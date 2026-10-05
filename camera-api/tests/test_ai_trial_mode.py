"""Sinov rejimi, tezlik chegarasi va dalil: sinov signallari yoziladi, lekin
operator navbati, ogohlantirishlar va hisobotlarga chiqmaydi."""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.models import AIModuleConfig, Building, Camera, Event
from app.services import event_bus
from app.services.analytics import _core
from app.services.event_bus import raise_event
from app.timezone import local_now
from tests.conftest import auth_headers

TRIAL_CODE = 2  # taqiqlangan zona — seed'da sinov rejimi, chegara 65
WORKING_CODE = 1  # begona shaxs — ishchi rejim, chegara 70


@pytest.fixture
async def camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    cam = Camera(
        name="Sinov koridori",
        ip="10.0.0.91",
        building_id=building.id,
        zone="Koridor",
        resolution="1080p",
        status="faol",
        last_seen_at=datetime.now(timezone.utc),
    )
    db_session.add(cam)
    await db_session.commit()
    await db_session.refresh(cam, ["building"])
    return cam


@pytest.fixture
def broadcasts(monkeypatch):
    sent: list[dict] = []

    async def fake_broadcast(message):
        sent.append(message)

    monkeypatch.setattr(event_bus.manager, "broadcast", fake_broadcast)
    event_bus.reset_rate_limited_for_tests()
    return sent


async def _raise(db_session, camera, code, *, person_name=None, details=None):
    return await raise_event(
        db_session,
        camera=camera,
        module_code=code,
        module_name=f"Modul {code}",
        group="A",
        confidence=90,
        severity="yuqori",
        person_name=person_name,
        details=details,
    )


async def _module(db_session, code) -> AIModuleConfig:
    return (await db_session.execute(select(AIModuleConfig).where(AIModuleConfig.code == code))).scalar_one()


class TestTrialMode:
    async def test_seeded_modes(self, db_session, seeded):
        assert (await _module(db_session, 19)).mode == "sinov"
        assert (await _module(db_session, TRIAL_CODE)).mode == "sinov"
        assert (await _module(db_session, WORKING_CODE)).mode == "ishchi"

    async def test_trial_event_is_stored_but_never_broadcast(self, db_session, camera, broadcasts):
        trial = await _raise(db_session, camera, TRIAL_CODE)
        assert trial is not None and trial.is_trial is True
        assert broadcasts == []

        working = await _raise(db_session, camera, WORKING_CODE)
        assert working is not None and working.is_trial is False
        assert len(broadcasts) == 1 and broadcasts[0]["isTrial"] is False

    async def test_operator_views_exclude_trial_events(self, client: AsyncClient, db_session, camera, broadcasts):
        await _raise(db_session, camera, TRIAL_CODE)
        await _raise(db_session, camera, WORKING_CODE, details={"reason": "Sinov sababi", "metrics": {"closest": 0.3}})
        headers = await auth_headers(client, "admin", "admin123")

        journal = (await client.get("/api/events", headers=headers)).json()
        assert [item["moduleCode"] for item in journal["items"]] == [WORKING_CODE]
        assert journal["items"][0]["details"]["reason"] == "Sinov sababi"

        trial_only = (await client.get("/api/events", headers=headers, params={"trial": "true"})).json()
        assert [item["moduleCode"] for item in trial_only["items"]] == [TRIAL_CODE]
        assert trial_only["items"][0]["isTrial"] is True

        summary = (await client.get("/api/events/summary", headers=headers)).json()
        assert summary["total"] == 1 and summary["unreviewed"] == 1
        assert summary["trialUnreviewed"] == 1
        assert [facet["value"] for facet in summary["trialModules"]] == [str(TRIAL_CODE)]
        assert [facet["value"] for facet in summary["modules"]] == [str(WORKING_CODE)]

    async def test_reports_and_public_stats_ignore_trial_events(self, client: AsyncClient, db_session, camera, broadcasts):
        await _raise(db_session, camera, TRIAL_CODE)
        await _raise(db_session, camera, WORKING_CODE)
        today = local_now().date()
        core = await _core(db_session, today, today)
        assert core["serious"] == 1 and core["unreviewed"] == 1

        headers = await auth_headers(client, "admin", "admin123")
        stats = (await client.get("/api/public/stats", headers=headers)).json()
        assert stats["violations"] == 1


class TestRateLimit:
    async def test_anonymous_detections_are_capped_per_camera(self, db_session, camera, broadcasts, monkeypatch):
        monkeypatch.setattr(settings, "event_rate_limit_per_camera_hour", 2)
        assert await _raise(db_session, camera, WORKING_CODE) is not None
        assert await _raise(db_session, camera, WORKING_CODE) is not None
        assert await _raise(db_session, camera, WORKING_CODE) is None
        assert event_bus.rate_limited_counts() == {WORKING_CODE: 1}
        # Aniq odam haqidagi signal cheklanmaydi.
        assert await _raise(db_session, camera, WORKING_CODE, person_name="Soxta Shaxs") is not None

    async def test_module_wide_cap(self, db_session, camera, broadcasts, monkeypatch):
        monkeypatch.setattr(settings, "event_rate_limit_per_module_hour", 1)
        assert await _raise(db_session, camera, WORKING_CODE) is not None
        assert await _raise(db_session, camera, WORKING_CODE) is None


