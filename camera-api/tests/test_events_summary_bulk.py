"""Hodisalar jurnali: summary (bitta so'rov), ommaviy ko'rib chiqish,
yangi filtrlar va saralash."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Building, Camera, Event
from app.routers import events as events_router
from tests.conftest import auth_headers

DAY = date(2026, 9, 10)
TASHKENT_OFFSET = timedelta(hours=5)


def local_moment(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc) - TASHKENT_OFFSET


@pytest.fixture
async def cameras(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    entrance = Camera(name="Kirish-A", ip="10.8.0.1", building_id=building.id, zone="Z", resolution="1080p")
    corridor = Camera(name="Koridor-B", ip="10.8.0.2", building_id=building.id, zone="Z", resolution="1080p")
    db_session.add_all([entrance, corridor])
    await db_session.commit()
    return entrance, corridor


def make(camera, *, when=None, severity="past", status="yangi", code=20, building="1-bino", person=None, reviewed_at=None):
    return Event(
        occurred_at=when or datetime.now(timezone.utc), camera_id=camera.id, camera_name=camera.name,
        building=building, module_code=code, module_name=f"Modul {code}", group="D", confidence=60,
        severity=severity, status=status, person_name=person, reviewed_at=reviewed_at,
    )


@pytest.mark.usefixtures("seeded")
class TestSummary:
    async def test_counts_backlog_review_speed_and_facets(self, client: AsyncClient, db_session, cameras):
        entrance, corridor = cameras
        now = datetime.now(timezone.utc)
        occurred = now - timedelta(hours=2)
        db_session.add_all([
            make(entrance, severity="yuqori", code=21),
            make(entrance, when=now - timedelta(hours=30), severity="o'rta", code=19),
            make(corridor, when=occurred, status="tasdiqlangan", code=20, building="2-bino",
                 reviewed_at=occurred + timedelta(minutes=20)),
        ])
        await db_session.commit()

        headers = await auth_headers(client, "admin", "admin123")
        body = (await client.get("/api/events/summary", headers=headers)).json()
        assert (body["total"], body["unreviewed"], body["confirmed"], body["rejected"]) == (3, 2, 1, 0)
        assert (body["unreviewedHigh"], body["unreviewedMedium"], body["unreviewedLow"]) == (1, 1, 0)
        assert body["today"] >= 1
        assert body["staleSeriousUnreviewed"] == 1
        assert 29.5 <= body["oldestUnreviewedHours"] <= 30.5
        assert body["avgReviewMinutes"] == pytest.approx(20.0, abs=0.2)
        assert body["recentPrecision"] is None  # bitta ko'rib chiqilgan — foiz emas
        modules = {m["value"]: m for m in body["modules"]}
        assert modules["21"]["label"] == "Modul 21" and modules["21"]["count"] == 1
        buildings = {b["value"]: b["count"] for b in body["buildings"]}
        assert buildings == {"1-bino": 2, "2-bino": 1}

    async def test_precision_over_last_30_days(self, client: AsyncClient, db_session, cameras):
        entrance, _ = cameras
        recent = datetime.now(timezone.utc) - timedelta(days=1)
        db_session.add_all(
            [make(entrance, status="tasdiqlangan", reviewed_at=recent) for _ in range(8)]
            + [make(entrance, status="rad_etilgan", reviewed_at=recent) for _ in range(2)]
        )
        await db_session.commit()
        headers = await auth_headers(client, "admin", "admin123")
        body = (await client.get("/api/events/summary", headers=headers)).json()
        assert body["recentPrecision"] == 80.0


@pytest.mark.usefixtures("seeded")
class TestBulkReview:
    async def test_reviews_many_in_one_go_and_broadcasts_once(self, client: AsyncClient, db_session, cameras, monkeypatch):
        entrance, _ = cameras
        events = [make(entrance) for _ in range(3)]
        db_session.add_all(events)
        await db_session.commit()
        # expire_all() dan keyin obyekt atributlarini o'qish sinxron lazy-load
        # chaqiradi (async sessiyada xato) — identifikatorlar oldindan olinadi.
        event_ids = [e.id for e in events]

        sent: list[dict] = []

        async def capture(message: dict) -> None:
            sent.append(message)

        monkeypatch.setattr(events_router.manager, "broadcast", capture)
        headers = await auth_headers(client, "admin", "admin123")
        ids = [str(event_id) for event_id in event_ids] + [str(uuid.uuid4())]
        resp = await client.post("/api/events/review-bulk", headers=headers, json={"ids": ids, "status": "tasdiqlangan"})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"updated": 3, "skipped": 1, "status": "tasdiqlangan"}

        db_session.expire_all()
        rows = (await db_session.execute(select(Event).where(Event.id.in_(event_ids)))).scalars().all()
        assert all(r.status == "tasdiqlangan" and r.reviewed_at is not None and r.reviewed_by for r in rows)
        assert len(sent) == 1
        assert sent[0]["kind"] == "events_reviewed" and len(sent[0]["ids"]) == 3

    @pytest.mark.parametrize(
        "ids",
        [["not-a-uuid"], [], [str(uuid.uuid4()) for _ in range(201)]],
    )
    async def test_invalid_payloads_are_rejected(self, client: AsyncClient, ids):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post("/api/events/review-bulk", headers=headers, json={"ids": ids, "status": "rad_etilgan"})
        assert resp.status_code == 422

    async def test_single_review_records_when(self, client: AsyncClient, db_session, cameras):
        entrance, _ = cameras
        event = make(entrance)
        db_session.add(event)
        await db_session.commit()
        headers = await auth_headers(client, "admin", "admin123")
        body = (await client.patch(f"/api/events/{event.id}/review", headers=headers, json={"status": "rad_etilgan"})).json()
        assert body["status"] == "rad_etilgan"
        assert body["reviewedAt"]


@pytest.mark.usefixtures("seeded")
class TestFilters:
    async def test_modules_building_search_dates_and_severity_sort(self, client: AsyncClient, db_session, cameras):
        entrance, corridor = cameras
        db_session.add_all([
            make(entrance, when=local_moment(DAY, 7, 0), severity="past", code=21),
            make(entrance, when=local_moment(DAY, 12, 0), severity="yuqori", code=19),
            make(corridor, when=local_moment(DAY, 13, 0), severity="o'rta", code=20, building="2-bino",
                 person="Soxtaov Xodim"),
            make(entrance, when=local_moment(DAY - timedelta(days=1), 23, 30), code=21),
        ])
        await db_session.commit()
        headers = await auth_headers(client, "admin", "admin123")

        async def ids_for(**params):
            resp = await client.get("/api/events", headers=headers, params={"pageSize": 50, **params})
            assert resp.status_code == 200, resp.text
            return resp.json()["items"]

        day = DAY.isoformat()
        assert len(await ids_for(**{"from": day, "to": day})) == 3  # oldingi kun 23:30 kirmaydi
        assert len(await ids_for(moduleCodes="21,19")) == 3
        assert [e["building"] for e in await ids_for(building="2-bino")] == ["2-bino"]
        assert [e["cameraName"] for e in await ids_for(search="Koridor")] == ["Koridor-B"]
        assert [e["personName"] for e in await ids_for(search="Soxtaov")] == ["Soxtaov Xodim"]

        ordered = await ids_for(sort="severity", **{"from": day, "to": day})
        assert [e["severity"] for e in ordered] == ["yuqori", "o'rta", "past"]
        assert ordered[0]["occurredAt"].endswith("+05:00")

        assert (await client.get("/api/events", headers=headers, params={"cameraId": "x"})).status_code == 422
