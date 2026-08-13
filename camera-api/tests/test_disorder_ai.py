import cv2
import numpy as np
import pytest
from sqlalchemy import select

from app.jobs import disorder_ai
from app.jobs.disorder_ai import (
    DISORDER_MODULE_CODE,
    _is_motion_spike,
    _mean_flow_magnitude,
    _recently_flagged,
    process_camera_frame_pair_for_disorder,
    run_disorder_ai_sweep_once,
)
from app.models import Building, Camera, Event
from tests.conftest import TestSessionLocal


def _textured_frame(size=(200, 200)) -> np.ndarray:
    """A checkerboard pattern -- Farneback optical flow needs real
    gradients to track; a flat solid color has none."""
    x = np.arange(size[1])
    y = np.arange(size[0])
    xv, yv = np.meshgrid(x, y)
    return (((xv // 10) + (yv // 10)) % 2 * 200 + 20).astype(np.uint8)


def _shift(img: np.ndarray, dx: int, dy: int) -> np.ndarray:
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_REFLECT)


def _encode_jpeg_gray(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Zinapoya kamerasi", ip="10.0.9.8", building_id=building.id,
        zone="Zinapoya", resolution="1080p", status="faol",
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera, attribute_names=["building"])
    return camera


class TestMeanFlowMagnitude:
    def test_identical_frames_have_near_zero_magnitude(self):
        frame = _textured_frame()
        assert _mean_flow_magnitude(frame, frame) < 0.01

    def test_shifted_frame_has_higher_magnitude(self):
        frame = _textured_frame()
        shifted = _shift(frame, 8, 0)
        assert _mean_flow_magnitude(frame, shifted) > 2.0


class TestIsMotionSpike:
    def test_no_history_yet_is_never_a_spike(self):
        assert _is_motion_spike("cam-motion-fresh-1", 50.0) is False

    def test_below_absolute_floor_is_never_a_spike(self):
        camera_id = "cam-motion-quiet-1"
        for m in [0.0001, 0.0001, 0.0001, 0.0001, 0.0001]:
            _is_motion_spike(camera_id, m)
        assert _is_motion_spike(camera_id, 0.5) is False  # under disorder_min_absolute_magnitude (1.5)

    def test_multiplier_and_absolute_floor_both_cleared_is_a_spike(self):
        camera_id = "cam-motion-normal-1"
        for m in [1.0, 1.0, 1.0, 1.0, 1.0]:  # baseline settles at 1.0
            _is_motion_spike(camera_id, m)
        # 1.0 * 3.0 = 3.0, and 3.0 >= min_absolute_magnitude(1.5)
        assert _is_motion_spike(camera_id, 4.0) is True

    def test_below_multiplier_threshold_is_not_a_spike(self):
        camera_id = "cam-motion-normal-2"
        for m in [1.0, 1.0, 1.0, 1.0, 1.0]:
            _is_motion_spike(camera_id, m)
        assert _is_motion_spike(camera_id, 2.0) is False  # 2.0 < 1.0*3.0=3.0


@pytest.mark.usefixtures("seeded")
class TestProcessCameraFramePairForDisorder:
    async def test_recently_flagged_dedup(self, db_session, a_camera):
        assert await _recently_flagged(db_session, a_camera.id) is False
        db_session.add(Event(
            camera_id=a_camera.id, camera_name=a_camera.name, building="Bino",
            module_code=DISORDER_MODULE_CODE, module_name="Tartibsizlik", group="D",
            confidence=55, severity="past", status="yangi",
        ))
        await db_session.commit()
        assert await _recently_flagged(db_session, a_camera.id) is True

    async def test_mismatched_frame_sizes_are_skipped_safely(self, db_session, a_camera):
        small = _encode_jpeg_gray(_textured_frame((50, 50)))
        big = _encode_jpeg_gray(_textured_frame((200, 200)))
        raised = await process_camera_frame_pair_for_disorder(small, big, db_session, a_camera)
        assert raised is False

    async def test_sudden_large_motion_after_a_calm_baseline_raises(self, db_session, a_camera):
        base = _textured_frame()
        calm_pair = (_encode_jpeg_gray(base), _encode_jpeg_gray(base))

        results = []
        for _ in range(5):
            results.append(await process_camera_frame_pair_for_disorder(*calm_pair, db_session, a_camera))
        assert not any(results)

        shifted = _shift(base, 10, 0)
        spike_pair = (_encode_jpeg_gray(base), _encode_jpeg_gray(shifted))
        raised = await process_camera_frame_pair_for_disorder(*spike_pair, db_session, a_camera)
        assert raised is True

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1
        assert events[0].module_code == DISORDER_MODULE_CODE
        assert events[0].camera_name == a_camera.name


@pytest.mark.usefixtures("seeded")
class TestSweepConcurrency:
    async def test_one_camera_failing_does_not_stop_the_others(self, db_session, seeded, monkeypatch):
        building = (await db_session.execute(select(Building))).scalars().first()
        cameras = []
        for i in range(2):
            from datetime import datetime, timezone

            camera = Camera(
                name=f"Kamera {i}", ip=f"10.0.9.{i + 40}", stream_url=f"rtsp://fake/{i}",
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
            frame = _encode_jpeg_gray(_textured_frame())
            return frame, frame

        monkeypatch.setattr(disorder_ai, "grab_frame_pair", flaky_grab_frame_pair)

        await run_disorder_ai_sweep_once(session_factory=TestSessionLocal)
        assert calls["n"] == 2  # both cameras were attempted despite the first one failing
