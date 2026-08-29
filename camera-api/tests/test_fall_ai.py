from dataclasses import dataclass

import numpy as np
import pytest
from sqlalchemy import select

from app.jobs import fall_ai
from app.jobs.fall_ai import (
    FALL_MODULE_CODE,
    _recently_flagged,
    process_camera_frame_pair_for_fall,
    run_fall_ai_sweep_once,
)
from app.models import Building, Camera, Event
from tests.conftest import TestSessionLocal


@dataclass
class _FakePose:
    points: np.ndarray


def _fallen_pose() -> _FakePose:
    points = np.zeros((33, 4))
    points[0] = [0.1, 0.5, 0.0, 1.0]
    points[16] = [0.9, 0.5, 0.0, 1.0]
    points[27] = [0.5, 0.45, 0.0, 1.0]
    points[28] = [0.5, 0.55, 0.0, 1.0]
    return _FakePose(points=points)


def _standing_pose() -> _FakePose:
    points = np.zeros((33, 4))
    points[11] = [0.5, 0.2, 0.0, 1.0]
    points[12] = [0.5, 0.2, 0.0, 1.0]
    points[23] = [0.5, 0.6, 0.0, 1.0]
    points[24] = [0.5, 0.6, 0.0, 1.0]
    points[27] = [0.5, 1.0, 0.0, 1.0]
    points[28] = [0.5, 1.0, 0.0, 1.0]
    return _FakePose(points=points)


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Dahliz kamerasi", ip="10.0.9.11", building_id=building.id,
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
            module_code=FALL_MODULE_CODE, module_name="Yiqilish", group="F",
            confidence=65, severity="yuqori", status="yangi",
        ))
        await db_session.commit()
        assert await _recently_flagged(db_session, a_camera.id) is True


@pytest.mark.usefixtures("seeded")
class TestProcessCameraFramePairForFall:
    async def test_no_poses_raises_no_event(self, db_session, a_camera, monkeypatch):
        async def fake_detect_poses(frame_bytes):
            return []

        monkeypatch.setattr(fall_ai, "detect_poses", fake_detect_poses)
        raised = await process_camera_frame_pair_for_fall(b"a", b"b", db_session, a_camera)
        assert raised is False

    async def test_standing_pose_raises_no_event(self, db_session, a_camera, monkeypatch):
        async def fake_detect_poses(frame_bytes):
            return [_standing_pose()]

        monkeypatch.setattr(fall_ai, "detect_poses", fake_detect_poses)
        raised = await process_camera_frame_pair_for_fall(b"a", b"b", db_session, a_camera)
        assert raised is False

    async def test_fallen_only_in_second_frame_is_not_confirmed(self, db_session, a_camera, monkeypatch):
        call_count = {"n": 0}

        async def fake_detect_poses(frame_bytes):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [_fallen_pose()]  # frame_b
            return [_standing_pose()]  # frame_a

        monkeypatch.setattr(fall_ai, "detect_poses", fake_detect_poses)
        raised = await process_camera_frame_pair_for_fall(b"a", b"b", db_session, a_camera)
        assert raised is False

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 0

    async def test_fallen_in_both_frames_raises_an_event(self, db_session, a_camera, monkeypatch):
        async def fake_detect_poses(frame_bytes):
            return [_fallen_pose()]

        monkeypatch.setattr(fall_ai, "detect_poses", fake_detect_poses)
        raised = await process_camera_frame_pair_for_fall(b"a", b"b", db_session, a_camera)
        assert raised is True

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1
        assert events[0].module_code == FALL_MODULE_CODE
        assert events[0].severity == "yuqori"
        assert events[0].camera_name == a_camera.name

    async def test_same_camera_within_dedup_window_is_not_reraised(self, db_session, a_camera, monkeypatch):
        async def fake_detect_poses(frame_bytes):
            return [_fallen_pose()]

        monkeypatch.setattr(fall_ai, "detect_poses", fake_detect_poses)
        first = await process_camera_frame_pair_for_fall(b"a", b"b", db_session, a_camera)
        second = await process_camera_frame_pair_for_fall(b"a", b"b", db_session, a_camera)
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
                name=f"Kamera {i}", ip=f"10.0.9.{i + 70}", stream_url=f"rtsp://fake/{i}",
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

        async def fake_detect_poses(frame_bytes):
            return []

        monkeypatch.setattr(fall_ai, "grab_frame_pair_for_camera", flaky_grab_frame_pair)
        monkeypatch.setattr(fall_ai, "detect_poses", fake_detect_poses)

        await run_fall_ai_sweep_once(session_factory=TestSessionLocal)
        assert calls["n"] == 2  # both cameras were attempted despite the first one failing
