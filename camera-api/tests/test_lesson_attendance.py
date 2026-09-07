"""Davomat shu paytgacha faqat kun bo'yicha hisoblanardi.

Kirish eshigidan o'tgan talaba "keldi" bo'lardi va tizim uning darsga
kirgan-kirmaganini printsipial ravishda ko'ra olmasdi — dars jadvali
davomat uchun umuman ishlatilmasdi, u faqat kechikish chegarasini
hisoblashda qatnashardi.

Bu testlar aynan shu farqni himoya qiladi: dars darajasidagi davomat, va
uni yolg'on ayblovga aylanishdan saqlaydigan uchta qoida.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import settings
from app.jobs.lesson_attendance import (
    finalize_lesson,
    record_sightings,
    run_lesson_attendance_finalization_once,
)
from app.models import AttendanceRecord, Building, Camera, LessonAttendance, LessonSession, StudentStaff
from app.timezone import local_now
from tests.conftest import TestSessionLocal


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="205-xona", ip="10.0.7.5", stream_url="rtsp://fake/205", building_id=building.id,
        zone="205-xona", resolution="1080p", status="faol", last_seen_at=local_now(),
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera, attribute_names=["building"])
    return camera


async def _student(db_session, name: str, group: str = "301-guruh", *, confirmed: bool = True) -> StudentStaff:
    person = StudentStaff(
        full_name=name, type="talaba", group_or_position=group,
        biometrics_status="tasdiqlangan" if confirmed else "yoq",
    )
    db_session.add(person)
    await db_session.commit()
    await db_session.refresh(person)
    return person


async def _lesson(db_session, camera, *, started_minutes_ago: int, group: str = "301-guruh") -> LessonSession:
    row = LessonSession(
        date=local_now().date(), group_name=group, faculty="Davolash ishi", teacher="Dilnoza Yusupova",
        subject="Anatomiya", attention_score=50, teacher_activity_score=50, teacher_on_time=True,
        camera_id=camera.id, scheduled_start_time=local_now() - timedelta(minutes=started_minutes_ago),
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row, attribute_names=["camera"])
    return row


async def _see(db_session, lesson, student, times: int, *, seen_at=None) -> None:
    """seen_at berilmasa — dars boshlanish payti, ya'ni "o'z vaqtida".

    local_now() ni standart qilib qo'yish tuzoq bo'lardi: testlar
    tugagan darslar bilan ishlaydi, ya'ni "hozir" har doim kechikish
    oynasidan tashqarida bo'lib, har bir talaba kech_keldi bo'lib
    chiqardi."""
    moment = seen_at or lesson.scheduled_start_time
    for _ in range(times):
        await record_sightings(db_session, lesson, {str(student.id)}, seen_at=moment)


@pytest.mark.usefixtures("seeded")
class TestRecordSightings:
    async def test_repeated_sightings_accumulate_on_one_row(self, db_session, a_camera):
        student = await _student(db_session, "Aziz Karimov")
        lesson = await _lesson(db_session, a_camera, started_minutes_ago=10)

        await _see(db_session, lesson, student, times=3)

        rows = (await db_session.execute(select(LessonAttendance))).scalars().all()
        assert len(rows) == 1
        assert rows[0].sightings == 3
        assert rows[0].status is None  # dars hali tugamagan

    async def test_first_seen_is_kept_while_last_seen_advances(self, db_session, a_camera):
        student = await _student(db_session, "Aziz Karimov")
        lesson = await _lesson(db_session, a_camera, started_minutes_ago=10)
        early = local_now() - timedelta(minutes=8)
        late = local_now()

        await record_sightings(db_session, lesson, {str(student.id)}, seen_at=early)
        await record_sightings(db_session, lesson, {str(student.id)}, seen_at=late)

        row = (await db_session.execute(select(LessonAttendance))).scalar_one()
        assert abs((row.first_seen_at - early).total_seconds()) < 2
        assert abs((row.last_seen_at - late).total_seconds()) < 2


@pytest.mark.usefixtures("seeded")
class TestFinalization:
    async def test_a_student_seen_enough_times_is_present(self, db_session, a_camera):
        student = await _student(db_session, "Aziz Karimov")
        lesson = await _lesson(db_session, a_camera, started_minutes_ago=settings.lesson_duration_minutes + 5)
        await _see(db_session, lesson, student, times=settings.lesson_attendance_min_sightings)

        assert await finalize_lesson(db_session, lesson) == 1
        row = (await db_session.execute(select(LessonAttendance))).scalar_one()
        assert row.status == "keldi"

    async def test_a_student_never_seen_is_marked_absent(self, db_session, a_camera):
        present = await _student(db_session, "Aziz Karimov")
        absent = await _student(db_session, "Nodira Salimova")
        lesson = await _lesson(db_session, a_camera, started_minutes_ago=settings.lesson_duration_minutes + 5)
        await _see(db_session, lesson, present, times=settings.lesson_attendance_min_sightings)

        await finalize_lesson(db_session, lesson)
        rows = {
            str(r.student_staff_id): r
            for r in (await db_session.execute(select(LessonAttendance))).scalars().all()
        }
        assert rows[str(present.id)].status == "keldi"
        assert rows[str(absent.id)].status == "kelmadi"
        assert rows[str(absent.id)].sightings == 0

    async def test_a_single_sighting_is_not_enough_to_count_as_present(self, db_session, a_camera):
        """Yonidan o'tib ketgan odam ham, yuz mosligining xatosi ham bitta
        kadrda ko'rinishi mumkin — bu ishtirok emas."""
        student = await _student(db_session, "Aziz Karimov")
        lesson = await _lesson(db_session, a_camera, started_minutes_ago=settings.lesson_duration_minutes + 5)
        # Yana bitta ishonchli ko'rilgan talaba bo'lishi kerak, aks holda
        # dars umuman yakunlanmaydi (3-qoida) va test noto'g'ri sababdan
        # o'tib ketardi.
        anchor = await _student(db_session, "Anvar Toshev")
        await _see(db_session, lesson, anchor, times=settings.lesson_attendance_min_sightings)
        await _see(db_session, lesson, student, times=1)

        await finalize_lesson(db_session, lesson)
        rows = {
            str(r.student_staff_id): r
            for r in (await db_session.execute(select(LessonAttendance))).scalars().all()
        }
        assert rows[str(student.id)].status == "kelmadi"
        assert rows[str(student.id)].sightings == 1  # ko'rilgani saqlanadi, hisobga olinmaydi

    async def test_arriving_after_the_grace_window_is_late_not_present(self, db_session, a_camera):
        student = await _student(db_session, "Aziz Karimov")
        lesson = await _lesson(db_session, a_camera, started_minutes_ago=settings.lesson_duration_minutes + 5)
        late_moment = lesson.scheduled_start_time + timedelta(
            minutes=settings.attendance_late_to_lesson_grace_minutes + 10
        )
        await _see(db_session, lesson, student, times=settings.lesson_attendance_min_sightings, seen_at=late_moment)

        await finalize_lesson(db_session, lesson)
        row = (await db_session.execute(select(LessonAttendance))).scalar_one()
        assert row.status == "kech_keldi"

    async def test_arriving_inside_the_grace_window_is_present(self, db_session, a_camera):
        student = await _student(db_session, "Aziz Karimov")
        lesson = await _lesson(db_session, a_camera, started_minutes_ago=settings.lesson_duration_minutes + 5)
        just_after_bell = lesson.scheduled_start_time + timedelta(
            minutes=max(settings.attendance_late_to_lesson_grace_minutes - 1, 0)
        )
        await _see(db_session, lesson, student, times=settings.lesson_attendance_min_sightings, seen_at=just_after_bell)

        await finalize_lesson(db_session, lesson)
        row = (await db_session.execute(select(LessonAttendance))).scalar_one()
        assert row.status == "keldi"


