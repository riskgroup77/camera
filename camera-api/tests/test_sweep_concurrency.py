"""Covers the scale-focused rewrite of the AI sweep loops
(app/jobs/attendance_ai.py, vision_ai.py, fire_ai.py): cameras now
process CONCURRENTLY within one sweep instead of one at a time, each on
its own DB session (session_factory), and one camera's failure must not
take down the rest of the sweep. See each module's run_*_sweep_once()
docstring for the reasoning."""

import json
from datetime import datetime, timezone
from pathlib import Path

import insightface
import pytest
from sqlalchemy import select

from app.jobs import attendance_ai, fire_ai, vision_ai
from app.jobs.attendance_ai import run_attendance_ai_sweep_once
from app.jobs.fire_ai import FIRE_MODULE_CODE, run_fire_ai_sweep_once
from app.jobs.vision_ai import run_vision_ai_sweep_once
from app.models import AIModuleConfig, Building, Camera, Faculty, StudentStaff
from app.services.face_recognition import extract_embedding
from tests.conftest import TestSessionLocal

FACE_IMAGE_PATH = Path(insightface.__file__).parent / "data" / "images" / "t1.jpg"


async def _set_module_active(db_session, code: int, active: bool) -> None:
    module = (
        await db_session.execute(select(AIModuleConfig).where(AIModuleConfig.code == code))
    ).scalar_one()
    module.active = active
    await db_session.commit()


@pytest.fixture
async def enrolled_student(db_session, seeded):
    faculty = (await db_session.execute(select(Faculty))).scalars().first()
    embedding = await extract_embedding(FACE_IMAGE_PATH.read_bytes())
    student = StudentStaff(
        full_name="Parallel Sinov",
        type="talaba",
        faculty_id=faculty.id,
        group_or_position="1",
        biometric_embedding=json.dumps(embedding),
    )
    db_session.add(student)
    await db_session.commit()
    return student


