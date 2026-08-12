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
from app.jobs.fire_ai import run_fire_ai_sweep_once
from app.jobs.vision_ai import run_vision_ai_sweep_once
from app.models import Building, Camera, Faculty, StudentStaff
from app.services.face_recognition import extract_embedding
from tests.conftest import TestSessionLocal

FACE_IMAGE_PATH = Path(insightface.__file__).parent / "data" / "images" / "t1.jpg"


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


@pytest.mark.usefixtures("seeded")
class TestVisionSweepConcurrency:
    async def test_sweep_processes_every_camera(self, db_session, two_cameras, monkeypatch):
        async def fake_grab_frame_pair(stream_url, gap_seconds=1.0):
            frame = FACE_IMAGE_PATH.read_bytes()
            return frame, frame

        monkeypatch.setattr(vision_ai, "grab_frame_pair", fake_grab_frame_pair)
        monkeypatch.setattr(vision_ai, "is_asleep", lambda landmarks: False)  # no one is asleep — just prove the sweep runs both cameras without raising

        count = await run_vision_ai_sweep_once(session_factory=TestSessionLocal)
        assert count == 0  # is_asleep forced False — asserting this returns cleanly, not a specific count

    async def test_one_camera_failing_does_not_stop_the_others(self, db_session, two_cameras, monkeypatch):
        calls = {"n": 0}

        async def flaky_grab_frame_pair(stream_url, gap_seconds=1.0):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated grab failure")
            frame = FACE_IMAGE_PATH.read_bytes()
            return frame, frame

        monkeypatch.setattr(vision_ai, "grab_frame_pair", flaky_grab_frame_pair)

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
