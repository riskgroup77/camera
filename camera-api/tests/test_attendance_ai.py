import json
from datetime import datetime, time, timedelta
from pathlib import Path

import insightface
import pytest
from sqlalchemy import select

from app.jobs.attendance_ai import (
    find_best_match,
    process_camera_frame,
    upsert_attendance_from_recognition,
)
from app.models import AttendanceRecord, Building, Camera, Event, Faculty, LessonSession, StudentStaff
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


@pytest.fixture
async def an_entrance_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Asosiy eshik", ip="10.0.9.3", building_id=building.id, zone="Kirish",
        resolution="1080p", status="faol", is_entrance=True,
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera, attribute_names=["building"])
    return camera


@pytest.fixture
async def an_exit_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Chiqish kamerasi", ip="10.0.9.2", building_id=building.id, zone="Chiqish",
        resolution="1080p", status="faol", is_exit=True,
    )
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

    async def test_an_early_lesson_does_not_make_daily_attendance_late(self, db_session):
        """Kunlik davomat dars jadvaliga bog'liq emas: 08:00 dagi darsga 08:10
        da kelgan talaba kunlik davomatda "keldi" (09:00 dan oldin). Darsga
        kechikkani alohida — o'qituvchilar/dars kuzatuvida ko'rinadi."""
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        student = StudentStaff(
            full_name="Jadvaldan Mustaqil", type="talaba", faculty_id=faculty.id, group_or_position="19-IQT"
        )
        db_session.add(student)
        db_session.add(
            LessonSession(
                date=_local_time(8, 0).date(), group_name="19-IQT", faculty="Iqtisodiyot",
                teacher="Test O'qituvchi", subject="Matematika", attention_score=0,
                teacher_activity_score=0, scheduled_start_time=_local_time(8, 0),
            )
        )
        await db_session.commit()

        record = await upsert_attendance_from_recognition(db_session, str(student.id), _local_time(8, 10))
        assert record.status == "keldi"
        assert record.check_out is None

    async def test_a_later_lesson_does_not_excuse_arriving_after_the_cutoff(self, db_session):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        teacher = StudentStaff(
            full_name="Ikkinchi Darsli Domla", type="xodim", faculty_id=faculty.id, group_or_position="O'qituvchi"
        )
        db_session.add(teacher)
        await db_session.flush()
        db_session.add(
            LessonSession(
                date=_local_time(10, 0).date(), group_name="20-IQT", faculty="Iqtisodiyot",
                teacher=teacher.full_name, teacher_id=teacher.id, subject="Fizika", attention_score=0,
                teacher_activity_score=0, scheduled_start_time=_local_time(10, 0),
            )
        )
        await db_session.commit()

        record = await upsert_attendance_from_recognition(db_session, str(teacher.id), _local_time(10, 2))
        assert record.status == "kech_keldi"

    async def test_first_sighting_after_cutoff_is_kech_keldi(self, db_session):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        student = StudentStaff(full_name="Kech Kelgan", type="talaba", faculty_id=faculty.id, group_or_position="1")
        db_session.add(student)
        await db_session.commit()

        occurred_at = _local_time(9, 15)
        record = await upsert_attendance_from_recognition(db_session, str(student.id), occurred_at)
        assert record.status == "kech_keldi"

    async def test_second_sighting_on_a_non_exit_camera_does_not_set_check_out(self, db_session, a_camera):
        """Only a camera flagged is_exit may ever advance check_out — an
        ordinary interior camera (classroom, hallway) confirms someone is
        still on campus, not that they left. See Camera.is_exit's
        docstring for why "last seen anywhere" used to be silently treated
        as "check-out time"."""
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        student = StudentStaff(full_name="Ikki Marta Ko'ringan", type="talaba", faculty_id=faculty.id, group_or_position="1")
        db_session.add(student)
        await db_session.commit()

        morning = _local_time(8, 0)
        first = await upsert_attendance_from_recognition(db_session, str(student.id), morning, a_camera)
        assert first.status == "keldi"
        assert first.check_out is None

        afternoon = morning + timedelta(hours=6)
        second = await upsert_attendance_from_recognition(db_session, str(student.id), afternoon, a_camera)
        assert second.status == "keldi"  # unchanged from first sighting
        assert second.check_in.strftime("%H:%M") == "08:00"  # unchanged
        assert second.check_out is None  # a non-exit camera never sets check_out

        rows = (
            await db_session.execute(
                select(AttendanceRecord).where(AttendanceRecord.student_staff_id == student.id)
            )
        ).scalars().all()
        assert len(rows) == 1  # still one row for the day, not two

    async def test_sighting_on_an_exit_camera_sets_check_out(self, db_session, a_camera, an_exit_camera):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        student = StudentStaff(full_name="Chiqib Ketgan", type="talaba", faculty_id=faculty.id, group_or_position="1")
        db_session.add(student)
        await db_session.commit()

        morning = _local_time(8, 0)
        await upsert_attendance_from_recognition(db_session, str(student.id), morning, a_camera)

        # Seen mid-day by an ordinary camera — must NOT touch check_out.
        midday = morning + timedelta(hours=3)
        mid = await upsert_attendance_from_recognition(db_session, str(student.id), midday, a_camera)
        assert mid.check_out is None

        evening = morning + timedelta(hours=8)
        left = await upsert_attendance_from_recognition(db_session, str(student.id), evening, an_exit_camera)
        assert left.check_in.strftime("%H:%M") == "08:00"  # unchanged
        assert left.check_out.strftime("%H:%M") == "16:00"

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

    async def test_repeated_exit_sightings_do_not_flood_the_audit_log(self, db_session, an_exit_camera):
        """Chiqish vaqti yangilanadi, lekin jurnalda kunning bitta yozuvi qoladi."""
        from app.models import AuditLog

        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        person = StudentStaff(full_name="Kirishda Turgan", type="xodim", faculty_id=faculty.id, group_or_position="1")
        db_session.add(person)
        await db_session.commit()
        first = datetime.now(INSTITUTE_TZ).replace(hour=8, minute=0, second=0, microsecond=0)

        for seconds in (0, 30, 60, 90):
            record = await upsert_attendance_from_recognition(
                db_session, str(person.id), first + timedelta(seconds=seconds), an_exit_camera
            )

        assert record.check_out.strftime("%H:%M:%S") == "08:01:30"
        entries = (
            await db_session.execute(select(AuditLog).where(AuditLog.user_name == "AI davomat tizimi"))
        ).scalars().all()
        assert len(entries) == 1

    async def test_off_hours_first_sighting_raises_a_security_event(self, db_session, an_entrance_camera):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        student = StudentStaff(full_name="Tungi Kirgan", type="talaba", faculty_id=faculty.id, group_or_position="1")
        db_session.add(student)
        await db_session.commit()

        # default off-hours window is [07:00, 20:00) — 22:30 is well outside it
        occurred_at = _local_time(22, 30)
        await upsert_attendance_from_recognition(db_session, str(student.id), occurred_at, an_entrance_camera)

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1
        assert events[0].module_code == 3
        assert events[0].module_name == "Notekis/kechki vaqtda kirish"
        assert events[0].person_name == "Tungi Kirgan"
        assert events[0].camera_name == "Asosiy eshik"
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

    async def test_second_off_hours_sighting_same_day_does_not_duplicate_the_event(self, db_session, an_entrance_camera):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        student = StudentStaff(full_name="Ikki Marta Tunda", type="talaba", faculty_id=faculty.id, group_or_position="1")
        db_session.add(student)
        await db_session.commit()

        first = _local_time(21, 0)
        await upsert_attendance_from_recognition(db_session, str(student.id), first, an_entrance_camera)
        second = first + timedelta(hours=2)
        await upsert_attendance_from_recognition(db_session, str(student.id), second, an_entrance_camera)

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1  # not re-flagged on the later "last seen" update

    async def test_off_hours_sighting_with_module_disabled_raises_no_event(self, db_session, an_entrance_camera):
        """AIModuleConfig code 3 toggled off — same off-hours sighting that
        would normally raise an Event must not, once the caller (the real
        sweep loop) has determined the module is inactive."""
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        student = StudentStaff(full_name="Ochirilgan Modul", type="talaba", faculty_id=faculty.id, group_or_position="1")
        db_session.add(student)
        await db_session.commit()

        occurred_at = _local_time(22, 30)
        await upsert_attendance_from_recognition(
            db_session, str(student.id), occurred_at, an_entrance_camera, off_hours_module_active=False
        )

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 0

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


