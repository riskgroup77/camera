"""_process_camera used to call detect_faces() once per `await`, strictly
sequentially, even for independent frames (the unauthorized pair, the
sleep burst) that have no data dependency on each other. Measured on
production: for a camera needing both sleep and unauthorized checks (up
to 6 frames), that serialized ~1.4s-per-call cost into ~10s of wall
clock for a single camera — the dominant cost behind a measured AI-sweep
backlog running far past its configured interval. These tests cover the
fix: detect_faces() calls are deduplicated by frame identity and issued
concurrently via asyncio.gather, with each module still receiving the
exact same faces list it always did."""

import asyncio

import pytest
from sqlalchemy import select

from app.jobs import unified_face_sweep
from app.jobs.unified_face_sweep import _process_camera
from app.models import Building, Camera


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Sinf kamerasi", ip="10.0.9.50", building_id=building.id, zone="Sinf",
        resolution="1080p", status="faol",
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera, attribute_names=["building"])
    return camera


_ALL_FLAGS = {
    "staff_attendance": True,
    "student_attendance": True,
    "off_hours": True,
    "crowd": True,
    "unauthorized": True,
    "sleep": True,
}


def _frame(tag: str) -> bytes:
    # A distinct bytes object per tag — object identity is what
    # _process_camera's dedup relies on (same pattern as the frame_b is
    # primary_frame checks that predate this change).
    return bytes(tag, "utf-8") + b"\x00" * 8


