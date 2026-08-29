import json
from datetime import timedelta
from pathlib import Path

import insightface
import pytest
from sqlalchemy import select

from app.jobs import teacher_punctuality_ai
from app.jobs.teacher_punctuality_ai import (
    PUNCTUALITY_MODULE_CODE,
    _due_sessions,
    check_lesson_session,
    run_teacher_punctuality_sweep_once,
)
from app.models import Building, Camera, Event, Faculty, LessonSession, StudentStaff
from app.services.face_recognition import extract_embedding
from app.timezone import local_now
from tests.conftest import TestSessionLocal

FACE_IMAGE_PATH = Path(insightface.__file__).parent / "data" / "images" / "t1.jpg"


@pytest.fixture
async def a_teacher(db_session, seeded):
    faculty = (await db_session.execute(select(Faculty))).scalars().first()
    embedding = await extract_embedding(FACE_IMAGE_PATH.read_bytes())
    teacher = StudentStaff(
        full_name="Dilnoza Yusupova", type="xodim", faculty_id=faculty.id, group_or_position="O'qituvchi",
        biometric_embedding=json.dumps(embedding),
    )
    db_session.add(teacher)
    await db_session.commit()
    return teacher


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="101-xona kamerasi", ip="10.0.9.5", stream_url="rtsp://fake/101",
        building_id=building.id, zone="101-xona", resolution="1080p", status="faol",
        last_seen_at=local_now(),
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera, attribute_names=["building"])
    return camera


async def _make_session(db_session, teacher, camera, minutes_ago_start: int, checked: bool = False) -> LessonSession:
    row = LessonSession(
        date=local_now().date(), group_name="1-guruh", faculty="Davolash ishi", teacher=teacher.full_name,
        subject="Anatomiya", attention_score=80, teacher_activity_score=80, teacher_on_time=True,
        teacher_id=teacher.id, camera_id=camera.id,
        scheduled_start_time=local_now() - timedelta(minutes=minutes_ago_start),
        punctuality_checked_at=local_now() if checked else None,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row, attribute_names=["teacher_ref", "camera"])
    return row


@pytest.mark.usefixtures("seeded")
class TestDueSessions:
    async def test_session_without_camera_is_not_due(self, db_session, a_teacher):
        row = LessonSession(
            date=local_now().date(), group_name="1-guruh", faculty="F", teacher=a_teacher.full_name,
            subject="S", attention_score=1, teacher_activity_score=1, teacher_on_time=True,
            teacher_id=a_teacher.id, scheduled_start_time=local_now() - timedelta(minutes=30),
        )
        db_session.add(row)
        await db_session.commit()
        assert await _due_sessions(db_session) == []

    async def test_not_yet_past_grace_deadline_is_not_due(self, db_session, a_teacher, a_camera):
        await _make_session(db_session, a_teacher, a_camera, minutes_ago_start=1)  # grace default is 10 min
        assert await _due_sessions(db_session) == []

    async def test_past_grace_deadline_is_due(self, db_session, a_teacher, a_camera):
        row = await _make_session(db_session, a_teacher, a_camera, minutes_ago_start=15)
        due = await _due_sessions(db_session)
        assert [r.id for r in due] == [row.id]

    async def test_already_checked_is_not_due_again(self, db_session, a_teacher, a_camera):
        await _make_session(db_session, a_teacher, a_camera, minutes_ago_start=15, checked=True)
        assert await _due_sessions(db_session) == []

    async def test_camera_excluding_module_22_is_not_due(self, db_session, a_teacher, a_camera):
        a_camera.excluded_module_codes = [22]
        await db_session.commit()
        await _make_session(db_session, a_teacher, a_camera, minutes_ago_start=15)
        assert await _due_sessions(db_session) == []

    async def test_camera_excluding_a_different_module_is_still_due(self, db_session, a_teacher, a_camera):
        a_camera.excluded_module_codes = [25]  # vehicle detection, unrelated
        await db_session.commit()
        row = await _make_session(db_session, a_teacher, a_camera, minutes_ago_start=15)
        due = await _due_sessions(db_session)
        assert [r.id for r in due] == [row.id]


