"""Tergov qidiruvi: rasm bo'yicha odam/notanish yuz va odamning kunlik yo'li."""

import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy import select

from app.models import AuditLog, Building, Camera, PresenceVisit, StudentStaff, UnknownSighting, User
from app.security import hash_password
from app.services import face_recognition
from app.services.person_search import VisitRow, group_stops
from tests.conftest import auth_headers

pytestmark = pytest.mark.anyio

DAY = date(2026, 9, 23)
# Toshkentda 09:00 (UTC+5).
MORNING = datetime(2026, 9, 23, 4, 0, tzinfo=timezone.utc)


def _vec(seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=512)
    return list(v / np.linalg.norm(v))


def _near(base: list[float], noise: float, seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    v = np.asarray(base) + rng.normal(scale=noise, size=512)
    return list(v / np.linalg.norm(v))


QUERY = _vec(1)


@pytest.fixture(autouse=True)
def fake_embedding(monkeypatch):
    """InsightFace testda yo'q — rasm baytiga qarab tayyor vektor."""

    async def extract(data: bytes) -> list[float]:
        if data == b"yuzsiz":
            raise face_recognition.NoFaceDetectedError("Yuz aniqlanmadi (0 ta yuz topildi)")
        return QUERY

    monkeypatch.setattr(face_recognition, "extract_embedding", extract)


@pytest.fixture
async def world(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    cam_a = Camera(name="Kirish", ip="10.91.0.1", building_id=building.id, floor=1, zone="Eshik", resolution="1080p", status="faol")
    cam_b = Camera(name="Koridor", ip="10.91.0.2", building_id=building.id, floor=2, zone="Z", resolution="1080p", status="faol")
    target = StudentStaff(
        full_name="Qidiruv Maqsad",
        type="talaba",
        group_or_position="QA-1",
        biometrics_status="tasdiqlangan",
        biometric_embedding=json.dumps(_near(QUERY, 0.01, 2)),
    )
    other = StudentStaff(
        full_name="Boshqa Odam",
        type="xodim",
        group_or_position="Kafedra",
        biometrics_status="tasdiqlangan",
        biometric_embedding=json.dumps(_vec(99)),
    )
    db_session.add_all([cam_a, cam_b, target, other])
    await db_session.flush()
    db_session.add_all([
        UnknownSighting(
            day=DAY, camera_id=cam_b.id, first_seen_at=MORNING, last_seen_at=MORNING + timedelta(minutes=4),
            hits=3, embedding=json.dumps(_near(QUERY, 0.02, 3)), face_px=90,
        ),
        UnknownSighting(
            day=DAY, camera_id=cam_a.id, first_seen_at=MORNING, last_seen_at=MORNING,
            hits=1, embedding=json.dumps(_vec(50)), face_px=90,
        ),
        # Oraliqdan tashqarida — natijaga tushmasligi kerak.
        UnknownSighting(
            day=DAY - timedelta(days=40), camera_id=cam_b.id, first_seen_at=MORNING - timedelta(days=40),
            last_seen_at=MORNING - timedelta(days=40), hits=1, embedding=json.dumps(_near(QUERY, 0.02, 4)), face_px=90,
        ),
        PresenceVisit(student_staff_id=target.id, camera_id=cam_a.id, first_seen_at=MORNING, last_seen_at=MORNING + timedelta(minutes=1), sightings=2, best_similarity=0.61),
    ])
    await db_session.commit()
    return {"target": target, "other": other, "cam_a": cam_a, "cam_b": cam_b}


async def _search(client, headers, data: bytes = b"rasm", **form):
    return await client.post(
        "/api/person-locator/rasm",
        headers=headers,
        files={"photo": ("q.jpg", data, "image/jpeg")},
        data={"dan": "2026-09-20", "gacha": "2026-09-24", **form},
    )


async def test_photo_search_finds_enrolled_and_unknown(client, db_session, world):
    headers = await auth_headers(client, "admin", "admin123")
    response = await _search(client, headers)
    assert response.status_code == 200, response.text
    body = response.json()

    assert [p["id"] for p in body["people"]] == [str(world["target"].id)]
    person = body["people"][0]
    assert person["fullName"] == "Qidiruv Maqsad"
    assert person["similarity"] > 0.9
    assert person["lastSeenAt"] is not None

    assert len(body["sightings"]) == 1
    sighting = body["sightings"][0]
    assert sighting["cameraId"] == str(world["cam_b"].id)
    assert sighting["cameraName"] == "Koridor"
    assert sighting["hits"] == 3
    assert sighting["similarity"] > 0.9

    audit = (await db_session.execute(select(AuditLog).where(AuditLog.module == "Shaxs qidirish"))).scalars().all()
    assert any(row.action.startswith("Rasm bo'yicha qidiruv") for row in audit)


async def test_photo_search_min_threshold_filters(client, world):
    headers = await auth_headers(client, "admin", "admin123")
    body = (await _search(client, headers, min="0.999")).json()
    assert body["people"] == []
    assert body["sightings"] == []


async def test_photo_without_face_is_422(client, world):
    headers = await auth_headers(client, "admin", "admin123")
    response = await _search(client, headers, data=b"yuzsiz")
    assert response.status_code == 422
    assert "yuz topilmadi" in response.json()["detail"]


async def test_photo_search_rejects_long_range(client, world):
    headers = await auth_headers(client, "admin", "admin123")
    response = await _search(client, headers, dan="2026-01-01")
    assert response.status_code == 422


async def test_photo_search_requires_view_live(client, db_session, world):
    db_session.add(User(login="masul-qidiruv", password_hash=hash_password("Masul-12345"), full_name="Mas'ul", role="kamera-masuli"))
    await db_session.commit()
    headers = await auth_headers(client, "masul-qidiruv", "Masul-12345")
    assert (await _search(client, headers)).status_code == 403
    route = await client.get(f"/api/person-locator/{world['target'].id}/yol?sana=2026-09-23", headers=headers)
    assert route.status_code == 403
    assert (await _search(client, {})).status_code == 401


async def test_route_groups_consecutive_visits(client, db_session, world):
    target, cam_a, cam_b = world["target"], world["cam_a"], world["cam_b"]
    db_session.add_all([
        # Kirish (09:00 fixture) + 2 daqiqadan keyin yana Kirish -> bitta to'xtash.
        PresenceVisit(student_staff_id=target.id, camera_id=cam_a.id, first_seen_at=MORNING + timedelta(minutes=3), last_seen_at=MORNING + timedelta(minutes=5), sightings=3, best_similarity=0.7),
        PresenceVisit(student_staff_id=target.id, camera_id=cam_b.id, first_seen_at=MORNING + timedelta(minutes=10), last_seen_at=MORNING + timedelta(minutes=12), sightings=1),
        PresenceVisit(student_staff_id=target.id, camera_id=cam_a.id, first_seen_at=MORNING + timedelta(minutes=20), last_seen_at=MORNING + timedelta(minutes=21), sightings=1),
        # Boshqa kun — tushmaydi.
        PresenceVisit(student_staff_id=target.id, camera_id=cam_b.id, first_seen_at=MORNING + timedelta(days=1), last_seen_at=MORNING + timedelta(days=1), sightings=1),
    ])
    await db_session.commit()
    headers = await auth_headers(client, "admin", "admin123")
    response = await client.get(f"/api/person-locator/{target.id}/yol?sana=2026-09-23", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["day"] == "2026-09-23"
    stops = body["stops"]
    assert [s["cameraName"] for s in stops] == ["Kirish", "Koridor", "Kirish"]
    first = stops[0]
    assert first["count"] == 5
    assert first["bestSimilarity"] == pytest.approx(0.7)
    assert first["floor"] == 1
    assert first["building"]
    assert datetime.fromisoformat(first["endedAt"]) == MORNING + timedelta(minutes=5)


async def test_route_unknown_person_404(client, world):
    headers = await auth_headers(client, "admin", "admin123")
    response = await client.get("/api/person-locator/not-a-uuid/yol", headers=headers)
    assert response.status_code == 404


def test_group_stops_splits_on_long_gap():
    t = MORNING
    visits = [
        VisitRow("a", "A", None, None, None, t, t + timedelta(minutes=1), 1, None),
        VisitRow("a", "A", None, None, None, t + timedelta(minutes=10), t + timedelta(minutes=11), 1, 0.5),
    ]
    stops = group_stops(visits)
    assert len(stops) == 2
    assert stops[1].best_similarity == 0.5
