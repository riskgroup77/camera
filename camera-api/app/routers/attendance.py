"""Attendance calendar endpoints.

Rows here are written two ways: manually via POST /api/attendance below
(an admin correcting or backfilling a record), and automatically by
app/jobs/attendance_ai.py (TT kriteriya 6 "Xodim/o'qituvchi davomati", 7
"Talaba davomati", 8 "Darsga kechikish") firing a check-in/check-out on
each face match against a live camera. Both paths write the same table
through the same upsert-by-(person,date) shape, so a day's row never cares
which one produced it.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, timedelta
from datetime import time as time_type
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.models import AttendanceRecord, PresenceVisit, StudentStaff
from app.services.attendance_policy import EARLY_YES, early_leave_verdict, load_policy
from app.schemas.attendance import (
    AttendanceDayOut,
    AttendanceMonthOut,
    AttendancePersonOut,
    AttendanceRecordIn,
    AttendanceSummaryOut,
)
from app.storage import presigned_url
from app.timezone import INSTITUTE_TZ, INSTITUTE_TZ_NAME, local_now
from app.utils import compute_initials
from app.timezone import business_today, day_start, local_date

router = APIRouter(prefix="/api/attendance", tags=["attendance"])

PRESENT_STATUSES = ("keldi", "kech_keldi")
MAX_SUMMARY_MONTHS = 12

# Kalendarni o'qish hisobot sahifasidan ham kerak (odamning kuni).
ReadDep = Annotated[CurrentUser, Depends(require_permission("manageAttendance", "viewReports"))]
# Yozuvni qo'lda qo'yish yoki o'chirish — faqat davomat huquqi bilan.
EditDep = Annotated[CurrentUser, Depends(require_permission("manageAttendance"))]


def _parse_time(value: str | None) -> time_type | None:
    if value is None:
        return None
    try:
        return time_type.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"'{value}' — vaqt 'HH:MM' formatida bo'lishi kerak") from exc


def _person_uuid(value: str) -> uuid.UUID:
    """Noto'g'ri identifikator — bazaga yetib borib 500 bermasin, 404 bo'lsin."""
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Talaba/xodim topilmadi") from None


def _month_start(month: str) -> date_type:
    try:
        year_part, month_part = month.split("-")
        return date_type(int(year_part), int(month_part), 1)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "month 'YYYY-MM' formatida bo'lishi kerak") from exc


