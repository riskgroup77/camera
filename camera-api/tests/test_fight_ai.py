from dataclasses import dataclass

import cv2
import numpy as np
import pytest
from sqlalchemy import select

from app.jobs import fight_ai
from app.jobs.fight_ai import (
    FIGHT_MODULE_CODE,
    _people_in_close_proximity,
    _person_center,
    _recently_flagged,
    process_camera_frame_pair_for_fight,
    run_fight_ai_sweep_once,
)
from app.models import Building, Camera, Event
from app.services.pose_detection import LEFT_HIP, NOSE, RIGHT_HIP
from tests.conftest import TestSessionLocal


@dataclass
class _FakePose:
    points: np.ndarray


def _pose_centered_at(x: float, y: float, use_hips: bool = True) -> _FakePose:
    points = np.zeros((33, 4))
    if use_hips:
        points[LEFT_HIP] = [x, y, 0.0, 1.0]
        points[RIGHT_HIP] = [x, y, 0.0, 1.0]
    else:
        points[NOSE] = [x, y, 0.0, 1.0]
    return _FakePose(points=points)


def _encode_jpeg(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def _blank_frame() -> bytes:
    return _encode_jpeg(np.full((100, 100, 3), 100, dtype=np.uint8))


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Hovli kamerasi", ip="10.0.9.30", building_id=building.id,
        zone="Hovli", resolution="1080p", status="faol",
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera, attribute_names=["building"])
    return camera


class TestPersonCenter:
    def test_uses_hip_midpoint_when_visible(self):
        pose = _pose_centered_at(0.4, 0.6, use_hips=True)
        assert _person_center(pose.points) == (0.4, 0.6)

    def test_falls_back_to_nose_when_hips_not_visible(self):
        pose = _pose_centered_at(0.3, 0.2, use_hips=False)
        assert _person_center(pose.points) == (0.3, 0.2)

    def test_none_when_nothing_is_visible(self):
        points = np.zeros((33, 4))
        assert _person_center(points) is None


class TestPeopleInCloseProximity:
    def test_two_close_people_are_in_proximity(self):
        poses = [_pose_centered_at(0.5, 0.5), _pose_centered_at(0.55, 0.5)]
        assert _people_in_close_proximity(poses) is True

    def test_two_far_apart_people_are_not_in_proximity(self):
        poses = [_pose_centered_at(0.1, 0.1), _pose_centered_at(0.9, 0.9)]
        assert _people_in_close_proximity(poses) is False

    def test_a_single_person_is_never_in_proximity(self):
        assert _people_in_close_proximity([_pose_centered_at(0.5, 0.5)]) is False

    def test_two_people_at_proximity_boundary(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "fight_proximity_threshold", 0.12)
        # Just inside threshold — centers 0.11 apart horizontally
        poses = [_pose_centered_at(0.5, 0.5), _pose_centered_at(0.61, 0.5)]
        assert _people_in_close_proximity(poses) is True

        # Just outside threshold
        poses_far = [_pose_centered_at(0.5, 0.5), _pose_centered_at(0.63, 0.5)]
        assert _people_in_close_proximity(poses_far) is False


@pytest.mark.usefixtures("seeded")
class TestRecentlyFlagged:
    async def test_no_prior_events_is_not_flagged(self, db_session, a_camera):
        assert await _recently_flagged(db_session, a_camera.id) is False

    async def test_recent_event_at_same_camera_is_flagged(self, db_session, a_camera):
        db_session.add(Event(
            camera_id=a_camera.id, camera_name=a_camera.name, building="Bino",
            module_code=FIGHT_MODULE_CODE, module_name="Jang", group="D",
            confidence=35, severity="yuqori", status="yangi",
        ))
        await db_session.commit()
        assert await _recently_flagged(db_session, a_camera.id) is True


@pytest.mark.usefixtures("seeded")
class TestProcessCameraFramePairForFight:
    async def test_fewer_than_two_poses_raises_no_event(self, db_session, a_camera, monkeypatch):
        async def fake_detect_poses(frame_bytes):
            return [_pose_centered_at(0.5, 0.5)]

        monkeypatch.setattr(fight_ai, "detect_poses", fake_detect_poses)
        raised = await process_camera_frame_pair_for_fight(_blank_frame(), _blank_frame(), db_session, a_camera)
        assert raised is False

    async def test_two_poses_far_apart_raises_no_event(self, db_session, a_camera, monkeypatch):
        async def fake_detect_poses(frame_bytes):
            return [_pose_centered_at(0.1, 0.1), _pose_centered_at(0.9, 0.9)]

        monkeypatch.setattr(fight_ai, "detect_poses", fake_detect_poses)
        raised = await process_camera_frame_pair_for_fight(_blank_frame(), _blank_frame(), db_session, a_camera)
        assert raised is False

    async def test_close_poses_without_a_motion_spike_raises_no_event(self, db_session, a_camera, monkeypatch):
        async def fake_detect_poses(frame_bytes):
            return [_pose_centered_at(0.5, 0.5), _pose_centered_at(0.52, 0.5)]

        monkeypatch.setattr(fight_ai, "detect_poses", fake_detect_poses)
        monkeypatch.setattr(fight_ai, "_is_motion_spike", lambda camera_id, magnitude, **kwargs: False)
        raised = await process_camera_frame_pair_for_fight(_blank_frame(), _blank_frame(), db_session, a_camera)
        assert raised is False

    async def test_close_poses_with_a_motion_spike_raises_an_event_at_low_confidence(self, db_session, a_camera, monkeypatch):
        async def fake_detect_poses(frame_bytes):
            return [_pose_centered_at(0.5, 0.5), _pose_centered_at(0.52, 0.5)]

        monkeypatch.setattr(fight_ai, "detect_poses", fake_detect_poses)
        monkeypatch.setattr(fight_ai, "_is_motion_spike", lambda camera_id, magnitude, **kwargs: True)
        raised = await process_camera_frame_pair_for_fight(_blank_frame(), _blank_frame(), db_session, a_camera)
        assert raised is True

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1
        assert events[0].module_code == FIGHT_MODULE_CODE
        assert events[0].confidence == 35  # deliberately the lowest confidence in the system
        assert events[0].severity == "yuqori"

    async def test_same_camera_within_dedup_window_is_not_reraised(self, db_session, a_camera, monkeypatch):
        async def fake_detect_poses(frame_bytes):
            return [_pose_centered_at(0.5, 0.5), _pose_centered_at(0.52, 0.5)]

        monkeypatch.setattr(fight_ai, "detect_poses", fake_detect_poses)
        monkeypatch.setattr(fight_ai, "_is_motion_spike", lambda camera_id, magnitude, **kwargs: True)
        first = await process_camera_frame_pair_for_fight(_blank_frame(), _blank_frame(), db_session, a_camera)
        second = await process_camera_frame_pair_for_fight(_blank_frame(), _blank_frame(), db_session, a_camera)
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
                name=f"Kamera {i}", ip=f"10.0.9.{i + 100}", stream_url=f"rtsp://fake/{i}",
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
            return _blank_frame(), _blank_frame()

        async def fake_detect_poses(frame_bytes):
            return []

        monkeypatch.setattr(fight_ai, "grab_frame_pair", flaky_grab_frame_pair)
        monkeypatch.setattr(fight_ai, "detect_poses", fake_detect_poses)

        await run_fight_ai_sweep_once(session_factory=TestSessionLocal)
        assert calls["n"] == 2  # both cameras were attempted despite the first one failing