@pytest.mark.usefixtures("seeded")
class TestTheThreeHonestyRules:
    async def test_a_student_without_confirmed_biometrics_is_never_marked_absent(self, db_session, a_camera):
        """Yuzi kiritilmagan odamni kamera printsipial ravishda tanimaydi
        — uni "kelmadi" deb yozish bizning ma'lumotimiz haqidagi faktni
        odam haqidagi ayblovga aylantirish bo'lardi."""
        unenrolled = await _student(db_session, "Ro'yxatsiz Talaba", confirmed=False)
        anchor = await _student(db_session, "Anvar Toshev")
        lesson = await _lesson(db_session, a_camera, started_minutes_ago=settings.lesson_duration_minutes + 5)
        await _see(db_session, lesson, anchor, times=settings.lesson_attendance_min_sightings)

        await finalize_lesson(db_session, lesson)
        rows = (await db_session.execute(select(LessonAttendance))).scalars().all()
        assert str(unenrolled.id) not in {str(r.student_staff_id) for r in rows}

    async def test_a_lesson_with_no_confirmed_sightings_is_not_finalized_at_all(self, db_session, a_camera):
        """Kamera hech narsa bermagan dars "hamma kelmadi" degani emas —
        bu tizimning eng yomon xato turi bo'lardi."""
        await _student(db_session, "Aziz Karimov")
        await _student(db_session, "Nodira Salimova")
        lesson = await _lesson(db_session, a_camera, started_minutes_ago=settings.lesson_duration_minutes + 5)

        assert await finalize_lesson(db_session, lesson) == 0
        assert (await db_session.execute(select(LessonAttendance))).scalars().all() == []

    async def test_a_group_with_no_enrolled_students_is_not_finalized(self, db_session, a_camera):
        lesson = await _lesson(db_session, a_camera, started_minutes_ago=settings.lesson_duration_minutes + 5)
        assert await finalize_lesson(db_session, lesson) == 0


