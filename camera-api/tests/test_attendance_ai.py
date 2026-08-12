import json
from datetime import datetime, timedelta
from pathlib import Path

import insightface
import pytest
from sqlalchemy import select

from app.jobs.attendance_ai import (
    find_best_match,
    process_camera_frame,
    upsert_attendance_from_recognition,
)
from app.models import AttendanceRecord, Building, Camera, Event, Faculty, StudentStaff
from app.services.face_recognition import detect_faces, extract_embedding
from app.timezone import INSTITUTE_TZ

FACE_IMAGE_PATH = Path(insightface.__file__).parent / "data" / "images" / "t1.jpg"


def _local_time(hour: int, minute: int) -> datetime:
    """'Today' at the given hour/minute, explicitly in the institute's
    local timezone (Asia/Tashkent) — not UTC. attendance_ai's cutoffs
    (late arrival, off-hours) are local clock times, so tests need to
    construct moments the same way, or they'd silently be testing the
    wrong boundary (see app/timezone.py's module docstring for the real
    bug this pattern replaced)."""
    return datetime.now(INSTITUTE_TZ).replace(hour=hour, minute=minute, second=0, microsecond=0)


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(name="Kirish kamerasi", ip="10.0.9.1", building_id=building.id, zone="Kirish", resolution="1080p", status="faol")
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera, attribute_names=["building"])
    return camera


class TestFindBestMatch:
    def test_no_candidates_returns_none(self):
        assert find_best_match([1.0, 0.0], []) is None

    def test_identical_vector_matches(self):
        vec = [1.0, 0.0, 0.0]
        result = find_best_match(vec, [("person-a", [1.0, 0.0, 0.0])])
        assert result == ("person-a", pytest.approx(1.0))

    def test_orthogonal_vector_is_below_threshold(self):
        # cosine similarity of orthogonal unit vectors is 0.0, well under
        # settings.attendance_ai_match_threshold (0.55 by default).
        result = find_best_match([1.0, 0.0], [("person-a", [0.0, 1.0])])
        assert result is None

    def test_picks_the_closer_of_two_candidates(self):
        query = [1.0, 0.0]
        result = find_best_match(
            query, [("far", [0.0, 1.0]), ("close", [0.99, 0.14])]
        )
        assert result is not None
        assert result[0] == "close"


@pytest.mark.usefixtures("seeded")
class TestUpsertAttendanceFromRecognition:
    async def test_first_sighting_before_cutoff_is_keldi(self, db_session):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        student = StudentStaff(full_name="Ertalab Kelgan", type="talaba", faculty_id=faculty.id, group_or_position="1")
        db_session.add(student)
        await db_session.commit()

        occurred_at = _local_time(8, 30)
        record = await upsert_attendance_from_recognition(db_session, str(student.id), occurred_at)
        assert record.status == "keldi"
        assert record.check_in.strftime("%H:%M") == "08:30"
        assert record.check_out is None

    async def test_first_sighting_after_cutoff_is_kech_keldi(self, db_session):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        student = StudentStaff(full_name="Kech Kelgan", type="talaba", faculty_id=faculty.id, group_or_position="1")
        db_session.add(student)
        await db_session.commit()

        occurred_at = _local_time(9, 15)
        record = await upsert_attendance_from_recognition(db_session, str(student.id), occurred_at)
        assert record.status == "kech_keldi"

    async def test_second_sighting_same_day_only_advances_check_out(self, db_session):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        student = StudentStaff(full_name="Ikki Marta Ko'ringan", type="talaba", faculty_id=faculty.id, group_or_position="1")
        db_session.add(student)
        await db_session.commit()

        morning = _local_time(8, 0)
        first = await upsert_attendance_from_recognition(db_session, str(student.id), morning)
        assert first.status == "keldi"
        assert first.check_out is None

        afternoon = morning + timedelta(hours=6)
        second = await upsert_attendance_from_recognition(db_session, str(student.id), afternoon)
        assert second.status == "keldi"  # unchanged from first sighting
        assert second.check_in.strftime("%H:%M") == "08:00"  # unchanged
        assert second.check_out.strftime("%H:%M") == "14:00"

        rows = (
            await db_session.execute(
                select(AttendanceRecord).where(AttendanceRecord.student_staff_id == student.id)
            )
        ).scalars().all()
        assert len(rows) == 1  # still one row for the day, not two

    async def test_writes_an_audit_log_entry_attributed_to_the_ai(self, db_session):
        from app.models import AuditLog

        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        student = StudentStaff(full_name="Audit Sinovi", type="talaba", faculty_id=faculty.id, group_or_position="1")
        db_session.add(student)
        await db_session.commit()

        await upsert_attendance_from_recognition(db_session, str(student.id), datetime.now(INSTITUTE_TZ))

        entries = (
            await db_session.execute(select(AuditLog).where(AuditLog.user_name == "AI davomat tizimi"))
        ).scalars().all()
        assert len(entries) == 1
        assert "Audit Sinovi" in entries[0].action
        assert entries[0].user_id is None

    async def test_off_hours_first_sighting_raises_a_security_event(self, db_session, a_camera):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        student = StudentStaff(full_name="Tungi Kirgan", type="talaba", faculty_id=faculty.id, group_or_position="1")
        db_session.add(student)
        await db_session.commit()

        # default off-hours window is [07:00, 20:00) — 22:30 is well outside it
        occurred_at = _local_time(22, 30)
        await upsert_attendance_from_recognition(db_session, str(student.id), occurred_at, a_camera)

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1
        assert events[0].module_code == 3
        assert events[0].module_name == "Notekis/kechki vaqtda kirish"
        assert events[0].person_name == "Tungi Kirgan"
        assert events[0].camera_name == "Kirish kamerasi"
        assert events[0].group == "A"

    async def test_within_hours_sighting_raises_no_event(self, db_session, a_camera):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        student = StudentStaff(full_name="Kunduzi Kirgan", type="talaba", faculty_id=faculty.id, group_or_position="1")
        db_session.add(student)
        await db_session.commit()

        occurred_at = _local_time(10, 0)
        await upsert_attendance_from_recognition(db_session, str(student.id), occurred_at, a_camera)

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 0

    async def test_second_off_hours_sighting_same_day_does_not_duplicate_the_event(self, db_session, a_camera):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        student = StudentStaff(full_name="Ikki Marta Tunda", type="talaba", faculty_id=faculty.id, group_or_position="1")
        db_session.add(student)
        await db_session.commit()

        first = _local_time(21, 0)
        await upsert_attendance_from_recognition(db_session, str(student.id), first, a_camera)
        second = first + timedelta(hours=2)
        await upsert_attendance_from_recognition(db_session, str(student.id), second, a_camera)

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1  # not re-flagged on the later "last seen" update

    async def test_off_hours_sighting_without_a_camera_raises_no_event(self, db_session):
        """camera is optional — callers that don't pass one (e.g. most of
        the tests above) don't get kriteriya 3 behavior, by design."""
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        student = StudentStaff(full_name="Kamerasiz Sinov", type="talaba", faculty_id=faculty.id, group_or_position="1")
        db_session.add(student)
        await db_session.commit()

        occurred_at = _local_time(23, 0)
        await upsert_attendance_from_recognition(db_session, str(student.id), occurred_at)

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 0