class TestTrialQuota:
    """Sinov signali namuna uchun yig'iladi: soatlik kvota to'lgach modul
    tekshirilmaydi ham, yozmaydi ham."""

    async def test_trial_events_are_capped_per_hour(self, db_session, camera, broadcasts, monkeypatch):
        monkeypatch.setattr(settings, "trial_events_per_module_hour", 2)
        monkeypatch.setattr(settings, "trial_events_per_camera_hour", 5)
        assert await _raise(db_session, camera, TRIAL_CODE) is not None
        assert await _raise(db_session, camera, TRIAL_CODE) is not None
        assert await _raise(db_session, camera, TRIAL_CODE) is None

    async def test_one_camera_cannot_use_the_whole_quota(self, db_session, camera, broadcasts, monkeypatch):
        monkeypatch.setattr(settings, "trial_events_per_module_hour", 10)
        monkeypatch.setattr(settings, "trial_events_per_camera_hour", 1)
        assert await _raise(db_session, camera, TRIAL_CODE) is not None
        assert await _raise(db_session, camera, TRIAL_CODE) is None

    async def test_sweep_stops_for_the_rest_of_the_hour(self, db_session, camera, broadcasts, monkeypatch):
        from app.jobs.module_status import is_module_active

        monkeypatch.setattr(settings, "trial_events_per_module_hour", 1)
        assert await is_module_active(db_session, TRIAL_CODE) is True
        await _raise(db_session, camera, TRIAL_CODE)
        assert await is_module_active(db_session, TRIAL_CODE) is False
        # Ishchi rejimdagi modulga ta'sir qilmaydi.
        assert await is_module_active(db_session, WORKING_CODE) is True

    async def test_working_modules_keep_their_own_limits(self, db_session, camera, broadcasts, monkeypatch):
        monkeypatch.setattr(settings, "trial_events_per_module_hour", 1)
        monkeypatch.setattr(settings, "event_rate_limit_per_camera_hour", 3)
        for _ in range(3):
            assert await _raise(db_session, camera, WORKING_CODE) is not None
        assert await _raise(db_session, camera, WORKING_CODE) is None


class TestTrialSampleAndPromotion:
    async def _trial_events(self, db_session, count, status="yangi"):
        for _ in range(count):
            db_session.add(
                Event(
                    camera_name="Sinov",
                    building="1-bino",
                    module_code=TRIAL_CODE,
                    module_name="Yong'in",
                    group="F",
                    confidence=50,
                    severity="yuqori",
                    status=status,
                    is_trial=True,
                    reviewed_at=datetime.now(timezone.utc) if status != "yangi" else None,
                )
            )
        await db_session.commit()

    async def test_sample_has_only_unreviewed_trial_events_of_the_module(self, client: AsyncClient, db_session, seeded):
        await self._trial_events(db_session, 2)
        await self._trial_events(db_session, 1, status="rad_etilgan")
        db_session.add(
            Event(camera_name="Boshqa", building="1-bino", module_code=WORKING_CODE, module_name="Begona",
                  group="A", confidence=90, severity="yuqori", status="yangi")
        )
        await db_session.commit()
        headers = await auth_headers(client, "admin", "admin123")

        sample = (await client.get(f"/api/ai-modules/{TRIAL_CODE}/trial-sample", headers=headers)).json()
        assert len(sample) == 2
        assert all(item["isTrial"] and item["status"] == "yangi" and item["moduleCode"] == TRIAL_CODE for item in sample)

    async def test_promotion_needs_enough_precise_reviews(self, client: AsyncClient, db_session, seeded):
        module = await _module(db_session, TRIAL_CODE)
        headers = await auth_headers(client, "admin", "admin123")
        body = {"threshold": module.threshold, "sensitivity": module.sensitivity, "active": module.active, "mode": "ishchi"}

        refused = await client.patch(f"/api/ai-modules/{module.id}", headers=headers, json=body)
        assert refused.status_code == 409

        await self._trial_events(db_session, 30, status="tasdiqlangan")
        listed = next(m for m in (await client.get("/api/ai-modules", headers=headers)).json() if m["code"] == TRIAL_CODE)
        assert listed["mode"] == "sinov" and listed["promotionReady"] is True

        promoted = await client.patch(f"/api/ai-modules/{module.id}", headers=headers, json=body)
        assert promoted.status_code == 200, promoted.text
        assert promoted.json()["mode"] == "ishchi"

    async def test_switching_to_trial_moves_pending_events_out_of_the_queue(
        self, client: AsyncClient, db_session, seeded
    ):
        for status_value in ("yangi", "yangi", "tasdiqlangan"):
            db_session.add(
                Event(camera_name="Kirish", building="1-bino", module_code=WORKING_CODE, module_name="Begona",
                      group="A", confidence=90, severity="yuqori", status=status_value)
            )
        await db_session.commit()
        module = await _module(db_session, WORKING_CODE)
        headers = await auth_headers(client, "admin", "admin123")
        body = {"threshold": module.threshold, "sensitivity": module.sensitivity, "active": module.active, "mode": "sinov"}

        assert (await client.patch(f"/api/ai-modules/{module.id}", headers=headers, json=body)).status_code == 200

        summary = (await client.get("/api/events/summary", headers=headers)).json()
        assert summary["unreviewed"] == 0 and summary["confirmed"] == 1
        assert summary["trialUnreviewed"] == 2

    async def test_back_to_trial_is_always_allowed(self, client: AsyncClient, db_session, seeded):
        module = await _module(db_session, WORKING_CODE)
        headers = await auth_headers(client, "admin", "admin123")
        body = {"threshold": module.threshold, "sensitivity": module.sensitivity, "active": module.active, "mode": "sinov"}
        resp = await client.patch(f"/api/ai-modules/{module.id}", headers=headers, json=body)
        assert resp.status_code == 200 and resp.json()["mode"] == "sinov"
