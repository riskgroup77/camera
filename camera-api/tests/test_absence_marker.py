"""app/jobs/absence_marker.py writes 'kelmadi' — a record that says a
real person did not show up. Getting it wrong accuses someone, so the
guard rails (enrolled-only, working-day-only, after-hours-only, never
overwrite) matter more than the happy path.

Before this job existed nothing ever wrote 'kelmadi' at all: attendance
only recorded people a camera recognised, so absentees had no row and
every "Kelmaydiganlar" figure read 0."""

from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app.config import settings
from app.jobs import absence_marker
from app.jobs.absence_marker import is_working_day, mark_absences_for_day, run_absence_marking_once
from app.models import AttendanceRecord, Faculty, StudentStaff
from tests.conftest import TestSessionLocal


@pytest.fixture(autouse=True)
def _no_coverage_guard(monkeypatch):
    """Bu fayldagi ko'p test bitta-ikkita odam bilan ishlaydi — qamrov
    chegarasi (attendance_absence_min_coverage) ularni har doim to'xtatardi.
    Chegaraning o'zi TestCoverageGuard da alohida tekshiriladi."""
    monkeypatch.setattr(settings, "attendance_absence_min_coverage", 0.0)


async def _person(db, name: str, *, enrolled: bool, person_type: str = "xodim") -> StudentStaff:
    """Standart tur — xodim: talabalar davomati (#7) 2026-09-16 dan beri
    to'xtatilgan, shuning uchun bu yerdagi qoidalar xodimda tekshiriladi."""
    faculty = (await db.execute(select(Faculty))).scalars().first()
    record = StudentStaff(
        full_name=name,
        type=person_type,
        faculty_id=faculty.id,
        group_or_position="101-guruh",
        biometrics_status="tasdiqlangan" if enrolled else "yoq",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


@pytest.mark.usefixtures("seeded")
class TestMarkAbsencesForDay:
    async def test_enrolled_person_with_no_record_is_marked_absent(self, db_session):
        person = await _person(db_session, "Kelmagan Talaba", enrolled=True)
        day = date(2026, 9, 2)

        inserted = await mark_absences_for_day(db_session, day)

        assert inserted >= 1
        row = (
            await db_session.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.student_staff_id == person.id, AttendanceRecord.date == day
                )
            )
        ).scalar_one()
        assert row.status == "kelmadi"
        assert row.check_in is None

    async def test_population_with_attendance_turned_off_is_never_marked(self, db_session):
        """Talabalar davomati moduli o'chirilgan: kamera ularni
        tekshirmayapti, demak "kelmadi" deb yozish yolg'on ayblov."""
        from app.models import AIModuleConfig

        student = await _person(db_session, "Kuzatilmaydigan Talaba", enrolled=True, person_type="talaba")
        staff = await _person(db_session, "Kuzatiladigan Xodim", enrolled=True)
        day = date(2026, 9, 2)
        # Talabalar davomati moduli o'chiriladi (standart bo'yicha endi yoqiq).
        seven = (await db_session.execute(select(AIModuleConfig).where(AIModuleConfig.code == 7))).scalar_one()
        seven.active = False
        await db_session.commit()

        await mark_absences_for_day(db_session, day)

        marked = set(
            (
                await db_session.execute(
                    select(AttendanceRecord.student_staff_id).where(AttendanceRecord.date == day)
                )
            ).scalars().all()
        )
        assert staff.id in marked
        assert student.id not in marked

        # Modul qayta yoqilsa — talaba ham belgilanadi.
        module = (
            await db_session.execute(select(AIModuleConfig).where(AIModuleConfig.code == 7))
        ).scalar_one()
        module.active = True
        await db_session.commit()
        await mark_absences_for_day(db_session, day)
        marked_after = set(
            (
                await db_session.execute(
                    select(AttendanceRecord.student_staff_id).where(AttendanceRecord.date == day)
                )
            ).scalars().all()
        )
        assert student.id in marked_after

    async def test_person_without_enrolled_biometrics_is_never_marked(self, db_session):
        """The system physically cannot recognise them — their missing row
        reflects OUR data, not their attendance. Marking them absent would
        be a fabricated accusation."""
        person = await _person(db_session, "Ro'yxatdan O'tmagan", enrolled=False)
        day = date(2026, 9, 2)

        await mark_absences_for_day(db_session, day)

        rows = (
            await db_session.execute(
                select(AttendanceRecord).where(AttendanceRecord.student_staff_id == person.id)
            )
        ).scalars().all()
        assert rows == []

    async def test_does_not_overwrite_a_recognised_arrival(self, db_session):
        person = await _person(db_session, "Kelgan Talaba", enrolled=True)
        day = date(2026, 9, 2)
        db_session.add(
            AttendanceRecord(
                student_staff_id=person.id, date=day, status="keldi", check_in=time(8, 55)
            )
        )
        await db_session.commit()

        await mark_absences_for_day(db_session, day)

        row = (
            await db_session.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.student_staff_id == person.id, AttendanceRecord.date == day
                )
            )
        ).scalar_one()
        assert row.status == "keldi"
        assert row.check_in == time(8, 55)

    async def test_running_twice_inserts_nothing_the_second_time(self, db_session):
        await _person(db_session, "Ikki Marta", enrolled=True)
        day = date(2026, 9, 2)

        first = await mark_absences_for_day(db_session, day)
        second = await mark_absences_for_day(db_session, day)

        assert first >= 1
        assert second == 0


