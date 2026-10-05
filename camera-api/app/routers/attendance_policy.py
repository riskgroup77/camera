"""Kelib-ketish qoidalari: ish vaqti, kechikish chegarasi, ish kunlari.

GET — hamma davomat ko'ruvchi; PUT — manageAttendance. Saqlanganda oxirgi
RECOMPUTE_DAYS kundagi yozuvlarning holati (keldi / kech_keldi) yangi qoida
bo'yicha qayta hisoblanadi — kelish vaqti o'zgarmaydi. Qo'lda kiritilgan
yozuvdan (source='qolda') boshqa hammasi qayta hisoblanadi, manbasi
yozilmagan eski yozuvlar ham."""

from dataclasses import replace
from datetime import date as date_type, timedelta, time as time_type
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.config import settings
from app.database import get_db
from app.dependencies import CurrentUser, get_current_user, require_permission
from app.models import AttendancePolicy, AttendanceRecord, Holiday, StudentStaff
from app.services.attendance_policy import current_policy, from_row, load_policy, set_cached
from app.timezone import local_now
from app.timezone import business_today

router = APIRouter(prefix="/api/attendance-policy", tags=["attendance"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
RECOMPUTE_DAYS = 60
UPDATE_CHUNK_SIZE = 5000


class PolicyIn(BaseModel):
    staff_start: time_type = Field(alias="staffStart")
    student_start: time_type = Field(alias="studentStart")
    grace_minutes: int = Field(alias="graceMinutes", ge=0, le=180)
    work_end: time_type = Field(alias="workEnd")
    work_days: list[int] = Field(alias="workDays")
    track_last_seen: bool = Field(alias="trackLastSeen", default=True)

    @field_validator("work_days")
    @classmethod
    def _days(cls, value: list[int]) -> list[int]:
        days = sorted(set(value))
        if not days or any(d < 1 or d > 7 for d in days):
            raise ValueError("Ish kunlari 1..7 oralig'ida bo'lishi kerak")
        return days


def _out(policy) -> dict:
    data = policy.to_dict()
    return {
        "staffStart": data["staff_start"],
        "studentStart": data["student_start"],
        "graceMinutes": data["grace_minutes"],
        "workEnd": data["work_end"],
        "workDays": data["work_days"],
        "trackLastSeen": data["track_last_seen"],
        "staffLateAfter": policy.late_after("xodim").strftime("%H:%M"),
        "studentLateAfter": policy.late_after("talaba").strftime("%H:%M"),
    }


@router.get("")
async def get_policy(db: DbDep, _user: Annotated[CurrentUser, Depends(get_current_user)]) -> dict:
    return _out(await load_policy(db, force=True))


@router.put("")
async def put_policy(
    body: PolicyIn,
    request: Request,
    db: DbDep,
    current_user: Annotated[CurrentUser, Depends(require_permission("manageAttendance"))],
) -> dict:
    if body.work_end <= body.staff_start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Ish tugash vaqti boshlanishidan keyin bo'lishi kerak")
    # Ish kuni settings.day_start_hour (06:00) da almashadi — undan oldingi
    # boshlanish kechagi ish kuniga tushib, hamma "kech keldi" bo'lardi.
    earliest = time_type(settings.day_start_hour, 0)
    if body.staff_start < earliest or body.student_start < earliest:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Boshlanish vaqti {settings.day_start_hour:02d}:00 dan oldin bo'lishi mumkin emas — ish kuni shu soatda almashadi",
        )
    row = await db.get(AttendancePolicy, 1)
    if row is None:
        row = AttendancePolicy(id=1)
        db.add(row)
    row.staff_start = body.staff_start
    row.student_start = body.student_start
    row.grace_minutes = body.grace_minutes
    row.work_end = body.work_end
    row.work_days = ",".join(str(d) for d in body.work_days)
    row.track_last_seen = body.track_last_seen
    # Bayram kunlari saqlanadi — ular alohida jadvalda (holidays). Bu jarayon
    # qoidani hali yuklamagan bo'lishi mumkin: bazadan yangidan o'qiladi.
    holidays = (await load_policy(db, force=True)).holidays
    await db.flush()
    policy = replace(from_row(row), holidays=holidays)

    since = business_today() - timedelta(days=RECOMPUTE_DAYS)
    rows = (
        await db.execute(
            select(AttendanceRecord.id, AttendanceRecord.date, AttendanceRecord.check_in, AttendanceRecord.status, StudentStaff.type)
            .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
            .where(AttendanceRecord.date >= since)
            .where(AttendanceRecord.check_in.is_not(None))
            .where(AttendanceRecord.status.in_(("keldi", "kech_keldi")))
            # Qo'lda tuzatilgan yozuv (source='qolda') tegilmaydi — operator
            # qarori qoidadan ustun. QOLGANLARINING hammasi qayta hisoblanadi,
            # shu jumladan manbasi NULL bo'lgan ESKI yozuvlar: ilgari bu yerda
            # source IN ('kamera','turniket') turardi va productionda 1005 ta
            # yozuvning manbasi NULL, faqat 5 tasi 'kamera' edi — ya'ni "Ish
            # vaqti" sahifasi saqlanganda muvaffaqiyat deb aytardi-yu, amalda
            # deyarli hech nimani qayta hisoblamasdi.
            .where(
                or_(
                    AttendanceRecord.source.is_(None),
                    AttendanceRecord.source != "qolda",
                )
            )
        )
    ).all()
    changed = {"keldi": [], "kech_keldi": []}
    for rec_id, day, check_in, old, person_type in rows:
        new = policy.arrival_status(check_in, person_type, day)
        if new != old:
            changed[new].append(rec_id)
    # Bo'laklab yangilanadi: 60 kun × 10 000 odam = 600 000 qator, hammasi
    # bitta IN () ga sig'maydi — Postgres bitta so'rovda 32 767 dan ortiq
    # parametr qabul qilmaydi va qoidani saqlash butunlay xato bilan
    # tugardi (app/jobs/absence_marker.py:INSERT_CHUNK_SIZE da xuddi shu
    # dars yozilgan).
    for new_status, ids in changed.items():
        for start in range(0, len(ids), UPDATE_CHUNK_SIZE):
            chunk = ids[start : start + UPDATE_CHUNK_SIZE]
            await db.execute(
                update(AttendanceRecord).where(AttendanceRecord.id.in_(chunk)).values(status=new_status)
            )
    recomputed = sum(len(v) for v in changed.values())
    await log_action(
        db, request, current_user.id,
        f"Ish vaqti qoidasini o'zgartirdi: xodim {body.staff_start:%H:%M}, talaba {body.student_start:%H:%M}, "
        f"+{body.grace_minutes} daq; {recomputed} ta yozuv qayta hisoblandi",
        "Davomat",
    )
    await db.commit()
    set_cached(policy)
    return {**_out(policy), "recomputed": recomputed}



# ─────────────────────────────────────────── bayram va dam olish kunlari

#: O'zbekistonda har yili bir xil sanadagi dam olish kunlari (Mehnat kodeksi).
#: Ramazon va Qurbon hayit sanasi har yili o'zgaradi — ular qo'lda qo'shiladi.
FIXED_HOLIDAYS = (
    (1, 1, "Yangi yil"),
    (3, 8, "Xalqaro xotin-qizlar kuni"),
    (3, 21, "Navro'z bayrami"),
    (5, 9, "Xotira va qadrlash kuni"),
    (9, 1, "Mustaqillik kuni"),
    (10, 1, "O'qituvchi va murabbiylar kuni"),
    (12, 8, "Konstitutsiya kuni"),
)


class HolidayIn(BaseModel):
    date: date_type
    name: str = Field(min_length=1, max_length=120)


def _holiday_out(row: Holiday) -> dict:
    return {"date": row.date.isoformat(), "name": row.name}


async def _apply_holiday(db: AsyncSession, day: date_type) -> int:
    """O'tgan sana bayram deb belgilansa: o'sha kungi "kelmadi" — "dam_olish",
    "kech_keldi" — "keldi" (bayramda kechikish yo'q). Qo'lda tuzatilgan yozuv
    tegilmaydi. Qaytaradi: nechta yozuv o'zgardi."""
    not_manual = or_(AttendanceRecord.source.is_(None), AttendanceRecord.source != "qolda")
    absent = await db.execute(
        update(AttendanceRecord)
        .where(AttendanceRecord.date == day, AttendanceRecord.status == "kelmadi", not_manual)
        .values(status="dam_olish")
    )
    late = await db.execute(
        update(AttendanceRecord)
        .where(AttendanceRecord.date == day, AttendanceRecord.status == "kech_keldi", not_manual)
        .values(status="keldi")
    )
    return (absent.rowcount or 0) + (late.rowcount or 0)


@router.get("/holidays")
async def list_holidays(
    db: DbDep,
    _user: Annotated[CurrentUser, Depends(get_current_user)],
    year: int | None = None,
) -> list[dict]:
    stmt = select(Holiday).order_by(Holiday.date)
    if year:
        stmt = stmt.where(Holiday.date.between(date_type(year, 1, 1), date_type(year, 12, 31)))
    return [_holiday_out(row) for row in (await db.execute(stmt)).scalars().all()]


@router.post("/holidays", status_code=status.HTTP_201_CREATED)
async def add_holiday(
    body: HolidayIn,
    request: Request,
    db: DbDep,
    current_user: Annotated[CurrentUser, Depends(require_permission("manageAttendance"))],
) -> dict:
    row = await db.get(Holiday, body.date)
    if row is None:
        row = Holiday(date=body.date, name=body.name.strip())
        db.add(row)
    else:
        row.name = body.name.strip()
    changed = await _apply_holiday(db, body.date) if body.date <= business_today() else 0
    await log_action(
        db, request, current_user.id, f"Dam olish kuni: {body.date.isoformat()} — {row.name}; {changed} ta yozuv tuzatildi",
        "Davomat",
    )
    await db.commit()
    await load_policy(db, force=True)
    return {**_holiday_out(row), "recomputed": changed}


@router.post("/holidays/standart")
async def add_standard_holidays(
    request: Request,
    db: DbDep,
    current_user: Annotated[CurrentUser, Depends(require_permission("manageAttendance"))],
    year: int | None = None,
) -> dict:
    """Shu yilning o'zgarmas bayramlarini qo'shadi (bor bo'lsa tegmaydi)."""
    year = year or business_today().year
    if not 2000 <= year <= 2100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Yil noto'g'ri")
    existing = set(
        (await db.execute(
            select(Holiday.date).where(Holiday.date.between(date_type(year, 1, 1), date_type(year, 12, 31)))
        )).scalars().all()
    )
    added = 0
    changed = 0
    for month, day, name in FIXED_HOLIDAYS:
        moment = date_type(year, month, day)
        if moment in existing:
            continue
        db.add(Holiday(date=moment, name=name))
        added += 1
        if moment <= business_today():
            changed += await _apply_holiday(db, moment)
    await log_action(db, request, current_user.id, f"{year}-yil bayramlari qo'shildi: {added} ta", "Davomat")
    await db.commit()
    await load_policy(db, force=True)
    return {"added": added, "recomputed": changed}


@router.delete("/holidays/{day}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_holiday(
    day: date_type,
    request: Request,
    db: DbDep,
    current_user: Annotated[CurrentUser, Depends(require_permission("manageAttendance"))],
) -> None:
    row = await db.get(Holiday, day)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bu sana dam olish kuni sifatida yozilmagan")
    await db.delete(row)
    await log_action(db, request, current_user.id, f"Dam olish kuni olib tashlandi: {day.isoformat()}", "Davomat")
    await db.commit()
    await load_policy(db, force=True)