@pytest.mark.usefixtures("seeded")
class TestProcessCameraConcurrentFaceDetection:
    async def test_detect_faces_called_once_per_distinct_frame_concurrently(
        self, db_session, a_camera, monkeypatch
    ):
        sleep_frames = [_frame("sleep0"), _frame("sleep1"), _frame("sleep2"), _frame("sleep3")]
        pair = (_frame("pair_a"), _frame("pair_b"))

        async def fake_grab_frame_burst_for_camera(camera, count, gap_seconds):
            return sleep_frames

        async def fake_grab_frame_pair_for_camera(camera):
            return pair

        async def fake_grab_frame_for_camera(camera):
            raise AssertionError("primary_frame is already set by sleep's burst — should not be called")

        in_flight = {"n": 0, "peak": 0}
        calls: list[bytes] = []
        lock = asyncio.Lock()

        async def fake_detect_faces(frame: bytes):
            async with lock:
                in_flight["n"] += 1
                in_flight["peak"] = max(in_flight["peak"], in_flight["n"])
                calls.append(frame)
            await asyncio.sleep(0.02)  # long enough for concurrent calls to overlap
            async with lock:
                in_flight["n"] -= 1
            return [f"face-for-{frame!r}"]

        received: dict[str, object] = {}

        async def fake_process_camera_frame_for_crowd(frame, db, camera, faces):
            received["crowd_faces"] = faces
            return False

        async def fake_process_camera_frame(frame, db, camera, **kwargs):
            received["attendance_faces"] = kwargs["faces"]
            return []

        async def fake_process_camera_frame_pair_for_unauthorized(frame_a, frame_b, db, camera, **kwargs):
            received["unauthorized_faces_a"] = kwargs["faces_a"]
            received["unauthorized_faces_b"] = kwargs["faces_b"]
            return False

        async def fake_process_camera_frame_for_sleep(frames, db, camera, **kwargs):
            received["sleep_frames_faces"] = kwargs["frames_faces"]
            return 0

        monkeypatch.setattr(unified_face_sweep, "grab_frame_burst_for_camera", fake_grab_frame_burst_for_camera)
        monkeypatch.setattr(unified_face_sweep, "grab_frame_pair_for_camera", fake_grab_frame_pair_for_camera)
        monkeypatch.setattr(unified_face_sweep, "grab_frame_for_camera", fake_grab_frame_for_camera)
        monkeypatch.setattr(unified_face_sweep, "detect_faces", fake_detect_faces)
        monkeypatch.setattr(unified_face_sweep, "process_camera_frame_for_crowd", fake_process_camera_frame_for_crowd)
        monkeypatch.setattr(unified_face_sweep, "process_camera_frame", fake_process_camera_frame)
        monkeypatch.setattr(
            unified_face_sweep,
            "process_camera_frame_pair_for_unauthorized",
            fake_process_camera_frame_pair_for_unauthorized,
        )
        monkeypatch.setattr(
            unified_face_sweep, "process_camera_frame_for_sleep", fake_process_camera_frame_for_sleep
        )

        from tests.conftest import TestSessionLocal

        await _process_camera(a_camera, _ALL_FLAGS, candidates=None, session_factory=TestSessionLocal)

        # 5 distinct frames: sleep[0] doubles as primary_frame, so only
        # sleep[1..3] + pair_a + pair_b are additional — 6 total grabbed,
        # 6 distinct objects, each detected exactly once.
        assert len(calls) == 6
        assert len(set(id(c) for c in calls)) == 6

        # The whole point: multiple calls were in flight at the same time,
        # not one strictly after another.
        assert in_flight["peak"] > 1

        # Every consumer got the right faces for the right frame.
        assert received["crowd_faces"] == [f"face-for-{sleep_frames[0]!r}"]
        assert received["attendance_faces"] == [f"face-for-{sleep_frames[0]!r}"]
        assert received["unauthorized_faces_a"] == [f"face-for-{pair[0]!r}"]
        assert received["unauthorized_faces_b"] == [f"face-for-{pair[1]!r}"]
        assert received["sleep_frames_faces"] == [
            [f"face-for-{sleep_frames[0]!r}"],
            [f"face-for-{sleep_frames[1]!r}"],
            [f"face-for-{sleep_frames[2]!r}"],
            [f"face-for-{sleep_frames[3]!r}"],
        ]

    async def test_a_frame_shared_between_pair_and_sleep_is_detected_once(
        self, db_session, a_camera, monkeypatch
    ):
        # If the unauthorized pair's second frame happened to be the exact
        # same object as a sleep frame, it must still only be detected once.
        shared = _frame("shared")
        sleep_frames = [shared, _frame("sleep1")]
        pair = (_frame("pair_a"), shared)

        async def fake_grab_frame_burst_for_camera(camera, count, gap_seconds):
            return sleep_frames

        async def fake_grab_frame_pair_for_camera(camera):
            return pair

        call_count = {"n": 0}

        async def fake_detect_faces(frame: bytes):
            call_count["n"] += 1
            return [f"face-for-{frame!r}"]

        async def fake_noop(*args, **kwargs):
            return False

        async def fake_process_camera_frame(*args, **kwargs):
            return []

        async def fake_sleep_noop(*args, **kwargs):
            return 0

        monkeypatch.setattr(unified_face_sweep, "grab_frame_burst_for_camera", fake_grab_frame_burst_for_camera)
        monkeypatch.setattr(unified_face_sweep, "grab_frame_pair_for_camera", fake_grab_frame_pair_for_camera)
        monkeypatch.setattr(unified_face_sweep, "detect_faces", fake_detect_faces)
        monkeypatch.setattr(unified_face_sweep, "process_camera_frame_for_crowd", fake_noop)
        monkeypatch.setattr(unified_face_sweep, "process_camera_frame", fake_process_camera_frame)
        monkeypatch.setattr(unified_face_sweep, "process_camera_frame_pair_for_unauthorized", fake_noop)
        monkeypatch.setattr(unified_face_sweep, "process_camera_frame_for_sleep", fake_sleep_noop)

        from tests.conftest import TestSessionLocal

        await _process_camera(a_camera, _ALL_FLAGS, candidates=None, session_factory=TestSessionLocal)

        # 3 distinct frame objects (shared, pair_a, sleep1) -> 3 calls, not 4.
        assert call_count["n"] == 3