@pytest.mark.usefixtures("seeded")
class TestInactiveAndPolicy:
    async def test_inactive_person_is_never_marked_absent(self, db_session):
        person = await _person(db_session, "Chetlatilgan", enrolled=True)
        person.active = False
        await db_session.commit()
        await mark_absences_for_day(db_session, date(2026, 9, 2))
        rows = (
            await db_session.execute(select(AttendanceRecord).where(AttendanceRecord.student_staff_id == person.id))
        ).scalars().all()
        assert rows == []

    def test_working_days_follow_attendance_policy(self, monkeypatch):
        from app.services import attendance_policy

        monkeypatch.setattr(attendance_policy, "_cached", attendance_policy.Policy(work_days=(1, 2, 3, 4, 5)))
        assert is_working_day(date(2026, 9, 5)) is False  # shanba — qoidada dam olish


class TestWorkingDays:
    @pytest.mark.default_policy
    def test_sunday_is_not_a_working_day_by_default(self):
        assert settings.attendance_working_weekdays == "1,2,3,4,5,6"
        assert is_working_day(date(2026, 9, 6)) is False  # Sunday
        assert is_working_day(date(2026, 9, 5)) is True  # Saturday
        assert is_working_day(date(2026, 9, 2)) is True  # Wednesday


@pytest.mark.usefixtures("seeded")
class TestRunAbsenceMarkingOnce:
    async def test_does_nothing_before_the_working_day_is_over(self, db_session, monkeypatch):
        """At 09:00 "did not come today" is simply false — they may still
        be on their way."""
        await _person(db_session, "Erta Tekshiruv", enrolled=True)
        morning = datetime.combine(date(2026, 9, 2), time(9, 0), tzinfo=absence_marker.local_now().tzinfo)
        monkeypatch.setattr(absence_marker, "local_now", lambda: morning)

        assert await run_absence_marking_once(session_factory=TestSessionLocal) == 0

    @pytest.mark.default_policy
    async def test_does_nothing_on_a_non_working_day(self, db_session, monkeypatch):
        await _person(db_session, "Yakshanba Tekshiruvi", enrolled=True)
        sunday_evening = datetime.combine(
            date(2026, 9, 6), time(21, 0), tzinfo=absence_marker.local_now().tzinfo
        )
        monkeypatch.setattr(absence_marker, "local_now", lambda: sunday_evening)

        assert await run_absence_marking_once(session_factory=TestSessionLocal) == 0

    async def test_disabled_setting_short_circuits(self, db_session, monkeypatch):
        await _person(db_session, "O'chirilgan", enrolled=True)
        monkeypatch.setattr(settings, "attendance_absence_marking_enabled", False)

        assert await run_absence_marking_once(session_factory=TestSessionLocal) == 0

    async def test_marks_after_cutoff_on_a_working_day(self, db_session, monkeypatch):
        person = await _person(db_session, "Kechqurun Belgilanadi", enrolled=True)
        evening = datetime.combine(
            date(2026, 9, 2), time(21, 0), tzinfo=absence_marker.local_now().tzinfo
        )
        monkeypatch.setattr(absence_marker, "local_now", lambda: evening)

        marked = await run_absence_marking_once(session_factory=TestSessionLocal)

        assert marked >= 1
        row = (
            await db_session.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.student_staff_id == person.id,
                    AttendanceRecord.date == date(2026, 9, 2),
                )
            )
        ).scalar_one()
        assert row.status == "kelmadi"

    async def test_yesterdays_absences_are_not_backfilled(self, db_session, monkeypatch):
        """Only today is marked — silently inventing history for days the
        job wasn't running would be worse than a gap."""
        person = await _person(db_session, "Kechagi Kun", enrolled=True)
        evening = datetime.combine(
            date(2026, 9, 2), time(21, 0), tzinfo=absence_marker.local_now().tzinfo
        )
        monkeypatch.setattr(absence_marker, "local_now", lambda: evening)

        await run_absence_marking_once(session_factory=TestSessionLocal)

        yesterday = date(2026, 9, 2) - timedelta(days=1)
        rows = (
            await db_session.execute(
                select(AttendanceRecord).where(
                    AttendanceRecord.student_staff_id == person.id, AttendanceRecord.date == yesterday
                )
            )
        ).scalars().all()
        assert rows == []