def _add_months(first: date_type, count: int) -> date_type:
    index = first.year * 12 + first.month - 1 + count
    return date_type(index // 12, index % 12 + 1, 1)


def _minutes(value: time_type) -> float:
    return value.hour * 60 + value.minute + value.second / 60


def _is_early_leave(
    record: AttendanceRecord,
    last_seen: time_type | None = None,
    *,
    sightings: int | None = None,
    now: datetime | None = None,
) -> bool:
    """TT kriteriya 9 — "erta ketdi" deb ko'rsatiladimi.

    Qoidaning O'ZI endi bu yerda emas: u
    app/services/attendance_policy.early_leave_verdict() da, ya'ni hisobot
    (app/services/hisobot.py) bilan AYNAN bitta. Ilgari uch joyda uch xil
    hisoblanardi va hisobot 64 qatordan 54 tasini "erta ketdi" deb
    ko'rsatib yuborgan edi.

    Bu yerda faqat bitta tarjima: kartochka uchun "erta ketdi"gina True,
    "aniqlanmadi" esa False — noma'lumni ayblovga aylantirmaymiz."""
    return (
        early_leave_verdict(
            status=record.status,
            day=record.date,
            check_in=record.check_in,
            check_out=record.check_out,
            last_seen=last_seen,
            sightings=sightings,
            source=record.source,
            now=now,
        )
        == EARLY_YES
    )


@dataclass(frozen=True)
class DaySightings:
    """Bir kunlik ko'rinish tarixi: oxirgi payt va necha marta ko'rilgan."""
    last_seen: time_type
    count: int


async def _sightings_by_day(
    db: AsyncSession, person_id: uuid.UUID, first: date_type, end: date_type
) -> dict[date_type, DaySightings]:
    """[first, end) oralig'idagi har bir kun uchun odamni istalgan kamera
    oxirgi marta ko'rgan payti va jami ko'rinishlar soni (institut vaqti) —
    bitta GROUP BY so'rovi.

    Ko'rinishlar soni "erta ketdi" ni aytish uchun shart: bitta ko'rinish
    "o'sha paytda ketdi" degani emas, "bir marta ko'rindi" deganidir."""
    start_at = day_start(first)
    end_at = day_start(end)
    local_last_seen = func.timezone(INSTITUTE_TZ_NAME, PresenceVisit.last_seen_at)
    # Ish kuni (06:00 dan) bo'yicha: 00:00-05:59 dagi ko'rinish kechagi kunga tegishli.
    business_day = local_date(PresenceVisit.last_seen_at)
    rows = await db.execute(
        select(business_day, func.max(local_last_seen), func.sum(PresenceVisit.sightings))
        .where(PresenceVisit.student_staff_id == person_id)
        .where(PresenceVisit.last_seen_at >= start_at)
        .where(PresenceVisit.last_seen_at < end_at)
        .group_by(business_day)
    )
    return {
        day: DaySightings(moment.time().replace(microsecond=0), int(count or 0))
        for day, moment, count in rows.all()
    }


def _to_out(record: AttendanceRecord, seen: DaySightings | None = None) -> AttendanceDayOut:
    return AttendanceDayOut(
        date=record.date.isoformat(),
        status=record.status,
        check_in=record.check_in.strftime("%H:%M") if record.check_in else None,
        check_out=record.check_out.strftime("%H:%M") if record.check_out else None,
        early_leave=_is_early_leave(
            record,
            seen.last_seen if seen else None,
            sightings=seen.count if seen else None,
        ),
    )


def _month_summary(
    month: str, records: list[AttendanceRecord], seen: dict[date_type, DaySightings] | None = None
) -> AttendanceMonthOut:
    counted = [r for r in records if r.status != "dam_olish"]
    present = sum(r.status == "keldi" for r in counted)
    late = sum(r.status == "kech_keldi" for r in counted)
    attended = [r for r in counted if r.status in PRESENT_STATUSES]
    # Daqiqa aniqligida (soniyasiz) — "Institut holati" va hisobot bilan bir xil o'rtacha.
    arrivals = [r.check_in.hour * 60 + r.check_in.minute for r in attended if r.check_in]
    stays = [
        _minutes(r.check_out) - _minutes(r.check_in)
        for r in attended
        if r.check_in and r.check_out and r.check_out > r.check_in
    ]
    avg_arrival = round(sum(arrivals) / len(arrivals)) if arrivals else None
    return AttendanceMonthOut(
        month=month,
        recorded_days=len(counted),
        present=present,
        late=late,
        absent=sum(r.status == "kelmadi" for r in counted),
        early_leave=sum(
            _is_early_leave(
                r,
                day.last_seen if (day := (seen or {}).get(r.date)) else None,
                sightings=day.count if day else None,
            )
            for r in counted
        ),
        rate=round((present + late) * 100 / len(counted), 1) if counted else None,
        avg_arrival=f"{avg_arrival // 60:02d}:{avg_arrival % 60:02d}" if avg_arrival is not None else None,
        avg_presence_minutes=round(sum(stays) / len(stays)) if stays else None,
    )


@router.get("/{student_staff_id}", response_model=list[AttendanceDayOut])
async def get_attendance_calendar(
    student_staff_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: ReadDep,
    month: Annotated[str, Query(description="YYYY-MM")],
) -> list[AttendanceDayOut]:
    person_id = _person_uuid(student_staff_id)
    first = _month_start(month)
    # Sana oralig'i: (odam, sana) unikal indeksi to'g'ridan-to'g'ri o'qiladi.
    # extract(year/month) esa odamning har bir yozuvini hisoblab chiqardi.
    stmt = (
        select(AttendanceRecord)
        .where(AttendanceRecord.student_staff_id == person_id)
        .where(AttendanceRecord.date >= first)
        .where(AttendanceRecord.date < _add_months(first, 1))
        .order_by(AttendanceRecord.date)
    )
    result = await db.execute(stmt)
    await load_policy(db)  # _is_early_leave ish tugashini keshdan o'qiydi
    seen = await _sightings_by_day(db, person_id, first, _add_months(first, 1))
    return [_to_out(r, seen.get(r.date)) for r in result.scalars().all()]


@router.get("/{student_staff_id}/summary", response_model=AttendanceSummaryOut)
async def get_attendance_summary(
    student_staff_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: ReadDep,
    months: Annotated[int, Query(ge=1, le=MAX_SUMMARY_MONTHS)] = 6,
) -> AttendanceSummaryOut:
    """Odam kartasi va joriy oy bilan birga oxirgi N oy yig'indisi —
    kalendar sahifasining tepasi va trend grafigi bitta so'rovda."""
    from app.jobs.absence_marker import _working_weekdays

    person = (
        await db.execute(
            select(StudentStaff)
            .options(selectinload(StudentStaff.faculty))
            .where(StudentStaff.id == _person_uuid(student_staff_id))
        )
    ).scalar_one_or_none()
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Talaba/xodim topilmadi")

    current = business_today().replace(day=1)
    first = _add_months(current, -(months - 1))
    records = (
        await db.execute(
            select(AttendanceRecord)
            .where(AttendanceRecord.student_staff_id == person.id)
            .where(AttendanceRecord.date >= first)
            .where(AttendanceRecord.date < _add_months(current, 1))
        )
    ).scalars().all()

    await load_policy(db)
    seen = await _sightings_by_day(db, person.id, first, _add_months(current, 1))
    by_month: dict[str, list[AttendanceRecord]] = defaultdict(list)
    for record in records:
        by_month[record.date.strftime("%Y-%m")].append(record)
    keys = [_add_months(first, i).strftime("%Y-%m") for i in range(months)]

    return AttendanceSummaryOut(
        person=AttendancePersonOut(
            id=str(person.id),
            full_name=person.full_name,
            type=person.type,
            faculty=person.faculty.name if person.faculty else "",
            unit=person.group_or_position,
            biometrics_status=person.biometrics_status,
            initials=compute_initials(person.full_name),
            biometric_photo_url=presigned_url(person.biometric_photo_key) if person.biometric_photo_key else None,
        ),
        months=[_month_summary(key, by_month.get(key, []), seen) for key in keys],
        working_weekdays=sorted(_working_weekdays()),  # attendance_policy.work_days
    )


@router.post("", response_model=AttendanceDayOut, status_code=status.HTTP_201_CREATED)
async def record_attendance(
    body: AttendanceRecordIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: EditDep,
) -> AttendanceDayOut:
    person = await db.get(StudentStaff, _person_uuid(body.student_staff_id))
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
            # source='qolda' — qo'lda kiritilgan/tuzatilgan yozuv. Ilgari
            # bu ustun bo'sh qolardi va operatorning tuzatishi kamera
            # yozuvidan farq qilmasdi: (a) ish vaqti qoidasi o'zgarganda
            # qayta hisoblash (app/routers/attendance_policy.py) uni
            # kamera yozuvi deb bilib holatini qaytadan yozardi, (b) shu
            # kuni kamera odamni ko'rsa tuzatish ustiga yozilardi.
            # hisobot.SOURCE_LABEL da "qolda" allaqachon kutilgan.
            source="qolda",
        )
        .on_conflict_do_update(
            index_elements=[AttendanceRecord.student_staff_id, AttendanceRecord.date],
            set_={"status": body.status, "check_in": check_in, "check_out": check_out, "source": "qolda"},
        )
        .returning(AttendanceRecord)
    )
    result = await db.execute(stmt)
    record = result.scalar_one()

    await log_action(
        db, request, current_user.id, f"Davomat qayd etdi: {person.full_name} ({body.date})", "Talabalar"
    )
    await db.commit()
    # Kalendar (GET) bilan bir xil javob: "erta ketdi" hukmi shu kungi
    # ko'rinishlarga tayanadi — ularsiz saqlangan kun qayta yuklanguncha
    # boshqacha ko'rinardi.
    await load_policy(db)
    seen = await _sightings_by_day(db, person.id, record.date, record.date + timedelta(days=1))
    return _to_out(record, seen.get(record.date))


@router.delete("/{student_staff_id}/{date}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attendance_record(
    student_staff_id: str,
    date: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: EditDep,
) -> None:
    person_id = _person_uuid(student_staff_id)
    try:
        date_value = date_type.fromisoformat(date)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "date 'YYYY-MM-DD' formatida bo'lishi kerak") from exc

    result = await db.execute(
        select(AttendanceRecord)
        .where(AttendanceRecord.student_staff_id == person_id)
        .where(AttendanceRecord.date == date_value)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Davomat yozuvi topilmadi")

    person = await db.get(StudentStaff, person_id)
    await log_action(
        db, request, current_user.id,
        f"Davomat yozuvini o'chirdi: {person.full_name if person else student_staff_id} ({date})", "Talabalar"
    )
    await db.delete(record)
    await db.commit()
