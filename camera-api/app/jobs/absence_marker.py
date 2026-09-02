"""Marks people who were never seen today as 'kelmadi' (absent).

The gap this closes: nothing in the system ever wrote the 'kelmadi'
status. app/jobs/attendance_ai.py only ever files a row for someone a
camera actually RECOGNISED — so a person who never showed up simply had
no row at all, and "Kelmaydiganlar" on every dashboard and report read 0
forever. An attendance system that can say who came but not who didn't
is only answering half the question it exists to answer.

Two rules keep this honest rather than accusatory:

1. Only people with CONFIRMED biometrics are marked. Someone whose face
   was never enrolled cannot be recognised by any camera, so their
   absence is a property of OUR data, not of their attendance — marking
   them absent would be a fabricated accusation against a real person.

2. Only on configured working days, and only after the working day is
   actually over (attendance_absence_mark_after). Marking at 09:00 that
   someone "did not come" today is simply false; they may be on their way.

The sweep is idempotent: it inserts with ON CONFLICT DO NOTHING against
the (student_staff_id, date) unique key, so it never overwrites a
recognition-produced 'keldi'/'kech_keldi', never overwrites an admin's
manual correction, and can safely run every tick after the cutoff.
"""

import asyncio
import logging
from datetime import date as date_type, time as time_type

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.models import AttendanceRecord, StudentStaff
from app.timezone import local_now

logger = logging.getLogger("app.absence_marker")


def _working_weekdays() -> set[int]:
    """ISO weekdays (Mon=1 .. Sun=7) the institute expects attendance on."""
    days: set[int] = set()
    for part in settings.attendance_working_weekdays.split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= 7:
            days.add(int(part))
    return days


def is_working_day(day: date_type) -> bool:
    return day.isoweekday() in _working_weekdays()


def _cutoff_time() -> time_type:
    return time_type.fromisoformat(settings.attendance_absence_mark_after)


async def mark_absences_for_day(db: AsyncSession, day: date_type) -> int:
    """Files 'kelmadi' for every enrolled person with no row for `day`.
    Returns how many rows were actually inserted."""
    enrolled = (
        await db.execute(
            select(StudentStaff.id).where(StudentStaff.biometrics_status == "tasdiqlangan")
        )
    ).scalars().all()
    if not enrolled:
        return 0

    already_recorded = set(
        (
            await db.execute(
                select(AttendanceRecord.student_staff_id).where(AttendanceRecord.date == day)
            )
        ).scalars().all()
    )
    missing = [person_id for person_id in enrolled if person_id not in already_recorded]
    if not missing:
        return 0

    stmt = (
        insert(AttendanceRecord)
        .values([{"student_staff_id": person_id, "date": day, "status": "kelmadi"} for person_id in missing])
        .on_conflict_do_nothing(index_elements=["student_staff_id", "date"])
    )
    result = await db.execute(stmt)
    await db.commit()
    inserted = result.rowcount or 0
    if inserted:
        logger.info("marked absences", extra={"date": day.isoformat(), "count": inserted})
    return inserted


async def run_absence_marking_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """One tick: does nothing unless today is a working day AND the
    working day is already over. Safe to call as often as the scheduler
    likes — see the module docstring on idempotency."""
    if not settings.attendance_absence_marking_enabled:
        return 0

    now = local_now()  # institute-local clock, not UTC — see app/timezone.py
    today = now.date()
    if not is_working_day(today):
        return 0
    if now.time() < _cutoff_time():
        return 0

    async with session_factory() as db:
        return await mark_absences_for_day(db, today)


async def absence_marking_loop() -> None:
    while True:
        try:
            await run_absence_marking_once()
        except Exception:
            logger.exception("absence marking sweep failed")
        await asyncio.sleep(settings.attendance_absence_marking_interval_seconds)
