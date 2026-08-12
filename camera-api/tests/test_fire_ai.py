from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import settings
from app.jobs import fire_ai
from app.jobs.fire_ai import FIRE_MODULE_CODE, _recently_flagged, process_camera_frame_pair_for_fire
from app.models import Building, Camera, Event

FRAME_A = b"frame-a-placeholder"
FRAME_B = b"frame-b-placeholder"


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Dahliz kamerasi", ip="10.0.9.3", building_id=building.id,
        zone="Dahliz", resolution="1080p", status="faol",
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera, attribute_names=["building"])
    return camera


@pytest.mark.usefixtures("seeded")
class TestRecentlyFlagged:
    async def test_no_prior_events_is_not_flagged(self, db_session, a_camera):
        assert await _recently_flagged(db_session, a_camera.id) is False

    async def test_recent_event_at_same_camera_is_flagged(self, db_session, a_camera):
        db_session.add(Event(
            camera_id=a_camera.id, camera_name=a_camera.name, building="Bino",
            module_code=FIRE_MODULE_CODE, module_name="Yong'in / tutun aniqlash",
            group="F", confidence=80, severity="yuqori", status="yangi",
        ))
        await db_session.commit()
        assert await _recently_flagged(db_session, a_camera.id) is True

    async def test_event_outside_dedup_window_is_not_flagged(self, db_session, a_camera):
        stale = datetime.now(timezone.utc) - timedelta(minutes=settings.fire_dedup_minutes + 1)
        db_session.add(Event(
            camera_id=a_camera.id, camera_name=a_camera.name, building="Bino",
            module_code=FIRE_MODULE_CODE, module_name="Yong'in / tutun aniqlash",
            group="F", confidence=80, severity="yuqori", status="yangi", occurred_at=stale,
        ))
        await db_session.commit()
        assert await _recently_flagged(db_session, a_camera.id) is False


@pytest.mark.usefixtures("seeded")
class TestProcessCameraFramePairForFire:
    async def test_no_fire_detected_raises_no_event(self, db_session, a_camera, monkeypatch):
        monkeypatch.setattr(fire_ai, "is_likely_fire", lambda a, b: False)

        raised = await process_camera_frame_pair_for_fire(FRAME_A, FRAME_B, db_session, a_camera)
        assert raised is False

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 0

    async def test_fire_detected_raises_a_high_severity_event(self, db_session, a_camera, monkeypatch):
        monkeypatch.setattr(fire_ai, "is_likely_fire", lambda a, b: True)
        monkeypatch.setattr(fire_ai, "fire_pixel_fraction", lambda a, b: 0.05)

        raised = await process_camera_frame_pair_for_fire(FRAME_A, FRAME_B, db_session, a_camera)
        assert raised is True

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1
        assert events[0].module_code == FIRE_MODULE_CODE
        assert events[0].severity == "yuqori"
        assert events[0].camera_name == a_camera.name
        assert events[0].group == "F"

    async def test_repeated_fire_within_dedup_window_is_not_reraised(self, db_session, a_camera, monkeypatch):
        monkeypatch.setattr(fire_ai, "is_likely_fire", lambda a, b: True)
        monkeypatch.setattr(fire_ai, "fire_pixel_fraction", lambda a, b: 0.05)

        first = await process_camera_frame_pair_for_fire(FRAME_A, FRAME_B, db_session, a_camera)
        second = await process_camera_frame_pair_for_fire(FRAME_A, FRAME_B, db_session, a_camera)
        assert first is True
        assert second is False

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1
