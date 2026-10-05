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
from types import SimpleNamespace

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
    "unauthorized": True,
    "sleep": True,
}


def _frame(tag: str) -> bytes:
    # A distinct bytes object per tag — object identity is what
    # _process_camera's dedup relies on (same pattern as the frame_b is
    # primary_frame checks that predate this change).
    return bytes(tag, "utf-8") + b"\x00" * 8


@pytest.mark.usefixtures("seeded")
class _FakeFace(str):
    """Yuz o'rnidagi belgi: satr sifatida solishtiriladi, lekin uyqu
    tekshiruvi uchun yetarlicha yirik ramkaga ega."""

    bbox = (0.0, 0.0, 120.0, 140.0)


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
            return [_FakeFace(f"face-for-{frame!r}")]

        received: dict[str, object] = {}

        async def fake_process_camera_frame_pair_for_unauthorized(frame_a, frame_b, db, camera, **kwargs):
            received["unauthorized_faces_a"] = kwargs["faces_a"]
            received["unauthorized_faces_b"] = kwargs["faces_b"]
            return False

        async def fake_process_camera_frame_for_sleep(frames, db, camera, **kwargs):
            received["sleep_frames_faces"] = kwargs["frames_faces"]
            return 0

        monkeypatch.setattr(unified_face_sweep, "grab_frame_burst_for_camera", fake_grab_frame_burst_for_camera)
        monkeypatch.setattr(unified_face_sweep, "grab_frame_pair_for_camera", fake_grab_frame_pair_for_camera)
        monkeypatch.setattr(unified_face_sweep, "detect_faces", fake_detect_faces)
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

        # 4 distinct frames — the sleep burst covers everything: the
        # unauthorized check reuses the burst's first/last rather than
        # grabbing its own pair (see
        # test_sleep_burst_is_reused_for_the_unauthorized_pair). Each is
        # detected exactly once.
        assert len(calls) == 4
        assert len(set(id(c) for c in calls)) == 4

        # The whole point: multiple calls were in flight at the same time,
        # not one strictly after another.
        assert in_flight["peak"] > 1

        # Every consumer got the right faces for the right frame.
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
            return [_FakeFace(f"face-for-{frame!r}")]

        received: dict[str, object] = {}

        async def fake_unauthorized(frame_a, frame_b, db, camera, **kwargs):
            received["frame_a"] = frame_a
            received["frame_b"] = frame_b
            received["faces_a"] = kwargs["faces_a"]
            received["faces_b"] = kwargs["faces_b"]
            return False

        async def fake_noop(*args, **kwargs):
            return False

        async def fake_sleep_noop(*args, **kwargs):
            return 0

        monkeypatch.setattr(unified_face_sweep, "grab_frame_burst_for_camera", fake_grab_frame_burst_for_camera)
        monkeypatch.setattr(unified_face_sweep, "grab_frame_pair_for_camera", fake_grab_frame_pair_for_camera)
        monkeypatch.setattr(unified_face_sweep, "detect_faces", fake_detect_faces)
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
            return [_FakeFace(f"face-for-{frame!r}")]

        async def fake_noop(*args, **kwargs):
            return False

        monkeypatch.setattr(unified_face_sweep, "grab_frame_pair_for_camera", fake_grab_frame_pair_for_camera)
        monkeypatch.setattr(unified_face_sweep, "detect_faces", fake_detect_faces)
        monkeypatch.setattr(unified_face_sweep, "process_camera_frame_pair_for_unauthorized", fake_noop)

        from tests.conftest import TestSessionLocal

        flags = {**_ALL_FLAGS, "sleep": False}
        await _process_camera(a_camera, flags, candidates=None, session_factory=TestSessionLocal)

        assert pair_grabs["n"] == 1

    async def test_each_pair_frame_is_detected_once(
        self, db_session, a_camera, monkeypatch
    ):
        """With sleep off, only the unauthorized pair is analysed — each of
        its two frames exactly once. Identity dedup, not value dedup."""
        pair = (_frame("pair_a"), _frame("pair_b"))

        async def fake_grab_frame_pair_for_camera(camera):
            return pair

        call_count = {"n": 0}

        async def fake_detect_faces(frame: bytes):
            call_count["n"] += 1
            return [_FakeFace(f"face-for-{frame!r}")]

        async def fake_noop(*args, **kwargs):
            return False

        monkeypatch.setattr(unified_face_sweep, "grab_frame_pair_for_camera", fake_grab_frame_pair_for_camera)
        monkeypatch.setattr(unified_face_sweep, "detect_faces", fake_detect_faces)
        monkeypatch.setattr(unified_face_sweep, "process_camera_frame_pair_for_unauthorized", fake_noop)

        from tests.conftest import TestSessionLocal

        flags = {**_ALL_FLAGS, "sleep": False}
        await _process_camera(a_camera, flags, candidates=None, session_factory=TestSessionLocal)

        # 2 distinct objects, 2 calls.
        assert call_count["n"] == 2


# ─────────────────────────── Kunduzgi ko'rib chiqish rejimi (begona shaxs)