@pytest.mark.usefixtures("seeded")
class TestDayLevelAttendanceIsCredited:
    async def test_being_seen_in_class_also_creates_the_day_record(self, db_session, a_camera):
        """Auditoriyada ko'rilgan odam binoda ham bo'lgan — kirish
        kamerasi uni o'tkazib yuborgan bo'lsa ham."""
        student = await _student(db_session, "Aziz Karimov")
        lesson = await _lesson(db_session, a_camera, started_minutes_ago=settings.lesson_duration_minutes + 5)
        await _see(db_session, lesson, student, times=settings.lesson_attendance_min_sightings)

        await finalize_lesson(db_session, lesson)
        record = (await db_session.execute(select(AttendanceRecord))).scalar_one()
        assert record.status == "keldi"
        assert record.check_in is not None

    async def test_an_existing_day_record_is_never_overwritten(self, db_session, a_camera):
        """Kirish kamerasidan kelgan aniqroq vaqt ham, adminning qo'lda
        tuzatgani ham bu yerda buzilmasligi kerak."""
        student = await _student(db_session, "Aziz Karimov")
        db_session.add(
            AttendanceRecord(student_staff_id=student.id, date=local_now().date(), status="kech_keldi")
        )
        await db_session.commit()

        lesson = await _lesson(db_session, a_camera, started_minutes_ago=settings.lesson_duration_minutes + 5)
        await _see(db_session, lesson, student, times=settings.lesson_attendance_min_sightings)
        await finalize_lesson(db_session, lesson)

        record = (await db_session.execute(select(AttendanceRecord))).scalar_one()
        assert record.status == "kech_keldi"


@pytest.mark.usefixtures("seeded")
class TestFinalizationSweep:
    async def test_a_lesson_still_in_progress_is_not_finalized(self, db_session, a_camera):
        student = await _student(db_session, "Aziz Karimov")
        lesson = await _lesson(db_session, a_camera, started_minutes_ago=5)  # hali davom etyapti
        await _see(db_session, lesson, student, times=settings.lesson_attendance_min_sightings)

        assert await run_lesson_attendance_finalization_once(session_factory=TestSessionLocal) == 0
        row = (await db_session.execute(select(LessonAttendance))).scalar_one()
        assert row.status is None

    async def test_finalization_does_not_run_twice_on_the_same_lesson(self, db_session, a_camera):
        student = await _student(db_session, "Aziz Karimov")
        lesson = await _lesson(db_session, a_camera, started_minutes_ago=settings.lesson_duration_minutes + 5)
        await _see(db_session, lesson, student, times=settings.lesson_attendance_min_sightings)

        first = await run_lesson_attendance_finalization_once(session_factory=TestSessionLocal)
        second = await run_lesson_attendance_finalization_once(session_factory=TestSessionLocal)
        assert first == 1
        assert second == 0
