from dataclasses import dataclass

import numpy as np
import pytest
from sqlalchemy import select

from app.jobs import zone_entry_ai
from app.jobs.zone_entry_ai import (
    ZONE_MODULE_CODE,
    _recently_flagged,
    process_camera_frame_pair_for_zone,
    run_zone_entry_ai_sweep_once,
)
from app.models import Building, Camera, Event
from tests.conftest import TestSessionLocal

SQUARE_ZONE = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]


@dataclass
class _FakePose:
    points: np.ndarray


def _pose_with_ankles_at(x: float, y: float) -> _FakePose:
    points = np.zeros((33, 4))
    points[27] = [x, y, 0.0, 1.0]
    points[28] = [x, y, 0.0, 1.0]
    return _FakePose(points=points)


@pytest.fixture
async def a_camera_with_zone(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Laboratoriya kamerasi", ip="10.0.9.12", building_id=building.id,
        zone="Laboratoriya", resolution="1080p", status="faol",
        restricted_zone_polygon=SQUARE_ZONE,
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera, attribute_names=["building"])
    return camera


@pytest.mark.usefixtures("seeded")
class TestRecentlyFlagged:
    async def test_no_prior_events_is_not_flagged(self, db_session, a_camera_with_zone):
        assert await _recently_flagged(db_session, a_camera_with_zone.id) is False

    async def test_recent_event_at_same_camera_is_flagged(self, db_session, a_camera_with_zone):
        db_session.add(Event(
            camera_id=a_camera_with_zone.id, camera_name=a_camera_with_zone.name, building="Bino",
            module_code=ZONE_MODULE_CODE, module_name="Taqiqlangan zona", group="A",
            confidence=65, severity="yuqori", status="yangi",
        ))
        await db_session.commit()
        assert await _recently_flagged(db_session, a_camera_with_zone.id) is True


@pytest.mark.usefixtures("seeded")
class TestProcessCameraFramePairForZone:
    async def test_camera_without_a_configured_zone_never_raises(self, db_session, seeded, monkeypatch):
        building = (await db_session.execute(select(Building))).scalars().first()
        camera = Camera(
            name="Zonasiz kamera", ip="10.0.9.13", building_id=building.id,
            zone="Z", resolution="1080p", status="faol",
        )
        db_session.add(camera)
        await db_session.commit()
        await db_session.refresh(camera, attribute_names=["building"])

        async def fake_detect_poses(frame_bytes):
            return [_pose_with_ankles_at(0.5, 0.5)]  # would be inside SQUARE_ZONE if there were one

        monkeypatch.setattr(zone_entry_ai, "detect_poses", fake_detect_poses)
        raised = await process_camera_frame_pair_for_zone(b"a", b"b", db_session, camera)
        assert raised is False

    async def test_no_person_in_zone_raises_no_event(self, db_session, a_camera_with_zone, monkeypatch):
        async def fake_detect_poses(frame_bytes):
            return [_pose_with_ankles_at(0.05, 0.05)]  # well outside SQUARE_ZONE

        monkeypatch.setattr(zone_entry_ai, "detect_poses", fake_detect_poses)
        raised = await process_camera_frame_pair_for_zone(b"a", b"b", db_session, a_camera_with_zone)
        assert raised is False

    async def test_person_in_zone_only_in_second_frame_is_not_confirmed(self, db_session, a_camera_with_zone, monkeypatch):
        call_count = {"n": 0}

        async def fake_detect_poses(frame_bytes):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [_pose_with_ankles_at(0.5, 0.5)]  # frame_b: inside
            return [_pose_with_ankles_at(0.05, 0.05)]  # frame_a: outside

        monkeypatch.setattr(zone_entry_ai, "detect_poses", fake_detect_poses)
        raised = await process_camera_frame_pair_for_zone(b"a", b"b", db_session, a_camera_with_zone)
        assert raised is False

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 0

    async def test_person_in_zone_in_both_frames_raises_an_event(self, db_session, a_camera_with_zone, monkeypatch):
        async def fake_detect_poses(frame_bytes):
            return [_pose_with_ankles_at(0.5, 0.5)]

        monkeypatch.setattr(zone_entry_ai, "detect_poses", fake_detect_poses)
        raised = await process_camera_frame_pair_for_zone(b"a", b"b", db_session, a_camera_with_zone)
        assert raised is True

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1
        assert events[0].module_code == ZONE_MODULE_CODE
        assert events[0].camera_name == a_camera_with_zone.name

    async def test_same_camera_within_dedup_window_is_not_reraised(self, db_session, a_camera_with_zone, monkeypatch):
        async def fake_detect_poses(frame_bytes):
            return [_pose_with_ankles_at(0.5, 0.5)]

        monkeypatch.setattr(zone_entry_ai, "detect_poses", fake_detect_poses)
        first = await process_camera_frame_pair_for_zone(b"a", b"b", db_session, a_camera_with_zone)
        second = await process_camera_frame_pair_for_zone(b"a", b"b", db_session, a_camera_with_zone)
        assert first is True
        assert second is False

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1


@pytest.mark.usefixtures("seeded")
class TestSweepConcurrency:
    async def test_camera_without_zone_is_excluded_from_the_sweep_entirely(self, db_session, seeded, monkeypatch):
        building = (await db_session.execute(select(Building))).scalars().first()
        from datetime import datetime, timezone

        with_zone = Camera(
            name="Zonali kamera", ip="10.0.9.14", stream_url="rtsp://fake/0",
            building_id=building.id, zone="Z", resolution="1080p", status="faol",
            last_seen_at=datetime.now(timezone.utc), restricted_zone_polygon=SQUARE_ZONE,
        )
        without_zone = Camera(
            name="Oddiy kamera", ip="10.0.9.15", stream_url="rtsp://fake/1",
            building_id=building.id, zone="Z", resolution="1080p", status="faol",
            last_seen_at=datetime.now(timezone.utc),
        )
        db_session.add_all([with_zone, without_zone])
        await db_session.commit()

        calls = {"n": 0}

        async def counting_grab_frame_pair(stream_url, gap_seconds=1.0):
            calls["n"] += 1
            return b"a", b"b"

        async def fake_detect_poses(frame_bytes):
            return []

        monkeypatch.setattr(zone_entry_ai, "grab_frame_pair_for_camera", counting_grab_frame_pair)
        monkeypatch.setattr(zone_entry_ai, "detect_poses", fake_detect_poses)

        await run_zone_entry_ai_sweep_once(session_factory=TestSessionLocal)
        assert calls["n"] == 1  # only the camera WITH a configured zone was even attempted

    async def test_one_camera_failing_does_not_stop_the_others(self, db_session, seeded, monkeypatch):
        building = (await db_session.execute(select(Building))).scalars().first()
        cameras = []
        for i in range(2):
            from datetime import datetime, timezone

            camera = Camera(
                name=f"Kamera {i}", ip=f"10.0.9.{i + 80}", stream_url=f"rtsp://fake/{i}",
                building_id=building.id, zone="Z", resolution="1080p", status="faol",
                last_seen_at=datetime.now(timezone.utc), restricted_zone_polygon=SQUARE_ZONE,
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

        monkeypatch.setattr(zone_entry_ai, "grab_frame_pair_for_camera", flaky_grab_frame_pair)
        monkeypatch.setattr(zone_entry_ai, "detect_poses", fake_detect_poses)

        await run_zone_entry_ai_sweep_once(session_factory=TestSessionLocal)
        assert calls["n"] == 2  # both cameras were attempted despite the first one failing