@pytest.mark.usefixtures("seeded")
class TestCheckLessonSession:
    async def test_unreachable_camera_does_not_mark_absent(self, db_session, a_teacher, monkeypatch):
        camera = Camera(
            name="Offline kamera", ip="10.0.9.6", stream_url="rtsp://fake/offline",
            zone="Z", resolution="1080p", status="faol", last_seen_at=None,  # never seen -> unreachable
        )
        db_session.add(camera)
        await db_session.commit()
        await db_session.refresh(camera, attribute_names=["building"])
        row = await _make_session(db_session, a_teacher, camera, minutes_ago_start=15)

        raised = await check_lesson_session(row, db_session)
        assert raised is False
        assert row.teacher_on_time is True  # left at its default, not accused
        assert row.punctuality_checked_at is not None

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 0

    async def test_teacher_seen_marks_on_time_no_event(self, db_session, a_teacher, a_camera, monkeypatch):
        async def fake_grab_frame(stream_url):
            return FACE_IMAGE_PATH.read_bytes()

        monkeypatch.setattr(teacher_punctuality_ai, "grab_frame_for_camera", fake_grab_frame)
        row = await _make_session(db_session, a_teacher, a_camera, minutes_ago_start=15)

        raised = await check_lesson_session(row, db_session)
        assert raised is False
        assert row.teacher_on_time is True

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 0

    async def test_teacher_not_seen_raises_event(self, db_session, a_teacher, a_camera, monkeypatch):
        import io

        from PIL import Image

        async def fake_grab_frame(stream_url):
            # A real detectable face that is NOT the enrolled teacher (t1.jpg
            # has 6 faces; the teacher's embedding came from the largest one
            # via extract_embedding — a blank frame guarantees zero match
            # instead, simplest way to be certain no face matches at all).
            blank = Image.frombytes("RGB", (200, 200), bytes([200] * 200 * 200 * 3))
            buf = io.BytesIO()
            blank.save(buf, format="JPEG")
            return buf.getvalue()

        monkeypatch.setattr(teacher_punctuality_ai, "grab_frame_for_camera", fake_grab_frame)
        row = await _make_session(db_session, a_teacher, a_camera, minutes_ago_start=15)

        raised = await check_lesson_session(row, db_session)
        assert raised is True
        assert row.teacher_on_time is False

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1
        assert events[0].module_code == PUNCTUALITY_MODULE_CODE
        assert events[0].person_name == "Dilnoza Yusupova"
        assert events[0].camera_name == a_camera.name


@pytest.mark.usefixtures("seeded")
class TestSweepConcurrency:
    async def test_one_session_failing_does_not_stop_the_others(self, db_session, a_teacher, a_camera, monkeypatch):
        second_teacher_embedding = await extract_embedding(FACE_IMAGE_PATH.read_bytes())
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        second_teacher = StudentStaff(
            full_name="Ikkinchi O'qituvchi", type="xodim", faculty_id=faculty.id, group_or_position="O'qituvchi",
            biometric_embedding=json.dumps(second_teacher_embedding),
        )
        db_session.add(second_teacher)
        await db_session.commit()

        await _make_session(db_session, a_teacher, a_camera, minutes_ago_start=15)
        await _make_session(db_session, second_teacher, a_camera, minutes_ago_start=15)

        calls = {"n": 0}

        async def flaky_grab_frame(stream_url):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated grab failure")
            return FACE_IMAGE_PATH.read_bytes()

        monkeypatch.setattr(teacher_punctuality_ai, "grab_frame_for_camera", flaky_grab_frame)

        await run_teacher_punctuality_sweep_once(session_factory=TestSessionLocal)
        assert calls["n"] == 2  # both sessions were attempted despite the first one failing