@pytest.mark.usefixtures("seeded")
class TestCoverageGuard:
    """Kameralar shu kuni ozgina odamni tanigan bo'lsa, qolganlar "kelmadi"
    bo'lmaydi — productionda bir kunda 687 xodimdan 22 tasi tanilgan edi."""

    async def test_low_coverage_day_marks_nobody(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "attendance_absence_min_coverage", 0.3)
        day = date(2026, 8, 3)
        seen = await _person(db_session, "Tanilgan Bitta", enrolled=True)
        for i in range(4):
            await _person(db_session, f"Tanilmagan {i}", enrolled=True)
        db_session.add(AttendanceRecord(student_staff_id=seen.id, date=day, status="keldi", check_in=time(8, 0)))
        await db_session.commit()

        assert await mark_absences_for_day(db_session, day) == 0  # 1/5 = 20% < 30%

    async def test_enough_coverage_marks_the_rest(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "attendance_absence_min_coverage", 0.3)
        day = date(2026, 8, 3)
        for i in range(2):
            person = await _person(db_session, f"Kelgan {i}", enrolled=True)
            db_session.add(AttendanceRecord(student_staff_id=person.id, date=day, status="kech_keldi"))
        absent = await _person(db_session, "Kelmagan", enrolled=True)
        await db_session.commit()

        assert await mark_absences_for_day(db_session, day) == 1  # 2/3 tanilgan
        row = (
            await db_session.execute(select(AttendanceRecord).where(AttendanceRecord.student_staff_id == absent.id))
        ).scalar_one()
        assert row.status == "kelmadi"

    async def test_coverage_is_judged_per_population(self, db_session, monkeypatch):
        """Xodimlar yaxshi tanilgan kun talabalarning past qamrovini
        "oqlamaydi" — har tur o'z qamrovi bilan."""
        monkeypatch.setattr(settings, "attendance_absence_min_coverage", 0.5)
        day = date(2026, 8, 3)
        staff = await _person(db_session, "Xodim Kelgan", enrolled=True)
        db_session.add(AttendanceRecord(student_staff_id=staff.id, date=day, status="keldi"))
        await _person(db_session, "Xodim Kelmagan", enrolled=True)
        for i in range(3):
            await _person(db_session, f"Talaba {i}", enrolled=True, person_type="talaba")
        await db_session.commit()
        monkeypatch.setattr(absence_marker, "tracked_types", _both_types)

        assert await mark_absences_for_day(db_session, day) == 1  # faqat xodim


async def _both_types(db):
    return ["xodim", "talaba"]


@pytest.mark.usefixtures("seeded")
class TestLargeRoster:
    async def test_more_people_than_one_insert_allows(self, db_session, monkeypatch):
        """Postgres bitta so'rovda 32767 dan ortiq parametr olmaydi — katta
        ro'yxat bo'laklab yoziladi."""
        monkeypatch.setattr(absence_marker, "INSERT_CHUNK_SIZE", 2)
        day = date(2026, 8, 3)
        for i in range(5):
            await _person(db_session, f"Katta Ro'yxat {i}", enrolled=True)

        assert await mark_absences_for_day(db_session, day) == 5