@pytest.mark.usefixtures("seeded")
class TestDaytimeReviewMode:
    """Kunduzi notanish yuz signal emas — ro'yxatga tushadi. Kechasi esa
    oldingidek signal. Bir xil kadr juftligi, faqat natija boshqacha."""

    async def _run(self, a_camera, monkeypatch, flags):
        pair = (_frame("pair_a"), _frame("pair_b"))
        seen: dict[str, object] = {}

        async def fake_grab_frame_pair_for_camera(camera):
            return pair

        async def fake_detect_faces(frame: bytes):
            return ["yuz"]

        async def fake_unauthorized(frame_a, frame_b, db, camera, **kwargs):
            seen["review"] = kwargs.get("review")
            return True

        monkeypatch.setattr(unified_face_sweep, "grab_frame_pair_for_camera", fake_grab_frame_pair_for_camera)
        monkeypatch.setattr(unified_face_sweep, "detect_faces", fake_detect_faces)
        monkeypatch.setattr(unified_face_sweep, "process_camera_frame_pair_for_unauthorized", fake_unauthorized)

        from tests.conftest import TestSessionLocal

        await _process_camera(a_camera, flags, candidates=None, session_factory=TestSessionLocal)
        return seen

    async def test_daytime_runs_in_review_mode(self, db_session, a_camera, monkeypatch):
        seen = await self._run(a_camera, monkeypatch, {"unauthorized": False, "sleep": False, "review": True})
        assert seen["review"] is True

    async def test_night_raises_alarms_not_review(self, db_session, a_camera, monkeypatch):
        seen = await self._run(a_camera, monkeypatch, {"unauthorized": True, "sleep": False, "review": False})
        assert seen["review"] is False

    async def test_nothing_runs_when_both_off(self, db_session, a_camera, monkeypatch):
        seen = await self._run(a_camera, monkeypatch, {"unauthorized": False, "sleep": False, "review": False})
        assert seen == {}


class TestSleepBurstSkip:
    async def test_small_faces_skip_the_rest_of_the_burst(self, db_session, a_camera, monkeypatch):
        """Birinchi kadrda uyqu o'lchanadigan yirik yuz yo'q — qolgan 3 kadr tahlil qilinmaydi."""
        frames = [_frame("q0"), _frame("q1"), _frame("q2"), _frame("q3")]
        detected: list[bytes] = []

        async def fake_burst(camera, count, gap_seconds):
            return frames

        async def fake_detect(frame: bytes):
            detected.append(frame)
            return [SimpleNamespace(bbox=(0.0, 0.0, 20.0, 24.0))]

        async def fake_sleep(*args, **kwargs):
            raise AssertionError("uyqu tekshiruvi chaqirilmasligi kerak")

        monkeypatch.setattr(unified_face_sweep, "grab_frame_burst_for_camera", fake_burst)
        monkeypatch.setattr(unified_face_sweep, "detect_faces", fake_detect)
        monkeypatch.setattr(unified_face_sweep, "process_camera_frame_for_sleep", fake_sleep)
        from tests.conftest import TestSessionLocal

        flags = {"unauthorized": False, "review": False, "sleep": True}
        counts = await _process_camera(a_camera, flags, candidates=None, session_factory=TestSessionLocal)
        assert detected == [frames[0]]
        assert counts["sleep"] == 0



class TestArrivalOnAnyCamera:
    """2026-09-26: kelish istalgan kamerada — koridor kamerasi odamni aniq
    tanisa, kunning birinchi ko'rinishi "keldi" bo'ladi."""

    async def test_corridor_camera_records_first_arrival(self, db_session, a_camera, monkeypatch):
        import json
        import uuid

        import numpy as np

        from app.models import AttendanceRecord, PresenceVisit, StudentStaff
        from app.services.face_matching import invalidate_candidate_matrix_cache, load_candidate_matrix
        from tests.conftest import TestSessionLocal

        vector = np.random.default_rng(3).normal(size=512)
        vector /= np.linalg.norm(vector)
        other = np.random.default_rng(4).normal(size=512)
        other /= np.linalg.norm(other)
        person = StudentStaff(id=uuid.uuid4(), full_name="Koridor Xodim", type="xodim", group_or_position="Bo'lim",
                              biometrics_status="tasdiqlangan", biometric_embedding=json.dumps(vector.tolist()))
        second = StudentStaff(id=uuid.uuid4(), full_name="Boshqa Xodim", type="xodim", group_or_position="Bo'lim",
                              biometrics_status="tasdiqlangan", biometric_embedding=json.dumps(other.tolist()))
        person_id = person.id
        db_session.add_all([person, second])
        await db_session.commit()
        invalidate_candidate_matrix_cache()
        candidates = await load_candidate_matrix(db_session)

        frame = _frame("corridor")

        async def fake_grab(camera, *args, **kwargs):
            return frame

        async def fake_detect(data, **kwargs):
            return [SimpleNamespace(embedding=vector, bbox=np.array([0, 0, 80, 100]))]

        from app.config import settings

        # Productiondagi kabi: kelish vaqti — istalgan kameradagi birinchi ko'rinish.
        monkeypatch.setattr(settings, "attendance_arrival_only", True)
        monkeypatch.setattr(unified_face_sweep, "grab_frame_for_camera", fake_grab)
        monkeypatch.setattr(unified_face_sweep, "detect_faces", fake_detect)
        flags = {"unauthorized": False, "sleep": False, "arrival": True}
        counts = await _process_camera(a_camera, flags, candidates, TestSessionLocal)
        assert counts["arrivals"] == 1

        db_session.expire_all()
        record = (await db_session.execute(select(AttendanceRecord).where(AttendanceRecord.student_staff_id == person_id))).scalar_one()
        assert record.status in ("keldi", "kech_keldi") and record.check_in is not None
        visits = (await db_session.execute(select(PresenceVisit).where(PresenceVisit.student_staff_id == person_id))).scalars().all()
        assert [v.camera_id for v in visits] == [a_camera.id]
