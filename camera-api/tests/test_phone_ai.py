import pytest
from sqlalchemy import select

from app.jobs import phone_ai
from app.jobs.phone_ai import (
    PHONE_MODULE_CODE,
    _recently_flagged,
    process_camera_frame_pair_for_phone,
    run_phone_ai_sweep_once,
)
from app.models import Building, Camera, Event
from app.services.object_detection import DetectedObject
from tests.conftest import TestSessionLocal

_PHONE_DETECTION = [DetectedObject(class_id=67, class_name="cell phone", confidence=0.8, bbox=(10.0, 10.0, 50.0, 90.0))]


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Imtihon zali kamerasi", ip="10.0.9.9", building_id=building.id,
        zone="Imtihon zali", resolution="1080p", status="faol",
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
            module_code=PHONE_MODULE_CODE, module_name="Telefon", group="D",
            confidence=80, severity="o'rta", status="yangi",
        ))
        await db_session.commit()
        assert await _recently_flagged(db_session, a_camera.id) is True


@pytest.mark.usefixtures("seeded")
class TestProcessCameraFramePairForPhone:
    async def test_no_phone_raises_no_event(self, db_session, a_camera, monkeypatch):
        async def fake_detect_objects(frame_bytes, class_ids, confidence=0.5):
            return []

        monkeypatch.setattr(phone_ai, "detect_objects", fake_detect_objects)
        raised = await process_camera_frame_pair_for_phone(b"a", b"b", db_session, a_camera)
        assert raised is False

    async def test_phone_only_in_second_frame_is_not_confirmed(self, db_session, a_camera, monkeypatch):
        call_count = {"n": 0}

        async def fake_detect_objects(frame_bytes, class_ids, confidence=0.5):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _PHONE_DETECTION  # frame_b: phone seen
            return []  # frame_a: nothing

        monkeypatch.setattr(phone_ai, "detect_objects", fake_detect_objects)
        raised = await process_camera_frame_pair_for_phone(b"a", b"b", db_session, a_camera)
        assert raised is False

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 0

    async def test_phone_in_both_frames_raises_an_event(self, db_session, a_camera, monkeypatch):
        async def fake_detect_objects(frame_bytes, class_ids, confidence=0.5):
            return _PHONE_DETECTION

        monkeypatch.setattr(phone_ai, "detect_objects", fake_detect_objects)
        raised = await process_camera_frame_pair_for_phone(b"a", b"b", db_session, a_camera)
        assert raised is True

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1
        assert events[0].module_code == PHONE_MODULE_CODE
        assert events[0].camera_name == a_camera.name
        assert events[0].confidence == 80  # 0.8 confidence scaled to 0-100

    async def test_same_camera_within_dedup_window_is_not_reraised(self, db_session, a_camera, monkeypatch):
        async def fake_detect_objects(frame_bytes, class_ids, confidence=0.5):
            return _PHONE_DETECTION

        monkeypatch.setattr(phone_ai, "detect_objects", fake_detect_objects)
        first = await process_camera_frame_pair_for_phone(b"a", b"b", db_session, a_camera)
        second = await process_camera_frame_pair_for_phone(b"a", b"b", db_session, a_camera)
        assert first is True
        assert second is False

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1


@pytest.mark.usefixtures("seeded")
class TestSweepConcurrency:
    async def test_one_camera_failing_does_not_stop_the_others(self, db_session, seeded, monkeypatch):
        building = (await db_session.execute(select(Building))).scalars().first()
        cameras = []
        for i in range(2):
            from datetime import datetime, timezone

            camera = Camera(
                name=f"Kamera {i}", ip=f"10.0.9.{i + 50}", stream_url=f"rtsp://fake/{i}",
                building_id=building.id, zone="Z", resolution="1080p", status="faol",
                last_seen_at=datetime.now(timezone.utc),
            )
            db_session.add(camera)
            cameras.append(camera)
        await db_session.commit()

        calls = {"n": 0}

        async def flaky_grab_frame_pair(stream_url, gap_seconds=1.0):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated grab failure")
            return b"a", b"b"

        async def fake_detect_objects(frame_bytes, class_ids, confidence=0.5):
            return []

        monkeypatch.setattr(phone_ai, "grab_frame_pair_for_camera", flaky_grab_frame_pair)
        monkeypatch.setattr(phone_ai, "detect_objects", fake_detect_objects)

        await run_phone_ai_sweep_once(session_factory=TestSessionLocal)
        assert calls["n"] == 2  # both cameras were attempted despite the first one failing