@pytest.mark.usefixtures("seeded")
class TestProcessCameraFrame:
    async def test_matches_an_enrolled_person_from_a_real_photo(self, db_session):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        embedding = await extract_embedding(FACE_IMAGE_PATH.read_bytes())
        student = StudentStaff(
            full_name="Yuzi Ro'yxatdan O'tgan", type="talaba", faculty_id=faculty.id, group_or_position="1",
            biometric_embedding=json.dumps(embedding),
        )
        db_session.add(student)
        await db_session.commit()

        records = await process_camera_frame(FACE_IMAGE_PATH.read_bytes(), db_session)
        assert len(records) == 1
        assert str(records[0].student_staff_id) == str(student.id)

    async def test_two_enrolled_people_in_one_frame_both_get_attendance(self, db_session):
        """The actual bug this rewrite fixes: t1.jpg has 6 detectable
        faces (see app/services/face_recognition.py's detect_faces()).
        Enrolling two of them and processing the frame once must credit
        BOTH — the old largest-face-only version would have silently
        given attendance to only one of them, with nothing to explain
        why the other never showed up (found from real classroom
        testing: two enrolled students in frame together, only the
        closer one ever got an attendance record)."""
        faces = await detect_faces(FACE_IMAGE_PATH.read_bytes())
        assert len(faces) >= 2

        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        first = StudentStaff(
            full_name="Birinchi Talaba", type="talaba", faculty_id=faculty.id, group_or_position="1",
            biometric_embedding=json.dumps(faces[0].embedding.tolist()),
        )
        second = StudentStaff(
            full_name="Ikkinchi Talaba", type="talaba", faculty_id=faculty.id, group_or_position="1",
            biometric_embedding=json.dumps(faces[1].embedding.tolist()),
        )
        db_session.add_all([first, second])
        await db_session.commit()

        records = await process_camera_frame(FACE_IMAGE_PATH.read_bytes(), db_session)
        matched_ids = {str(r.student_staff_id) for r in records}
        assert str(first.id) in matched_ids
        assert str(second.id) in matched_ids

    async def test_no_face_in_frame_returns_empty_list_without_raising(self, db_session):
        import io

        from PIL import Image

        blank = Image.frombytes("RGB", (100, 100), bytes([255] * 100 * 100 * 3))
        buf = io.BytesIO()
        blank.save(buf, format="JPEG")

        records = await process_camera_frame(buf.getvalue(), db_session)
        assert records == []

    async def test_no_enrolled_candidates_returns_empty_list(self, db_session):
        """Real faces are detected, but nobody in the database has an
        enrolled embedding yet — must not match anyone."""
        records = await process_camera_frame(FACE_IMAGE_PATH.read_bytes(), db_session)
        assert records == []
