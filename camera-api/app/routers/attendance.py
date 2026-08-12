"""Attendance calendar endpoints.

Rows here are written two ways: manually via POST /api/attendance below
(an admin correcting or backfilling a record), and automatically by
app/jobs/attendance_ai.py (TT kriteriya 6 "Xodim/o'qituvchi davomati", 7
"Talaba davomati", 8 "Darsga kechikish") firing a check-in/check-out on
each face match against a live camera. Both paths write the same table
through the same upsert-by-(person,date) shape, so a day's row never cares
which one produced it.
"""

from datetime import date as date_type
from datetime import time as time_type
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import extract, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.config import settings
from app.database import get_db
from app.dependencies import CurrentUser, get_current_user
from app.models import AttendanceRecord, StudentStaff
from app.schemas.attendance import AttendanceDayOut, AttendanceRecordIn

router = APIRouter(prefix="/api/attendance", tags=["attendance"])


def _parse_time(value: str | None) -> time_type | None:
    if value is None:
        return None
    try:
        return time_type.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"'{value}' — vaqt 'HH:MM' formatida bo'lishi kerak") from exc


def _is_early_leave(record: AttendanceRecord) -> bool:
    """TT kriteriya 9 — pure rule-based, no extra model: present (keldi/
    kech_keldi) with a recorded check_out earlier than the configured
    end-of-day cutoff. A day with no check_out at all (still "present",
    just never re-sighted after check-in) is deliberately NOT flagged —
    that's an absence-of-data case, not evidence of leaving early."""
    if record.status not in ("keldi", "kech_keldi") or record.check_out is None:
        return False
    cutoff = time_type.fromisoformat(settings.attendance_early_leave_cutoff)
    return record.check_out < cutoff


def _to_out(record: AttendanceRecord) -> AttendanceDayOut:
    return AttendanceDayOut(
        date=record.date.isoformat(),
        status=record.status,
        check_in=record.check_in.strftime("%H:%M") if record.check_in else None,
        check_out=record.check_out.strftime("%H:%M") if record.check_out else None,
        early_leave=_is_early_leave(record),
    )


@router.get("/{student_staff_id}", response_model=list[AttendanceDayOut])
async def get_attendance_calendar(
    student_staff_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(get_current_user)],
    month: Annotated[str, Query(description="YYYY-MM")],
) -> list[AttendanceDayOut]:
    try:
        year_i, month_i = (int(p) for p in month.split("-"))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "month 'YYYY-MM' formatida bo'lishi kerak") from exc

    stmt = (
        select(AttendanceRecord)
        .where(AttendanceRecord.student_staff_id == student_staff_id)
        .where(extract("year", AttendanceRecord.date) == year_i)
        .where(extract("month", AttendanceRecord.date) == month_i)
        .order_by(AttendanceRecord.date)
    )
    result = await db.execute(stmt)
    return [_to_out(r) for r in result.scalars().all()]


@router.post("", response_model=AttendanceDayOut, status_code=status.HTTP_201_CREATED)
async def record_attendance(
    body: AttendanceRecordIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> AttendanceDayOut:
    person = await db.get(StudentStaff, body.student_staff_id)
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Talaba/xodim topilmadi")

    try:
        record_date = date_type.fromisoformat(body.date)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "date 'YYYY-MM-DD' formatida bo'lishi kerak") from exc

    check_in = _parse_time(body.check_in)
    check_out = _parse_time(body.check_out)

    # Upsert: one row per (person, date) — re-recording the same day (e.g. a
    # corrected check-out time) updates in place instead of erroring.
    stmt = (
        insert(AttendanceRecord)
        .values(
            student_staff_id=person.id,
            date=record_date,
            status=body.status,
            check_in=check_in,
            check_out=check_out,
        )
        .on_conflict_do_update(
            index_elements=[AttendanceRecord.student_staff_id, AttendanceRecord.date],
            set_={"status": body.status, "check_in": check_in, "check_out": check_out},
        )
        .returning(AttendanceRecord)
    )
    result = await db.execute(stmt)
    record = result.scalar_one()

    await log_action(
        db, request, current_user.id, f"Davomat qayd etdi: {person.full_name} ({body.date})", "Talabalar"
    )
    await db.commit()
    return _to_out(record)


@router.delete("/{student_staff_id}/{date}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attendance_record(
    student_staff_id: str,
    date: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    try:
        date_value = date_type.fromisoformat(date)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "date 'YYYY-MM-DD' formatida bo'lishi kerak") from exc

    result = await db.execute(
        select(AttendanceRecord)
        .where(AttendanceRecord.student_staff_id == student_staff_id)
        .where(AttendanceRecord.date == date_value)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Davomat yozuvi topilmadi")

    person = await db.get(StudentStaff, student_staff_id)
    await log_action(
        db, request, current_user.id,
        f"Davomat yozuvini o'chirdi: {person.full_name if person else student_staff_id} ({date})", "Talabalar"
    )
    await db.delete(record)
    await db.commit()
