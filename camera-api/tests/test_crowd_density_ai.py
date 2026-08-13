from pathlib import Path

import insightface
import pytest
from sqlalchemy import select

from app.jobs import crowd_density_ai
from app.jobs.crowd_density_ai import (
    CROWD_MODULE_CODE,
    _is_spike,
    _recently_flagged,
    process_camera_frame_for_crowd,
    run_crowd_density_ai_sweep_once,
)
from app.models import Building, Camera, Event
from tests.conftest import TestSessionLocal

FACE_IMAGE_PATH = Path(insightface.__file__).parent / "data" / "images" / "t1.jpg"


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Hovli kamerasi", ip="10.0.9.4", building_id=building.id,
        zone="Hovli", resolution="1080p", status="faol",
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera, attribute_names=["building"])
    return camera


class TestIsSpike:
    def test_no_history_yet_is_never_a_spike(self):
        assert _is_spike("camera-fresh-1", 50) is False

    def test_below_absolute_floor_is_never_a_spike_even_if_relatively_high(self):
        camera_id = "camera-quiet-1"
        for count in [0, 0, 0, 0, 0]:
            _is_spike(camera_id, count)
        # 3 is way above a baseline of 0, but under crowd_min_absolute (4)
        assert _is_spike(camera_id, 3) is False

    def test_multiplier_and_absolute_floor_both_cleared_is_a_spike(self):
        camera_id = "camera-normal-1"
        for count in [3, 3, 3, 3, 3]:  # baseline settles at 3
            _is_spike(camera_id, count)
        # 3 * crowd_spike_multiplier(2.0) = 6, and 6 >= crowd_min_absolute(4)
        assert _is_spike(camera_id, 6) is True

    def test_below_multiplier_threshold_is_not_a_spike(self):
        camera_id = "camera-normal-2"
        for count in [3, 3, 3, 3, 3]:
            _is_spike(camera_id, count)
        assert _is_spike(camera_id, 5) is False  # 5 < 3*2.0=6

    def test_history_updates_even_when_not_a_spike(self):
        camera_id = "camera-tracking-1"
        for count in [10, 10, 10, 10, 10]:
            _is_spike(camera_id, count)
        history = crowd_density_ai._face_count_history[camera_id]
        assert list(history) == [10, 10, 10, 10, 10]


@pytest.mark.usefixtures("seeded")
class TestProcessCameraFrameForCrowd:
    async def test_recently_flagged_dedup(self, db_session, a_camera):
        assert await _recently_flagged(db_session, a_camera.id) is False
        db_session.add(Event(
            camera_id=a_camera.id, camera_name=a_camera.name, building="Bino",
            module_code=CROWD_MODULE_CODE, module_name="Olomon", group="A",
            confidence=60, severity="o'rta", status="yangi",
        ))
        await db_session.commit()
        assert await _recently_flagged(db_session, a_camera.id) is True

    async def test_first_ever_frame_never_raises(self, db_session, a_camera):
        # No baseline exists yet -- can't be a spike relative to nothing.
        frame = FACE_IMAGE_PATH.read_bytes()  # 6 real faces
        raised = await process_camera_frame_for_crowd(frame, db_session, a_camera)
        assert raised is False

    async def test_sudden_spike_after_a_settled_baseline_raises(self, db_session, a_camera, monkeypatch):
        call_count = {"n": 0}
        real_detect_faces = crowd_density_ai.detect_faces

        class _FakeFace:
            pass

        async def fake_detect_faces(frame_bytes):
            call_count["n"] += 1
            if call_count["n"] <= 5:
                return [_FakeFace(), _FakeFace()]  # baseline: 2 faces per tick
            return await real_detect_faces(frame_bytes)  # tick 6: real 6-face photo -> spike

        monkeypatch.setattr(crowd_density_ai, "detect_faces", fake_detect_faces)

        frame = FACE_IMAGE_PATH.read_bytes()
        results = []
        for _ in range(6):
            results.append(await process_camera_frame_for_crowd(frame, db_session, a_camera))

        assert results == [False, False, False, False, False, True]

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1
        assert events[0].module_code == CROWD_MODULE_CODE
        assert events[0].camera_name == a_camera.name


@pytest.mark.usefixtures("seeded")
class TestSweepConcurrency:
    async def test_one_camera_failing_does_not_stop_the_others(self, db_session, seeded, monkeypatch):
        building = (await db_session.execute(select(Building))).scalars().first()
        cameras = []
        for i in range(2):
            from datetime import datetime, timezone

            camera = Camera(
                name=f"Kamera {i}", ip=f"10.0.9.{i + 20}", stream_url=f"rtsp://fake/{i}",
                building_id=building.id, zone="Z", resolution="1080p", status="faol",
                last_seen_at=datetime.now(timezone.utc),
            )
            db_session.add(camera)
            cameras.append(camera)
        await db_session.commit()

        calls = {"n": 0}

        async def flaky_grab_frame(stream_url):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated grab failure")
            return FACE_IMAGE_PATH.read_bytes()

        monkeypatch.setattr(crowd_density_ai, "grab_frame", flaky_grab_frame)

        await run_crowd_density_ai_sweep_once(session_factory=TestSessionLocal)
        assert calls["n"] == 2  # both cameras were attempted despite the first one failing
