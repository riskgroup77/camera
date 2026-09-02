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

        # 4 distinct frames — the sleep burst covers everything: sleep[0]
        # doubles as primary_frame, and the unauthorized check reuses the
        # burst's first/last rather than grabbing its own pair (see
        # test_sleep_burst_is_reused_for_the_unauthorized_pair). Each is
        # detected exactly once.
        assert len(calls) == 4
        assert len(set(id(c) for c in calls)) == 4

        # The whole point: multiple calls were in flight at the same time,
        # not one strictly after another.
        assert in_flight["peak"] > 1

        # Every consumer got the right faces for the right frame.
        assert received["crowd_faces"] == [f"face-for-{sleep_frames[0]!r}"]
        assert received["attendance_faces"] == [f"face-for-{sleep_frames[0]!r}"]
        assert received["unauthorized_faces_a"] == [f"face-for-{sleep_frames[0]!r}"]
        assert received["unauthorized_faces_b"] == [f"face-for-{sleep_frames[-1]!r}"]
        assert received["sleep_frames_faces"] == [
            [f"face-for-{sleep_frames[0]!r}"],
            [f"face-for-{sleep_frames[1]!r}"],
            [f"face-for-{sleep_frames[2]!r}"],
            [f"face-for-{sleep_frames[3]!r}"],
        ]

    async def test_sleep_burst_is_reused_for_the_unauthorized_pair(
        self, db_session, a_camera, monkeypatch
    ):
        """Both modules are active on most cameras. Grabbing a separate
        frame pair for the unauthorized check on top of the sleep burst
        cost 6 frames and 6 detect_faces calls per camera when 4 already
        satisfy both — the dominant per-camera cost in the whole sweep."""
        sleep_frames = [_frame("s0"), _frame("s1"), _frame("s2"), _frame("s3")]
        pair_grabs = {"n": 0}

        async def fake_grab_frame_burst_for_camera(camera, count, gap_seconds):
            return sleep_frames

        async def fake_grab_frame_pair_for_camera(camera):
            pair_grabs["n"] += 1
            return (_frame("extra_a"), _frame("extra_b"))

        detected: list[bytes] = []

        async def fake_detect_faces(frame: bytes):
            detected.append(frame)
            return [f"face-for-{frame!r}"]

        received: dict[str, object] = {}

        async def fake_unauthorized(frame_a, frame_b, db, camera, **kwargs):
            received["frame_a"] = frame_a
            received["frame_b"] = frame_b
            received["faces_a"] = kwargs["faces_a"]
            received["faces_b"] = kwargs["faces_b"]
            return False

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
        monkeypatch.setattr(unified_face_sweep, "process_camera_frame_pair_for_unauthorized", fake_unauthorized)
        monkeypatch.setattr(unified_face_sweep, "process_camera_frame_for_sleep", fake_sleep_noop)

        from tests.conftest import TestSessionLocal

        await _process_camera(a_camera, _ALL_FLAGS, candidates=None, session_factory=TestSessionLocal)

        # No second trip to the camera...
        assert pair_grabs["n"] == 0
        # ...only the 4 burst frames are ever detected, not 6.
        assert len(detected) == 4
        # ...and the pair handed to the unauthorized check is the burst's
        # first and last, i.e. the MOST separated frames available.
        assert received["frame_a"] is sleep_frames[0]
        assert received["frame_b"] is sleep_frames[-1]
        assert received["faces_a"] == [f"face-for-{sleep_frames[0]!r}"]
        assert received["faces_b"] == [f"face-for-{sleep_frames[-1]!r}"]

    async def test_pair_is_still_grabbed_when_sleep_is_not_running(
        self, db_session, a_camera, monkeypatch
    ):
        """Reuse only applies when a burst actually exists — a camera with
        sleep detection off must still get its own pair."""
        pair = (_frame("pair_a"), _frame("pair_b"))
        pair_grabs = {"n": 0}

        async def fake_grab_frame_pair_for_camera(camera):
            pair_grabs["n"] += 1
            return pair

        async def fake_detect_faces(frame: bytes):
            return [f"face-for-{frame!r}"]

        async def fake_noop(*args, **kwargs):
            return False

        async def fake_process_camera_frame(*args, **kwargs):
            return []

        monkeypatch.setattr(unified_face_sweep, "grab_frame_pair_for_camera", fake_grab_frame_pair_for_camera)
        monkeypatch.setattr(unified_face_sweep, "detect_faces", fake_detect_faces)
        monkeypatch.setattr(unified_face_sweep, "process_camera_frame_for_crowd", fake_noop)
        monkeypatch.setattr(unified_face_sweep, "process_camera_frame", fake_process_camera_frame)
        monkeypatch.setattr(unified_face_sweep, "process_camera_frame_pair_for_unauthorized", fake_noop)

        from tests.conftest import TestSessionLocal

        flags = {**_ALL_FLAGS, "sleep": False}
        await _process_camera(a_camera, flags, candidates=None, session_factory=TestSessionLocal)

        assert pair_grabs["n"] == 1

    async def test_primary_frame_taken_from_the_pair_is_detected_once(
        self, db_session, a_camera, monkeypatch
    ):
        """With sleep off, primary_frame is set FROM the pair's second
        frame — the same object appears twice in what needs detecting, and
        must still be detected once. Identity dedup, not value dedup."""
        pair = (_frame("pair_a"), _frame("pair_b"))

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

        monkeypatch.setattr(unified_face_sweep, "grab_frame_pair_for_camera", fake_grab_frame_pair_for_camera)
        monkeypatch.setattr(unified_face_sweep, "detect_faces", fake_detect_faces)
        monkeypatch.setattr(unified_face_sweep, "process_camera_frame_for_crowd", fake_noop)
        monkeypatch.setattr(unified_face_sweep, "process_camera_frame", fake_process_camera_frame)
        monkeypatch.setattr(unified_face_sweep, "process_camera_frame_pair_for_unauthorized", fake_noop)

        from tests.conftest import TestSessionLocal

        flags = {**_ALL_FLAGS, "sleep": False}
        await _process_camera(a_camera, flags, candidates=None, session_factory=TestSessionLocal)

        # pair_b doubles as primary_frame -> 2 distinct objects, 2 calls.
        assert call_count["n"] == 2