@pytest.mark.usefixtures("seeded")
class TestArrivalIsOnlyKnownAtTheDoor:
    """2026-09-17: bir kunda tanilgan 22 kishidan 20 tasi "kech keldi" deb
    yozilgan edi — kamera ularni birinchi marta 14:00-15:40 da xonada
    ko'rgan, ular esa ertalab ishlamayotgan eshikdan kirgan bo'lishi mumkin."""

    async def _person(self, db_session, name: str) -> StudentStaff:
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        person = StudentStaff(full_name=name, type="xodim", faculty_id=faculty.id, group_or_position="Laborant")
        db_session.add(person)
        await db_session.commit()
        return person

    async def test_late_first_sighting_inside_is_present_with_unknown_arrival(self, db_session, a_camera):
        person = await self._person(db_session, "Xonada Ko'ringan")
        record = await upsert_attendance_from_recognition(db_session, str(person.id), _local_time(15, 40), a_camera)
        assert record.status == "keldi"
        assert record.check_in is None

    async def test_late_first_sighting_at_the_door_is_late(self, db_session, an_entrance_camera):
        person = await self._person(db_session, "Eshikda Kech")
        record = await upsert_attendance_from_recognition(
            db_session, str(person.id), _local_time(9, 40), an_entrance_camera
        )
        assert record.status == "kech_keldi"
        assert record.check_in == time(9, 40)

    async def test_a_camera_facing_arrivals_keeps_late_arrivals_late(self, db_session, an_entrance_camera):
        """Kamera kirayotganlarning yuzini ko'radi (face_direction="kirish") —
        14:30 dagi birinchi ko'rinish haqiqatan kech kelish."""
        an_entrance_camera.face_direction = "kirish"
        await db_session.commit()
        person = await self._person(db_session, "Tushdan Keyin Kelgan")
        record = await upsert_attendance_from_recognition(
            db_session, str(person.id), _local_time(14, 30), an_entrance_camera
        )
        assert (record.status, record.check_in) == ("kech_keldi", time(14, 30))

    async def test_a_camera_facing_departures_never_marks_late(self, db_session, an_entrance_camera):
        an_entrance_camera.face_direction = "chiqish"
        await db_session.commit()
        person = await self._person(db_session, "Ketayotgan Odam")
        record = await upsert_attendance_from_recognition(
            db_session, str(person.id), _local_time(9, 40), an_entrance_camera
        )
        assert (record.status, record.check_in) == ("keldi", None)

    async def test_first_door_sighting_in_the_afternoon_is_not_late(self, db_session, an_entrance_camera):
        """Kirish kamerasi chiqishni ham ko'radi: kunning birinchi ko'rinishi
        16:30 da bo'lsa, bu odatda ketayotgan odam (2026-09-18 da tuzatishdan
        keyin yana 5 ta shunday "kech keldi" yozilgan edi)."""
        person = await self._person(db_session, "Ketayotgan Xodim")
        record = await upsert_attendance_from_recognition(
            db_session, str(person.id), _local_time(16, 30), an_entrance_camera
        )
        assert (record.status, record.check_in) == ("keldi", None)

    async def test_early_first_sighting_anywhere_is_on_time(self, db_session, a_camera):
        person = await self._person(db_session, "Erta Xonada")
        record = await upsert_attendance_from_recognition(db_session, str(person.id), _local_time(8, 20), a_camera)
        assert record.status == "keldi"
        assert record.check_in == time(8, 20)

    async def test_evening_first_sighting_inside_is_not_an_off_hours_entry(self, db_session, a_camera):
        """Kun bo'yi kameraga tushmagan xodimni kechqurun xonada ko'rish
        uning shu paytda binoga kirganini bildirmaydi."""
        person = await self._person(db_session, "Kechqurun Xonada")
        await upsert_attendance_from_recognition(db_session, str(person.id), _local_time(20, 57), a_camera)
        assert (await db_session.execute(select(Event))).scalars().all() == []

    async def test_early_morning_presence_anywhere_is_off_hours(self, db_session, a_camera):
        person = await self._person(db_session, "Tongda Xonada")
        await upsert_attendance_from_recognition(db_session, str(person.id), _local_time(6, 10), a_camera)
        events = (await db_session.execute(select(Event))).scalars().all()
        assert [e.module_code for e in events] == [3]
