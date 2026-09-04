"""The daily report was wrong in two ways that both read as ordinary
numbers, which is why neither was noticed from the report itself.

Dates were grouped with func.date() on a timestamptz while the container
runs in UTC, so the report answered "which UTC day was it". Measured on
production at 10:57 local it counted 35 events; the local day held 49.

And an attendance figure of 0.0% was printed for a period that had no
attendance records at all — "nobody came" and "nothing recorded yet"
rendered identically.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import AttendanceRecord, Building, Camera, Event, StudentStaff
from app.services.report_generator import generate_rule_based_report

TASHKENT_OFFSET = timedelta(hours=5)


def local_moment(day: date, hour: int, minute: int = 0) -> datetime:
    """A UTC instant that is `hour:minute` on `day` in Tashkent."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc) - TASHKENT_OFFSET


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Hisobot kamerasi", ip="10.9.9.9", building_id=building.id,
        zone="Z", resolution="1080p", status="faol",
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera)
    return camera


async def add_event(db_session, camera, when: datetime, *, module_code: int = 17, status: str = "yangi"):
    db_session.add(
        Event(
            occurred_at=when, camera_id=camera.id, camera_name=camera.name, building="B",
            module_code=module_code, module_name=f"Modul {module_code}", group="D",
            confidence=55, severity="past", status=status,
        )
    )
    await db_session.commit()


@pytest.mark.usefixtures("seeded")
class TestLocalDayBoundaries:
    async def test_an_event_just_after_local_midnight_counts_for_that_day(self, db_session, a_camera):
        """01:00 Tashkent is 20:00 the previous day in UTC. Grouped by UTC
        date it lands in yesterday's report and today's shows one fewer —
        which is how a fifth of every day went missing."""
        today = date(2026, 9, 4)
        await add_event(db_session, a_camera, local_moment(today, 1, 0))

        report = await generate_rule_based_report(db_session, "Kunlik", today=today)
        assert report.stats[1] == {"label": "AI signallar", "value": "1"}

    async def test_an_event_late_the_previous_evening_does_not_leak_in(self, db_session, a_camera):
        today = date(2026, 9, 4)
        await add_event(db_session, a_camera, local_moment(today - timedelta(days=1), 23, 30))

        report = await generate_rule_based_report(db_session, "Kunlik", today=today)
        assert report.stats[1]["value"] == "0"

    async def test_the_last_minute_of_the_local_day_still_counts(self, db_session, a_camera):
        today = date(2026, 9, 4)
        await add_event(db_session, a_camera, local_moment(today, 23, 59))

        report = await generate_rule_based_report(db_session, "Kunlik", today=today)
        assert report.stats[1]["value"] == "1"

    async def test_day_and_night_are_split_on_local_hours(self, db_session, a_camera):
        today = date(2026, 9, 4)
        await add_event(db_session, a_camera, local_moment(today, 10))  # working hours
        await add_event(db_session, a_camera, local_moment(today, 2))   # empty building

        report = await generate_rule_based_report(db_session, "Kunlik", today=today)
        timing = next(s for s in report.sections if "vaqt bo'yicha" in s.title)
        assert {r["label"]: r["value"] for r in timing.rows} == {
            "Ish vaqtida (07:00-21:00)": "1",
            "Ish vaqtidan tashqari": "1",
        }


@pytest.mark.usefixtures("seeded")
class TestMissingDataIsNotZero:
    async def test_no_attendance_records_reads_as_no_data(self, db_session):
        report = await generate_rule_based_report(db_session, "Kunlik", today=date(2026, 9, 4))
        assert report.stats[0] == {"label": "Davomat", "value": "ma'lumot yo'q"}
        assert "yo'q" in report.summary
        assert "0.0%" not in report.summary

    async def test_a_real_zero_is_still_reported_as_zero(self, db_session):
        """Everyone marked absent IS 0%, and must not be softened into
        "no data" — the two have to stay distinguishable in both
        directions."""
        today = date(2026, 9, 4)
        person = StudentStaff(
            full_name="Test Talaba", type="talaba", group_or_position="1",
            biometrics_status="tasdiqlangan",
        )
        db_session.add(person)
        await db_session.commit()
        await db_session.refresh(person)
        db_session.add(AttendanceRecord(student_staff_id=person.id, date=today, status="kelmadi"))
        await db_session.commit()

        report = await generate_rule_based_report(db_session, "Kunlik", today=today)
        assert report.stats[0] == {"label": "Davomat", "value": "0.0%"}


@pytest.mark.usefixtures("seeded")
class TestReportContent:
    async def test_modules_and_cameras_are_broken_out(self, db_session, a_camera):
        today = date(2026, 9, 4)
        await add_event(db_session, a_camera, local_moment(today, 9), module_code=17)
        await add_event(db_session, a_camera, local_moment(today, 10), module_code=17)
        await add_event(db_session, a_camera, local_moment(today, 11), module_code=20)

        report = await generate_rule_based_report(db_session, "Kunlik", today=today)
        titles = [s.title for s in report.sections]
        assert any("Modul" in t for t in titles)
        assert any("kamera" in t for t in titles)

        modules = next(s for s in report.sections if "Modul" in s.title)
        assert modules.rows[0]["value"] == "2"  # busiest module first

    async def test_unreviewed_events_are_counted_separately(self, db_session, a_camera):
        today = date(2026, 9, 4)
        await add_event(db_session, a_camera, local_moment(today, 9), status="yangi")
        await add_event(db_session, a_camera, local_moment(today, 10), status="tasdiqlangan")

        report = await generate_rule_based_report(db_session, "Kunlik", today=today)
        values = {s["label"]: s["value"] for s in report.stats}
        assert values["Ko'rilmagan signallar"] == "1"
        assert values["Tasdiqlangan"] == "1"

    async def test_the_attendance_section_says_how_many_are_enrolled(self, db_session):
        """A percentage over three people is not an institute-wide
        figure, and the report should not let it be read as one."""
        report = await generate_rule_based_report(db_session, "Kunlik", today=date(2026, 9, 4))
        attendance = next(s for s in report.sections if "Davomat" in s.title)
        assert "ro'yxatdan o'tgan" in (attendance.note or "")

    async def test_weekly_covers_seven_local_days(self, db_session, a_camera):
        today = date(2026, 9, 4)
        await add_event(db_session, a_camera, local_moment(today - timedelta(days=6), 12))
        await add_event(db_session, a_camera, local_moment(today - timedelta(days=7), 12))

        report = await generate_rule_based_report(db_session, "Haftalik", today=today)
        assert report.stats[1]["value"] == "1"

    async def test_an_unknown_period_is_rejected(self, db_session):
        with pytest.raises(ValueError):
            await generate_rule_based_report(db_session, "Yillik", today=date(2026, 9, 4))