@pytest.fixture
async def two_cameras(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    cameras = []
    for i in range(2):
        camera = Camera(
            name=f"Kamera {i}",
            ip=f"10.0.9.{i + 1}",
            stream_url=f"rtsp://fake-stream/{i}",
            building_id=building.id,
            zone="Z",
            resolution="1080p",
            status="faol",
            last_seen_at=datetime.now(timezone.utc),
        )
        db_session.add(camera)
        cameras.append(camera)
    await db_session.commit()
    return cameras


@pytest.mark.usefixtures("seeded")
class TestAttendanceSweepConcurrency:
    async def test_sweep_processes_every_camera(self, db_session, enrolled_student, two_cameras, monkeypatch):
        async def fake_grab_frame(stream_url):
            return FACE_IMAGE_PATH.read_bytes()

        monkeypatch.setattr(attendance_ai, "grab_frame", fake_grab_frame)

        count = await run_attendance_ai_sweep_once(session_factory=TestSessionLocal)
        # Both cameras "see" the same enrolled face — process_camera_frame
        # returns one AttendanceRecord per camera tick regardless of
        # whether it's an insert or an on-conflict update, so both count.
        assert count == 2

    async def test_one_camera_failing_does_not_stop_the_others(
        self, db_session, enrolled_student, two_cameras, monkeypatch
    ):
        calls = {"n": 0}

        async def flaky_grab_frame(stream_url):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated grab failure")
            return FACE_IMAGE_PATH.read_bytes()

        monkeypatch.setattr(attendance_ai, "grab_frame", flaky_grab_frame)

        count = await run_attendance_ai_sweep_once(session_factory=TestSessionLocal)
        assert count == 1  # the other camera still got processed despite the failure
        assert calls["n"] == 2  # both cameras were actually attempted

    async def test_no_cameras_returns_zero_without_error(self, db_session, enrolled_student):
        count = await run_attendance_ai_sweep_once(session_factory=TestSessionLocal)
        assert count == 0

    async def test_no_enrolled_candidates_skips_grabbing_entirely(self, db_session, two_cameras, monkeypatch):
        calls = {"n": 0}

        async def counting_grab_frame(stream_url):
            calls["n"] += 1
            return FACE_IMAGE_PATH.read_bytes()

        monkeypatch.setattr(attendance_ai, "grab_frame", counting_grab_frame)

        count = await run_attendance_ai_sweep_once(session_factory=TestSessionLocal)
        assert count == 0
        assert calls["n"] == 0  # nobody enrolled — no point even grabbing frames

    async def test_both_attendance_modules_disabled_skips_the_sweep_entirely(
        self, db_session, enrolled_student, two_cameras, monkeypatch
    ):
        await _set_module_active(db_session, 6, False)  # xodim davomati
        await _set_module_active(db_session, 7, False)  # talaba davomati

        calls = {"n": 0}

        async def counting_grab_frame(stream_url):
            calls["n"] += 1
            return FACE_IMAGE_PATH.read_bytes()

        monkeypatch.setattr(attendance_ai, "grab_frame", counting_grab_frame)

        count = await run_attendance_ai_sweep_once(session_factory=TestSessionLocal)
        assert count == 0
        assert calls["n"] == 0  # module toggled off in the admin panel -> sweep never even looks at cameras

    async def test_only_one_of_staff_student_disabled_still_runs(
        self, db_session, enrolled_student, two_cameras, monkeypatch
    ):
        await _set_module_active(db_session, 6, False)  # xodim davomati off, talaba (7) stays on

        async def fake_grab_frame(stream_url):
            return FACE_IMAGE_PATH.read_bytes()

        monkeypatch.setattr(attendance_ai, "grab_frame", fake_grab_frame)

        count = await run_attendance_ai_sweep_once(session_factory=TestSessionLocal)
        assert count == 2  # student attendance module (#7) alone is enough to keep the sweep running


@pytest.mark.usefixtures("seeded")
class TestAttendanceEntranceBurst:
    async def _entrance_camera(self, db_session):
        building = (await db_session.execute(select(Building))).scalars().first()
        camera = Camera(
            name="Kirish kamerasi", ip="10.0.9.50", stream_url="rtsp://fake/entrance",
            building_id=building.id, zone="Kirish", resolution="1080p", status="faol",
            last_seen_at=datetime.now(timezone.utc), is_entrance=True,
        )
        db_session.add(camera)
        await db_session.commit()
        return camera

    async def test_entrance_camera_uses_burst_not_single_frame(self, db_session, enrolled_student, monkeypatch):
        camera = await self._entrance_camera(db_session)

        single_calls = {"n": 0}
        burst_calls = []

        async def fake_grab_frame(stream_url):
            single_calls["n"] += 1
            return FACE_IMAGE_PATH.read_bytes()

        async def fake_grab_frame_burst(stream_url, count, gap_seconds):
            burst_calls.append((stream_url, count, gap_seconds))
            return [FACE_IMAGE_PATH.read_bytes()] * count

        monkeypatch.setattr(attendance_ai, "grab_frame", fake_grab_frame)
        monkeypatch.setattr(attendance_ai, "grab_frame_burst", fake_grab_frame_burst)

        await run_attendance_ai_sweep_once(session_factory=TestSessionLocal)

        assert single_calls["n"] == 0  # entrance camera never uses the single-frame path
        assert len(burst_calls) == 1
        assert burst_calls[0][0] == camera.stream_url
        assert burst_calls[0][1] == 3  # settings.attendance_entrance_burst_frame_count default

    async def test_same_person_across_burst_frames_is_credited_once(
        self, db_session, enrolled_student, monkeypatch
    ):
        await self._entrance_camera(db_session)

        async def fake_grab_frame_burst(stream_url, count, gap_seconds):
            # Same enrolled face in all 3 burst frames -- should still
            # only produce ONE attendance credit, not three.
            return [FACE_IMAGE_PATH.read_bytes()] * count

        monkeypatch.setattr(attendance_ai, "grab_frame_burst", fake_grab_frame_burst)

        count = await run_attendance_ai_sweep_once(session_factory=TestSessionLocal)
        assert count == 1

    async def test_non_entrance_camera_still_uses_single_frame(
        self, db_session, enrolled_student, two_cameras, monkeypatch
    ):
        burst_calls = {"n": 0}

        async def fake_grab_frame(stream_url):
            return FACE_IMAGE_PATH.read_bytes()

        async def counting_grab_frame_burst(stream_url, count, gap_seconds):
            burst_calls["n"] += 1
            return [FACE_IMAGE_PATH.read_bytes()] * count

        monkeypatch.setattr(attendance_ai, "grab_frame", fake_grab_frame)
        monkeypatch.setattr(attendance_ai, "grab_frame_burst", counting_grab_frame_burst)

        await run_attendance_ai_sweep_once(session_factory=TestSessionLocal)
        assert burst_calls["n"] == 0  # two_cameras fixture has is_entrance=False (default)


@pytest.mark.usefixtures("seeded")
class TestVisionSweepConcurrency:
    async def test_sweep_processes_every_camera(self, db_session, two_cameras, monkeypatch):
        async def fake_grab_frame_burst(stream_url, count, gap_seconds):
            frame = FACE_IMAGE_PATH.read_bytes()
            return [frame] * count

        monkeypatch.setattr(vision_ai, "grab_frame_burst", fake_grab_frame_burst)
        monkeypatch.setattr(vision_ai, "is_asleep", lambda landmarks: False)  # no one is asleep — just prove the sweep runs both cameras without raising

        count = await run_vision_ai_sweep_once(session_factory=TestSessionLocal)
        assert count == 0  # is_asleep forced False — asserting this returns cleanly, not a specific count

    async def test_one_camera_failing_does_not_stop_the_others(self, db_session, two_cameras, monkeypatch):
        calls = {"n": 0}

        async def flaky_grab_frame_burst(stream_url, count, gap_seconds):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated grab failure")
            frame = FACE_IMAGE_PATH.read_bytes()
            return [frame] * count

        monkeypatch.setattr(vision_ai, "grab_frame_burst", flaky_grab_frame_burst)

        await run_vision_ai_sweep_once(session_factory=TestSessionLocal)
        assert calls["n"] == 2  # both cameras were attempted despite the first one failing


@pytest.mark.usefixtures("seeded")
class TestFireSweepConcurrency:
    async def test_one_camera_failing_does_not_stop_the_others(self, db_session, two_cameras, monkeypatch):
        calls = {"n": 0}

        async def flaky_grab_frame_pair(stream_url, gap_seconds=1.0):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated grab failure")
            return b"frame-a", b"frame-b"

        monkeypatch.setattr(fire_ai, "grab_frame_pair", flaky_grab_frame_pair)
        monkeypatch.setattr(fire_ai, "is_likely_fire", lambda a, b: False)

        count = await run_fire_ai_sweep_once(session_factory=TestSessionLocal)
        assert count == 0
        assert calls["n"] == 2  # both cameras were attempted despite the first one failing

    async def test_disabled_module_skips_the_sweep_before_touching_any_camera(
        self, db_session, two_cameras, monkeypatch
    ):
        """Representative of the same active-flag gate added to every
        other single-criterion job (abandoned_object, crowd_density,
        disorder, fall, fight, phone, unauthorized_person, vehicle,
        vision, zone_entry, teacher_punctuality) — fire_ai stands in for
        all of them since they share the identical pattern."""
        await _set_module_active(db_session, FIRE_MODULE_CODE, False)

        calls = {"n": 0}

        async def counting_grab_frame_pair(stream_url, gap_seconds=1.0):
            calls["n"] += 1
            return b"frame-a", b"frame-b"

        monkeypatch.setattr(fire_ai, "grab_frame_pair", counting_grab_frame_pair)

        count = await run_fire_ai_sweep_once(session_factory=TestSessionLocal)
        assert count == 0
        assert calls["n"] == 0
