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


async def _person(db, name: str, *, enrolled: bool) -> StudentStaff:
    faculty = (await db.execute(select(Faculty))).scalars().first()
    record = StudentStaff(
        full_name=name,
        type="talaba",
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


class TestWorkingDays:
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
