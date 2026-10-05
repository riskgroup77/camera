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

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.models import AIModuleConfig, AttendanceRecord, StudentStaff
from app.services.attendance_policy import current_policy, load_policy
from app.services.notifications import notify_absences
from app.timezone import business_date, business_seconds, day_start, local_now

logger = logging.getLogger("app.absence_marker")


def _working_weekdays() -> set[int]:
    """ISO weekdays (Mon=1 .. Sun=7) the institute expects attendance on.

    Ish kunlari — attendance_policy (Sozlamalar → Ish vaqti), kechikish va
    hisobot bilan bir xil manba. Ilgari ATTENDANCE_WORKING_WEEKDAYS
    ishlatilardi: admin shanbani dam olish qilsa ham, shu job shanba kuni
    hammani "kelmadi" deb yozardi. Qoida yuklanmagan bo'lsa — standart
    (1-6), sozlamaning standarti bilan bir xil."""
    return set(current_policy().work_days)


def is_working_day(day: date_type) -> bool:
    """Hafta ish kuni va bayram emas (Sozlamalar → Ish vaqti)."""
    return current_policy().is_work_day(day)


def _quiet_after() -> time_type:
    """Shundan keyin ota-onalarga "kelmadi" xabari yuborilmaydi."""
    return time_type.fromisoformat(settings.parent_notify_quiet_after)


def _cutoff_time() -> time_type:
    return time_type.fromisoformat(settings.attendance_absence_mark_after)


STAFF_ATTENDANCE_MODULE_CODE = 6
STUDENT_ATTENDANCE_MODULE_CODE = 7
PRESENT_STATUSES = ("keldi", "kech_keldi")
# Bitta INSERT dagi qatorlar soni. Har qator 3 ta parametr, Postgres esa
# bitta so'rovda 32767 dan ortiq parametr qabul qilmaydi — 10 000+ odamni
# bir so'rovda yozish xato bilan tugardi.
INSERT_CHUNK_SIZE = 5000


async def tracked_types(db: AsyncSession) -> list[str]:
    """Davomati HOZIR yig'ilayotgan populyatsiyalar.

    Uchinchi himoya qoidasi (modul docstring'idagi ikkitasidan keyin):
    moduli o'chirilgan populyatsiyani "kelmadi" deb belgilash ham yolg'on
    ayblov — kamera ularni umuman tekshirmayapti. 2026-09-16 da talabalar
    davomati (#7) shu sababdan to'xtatildi: 5935 talabadan bittasining
    yuzi ro'yxatda."""
    rows = dict(
        (
            await db.execute(
                select(AIModuleConfig.code, AIModuleConfig.active).where(
                    AIModuleConfig.code.in_([STAFF_ATTENDANCE_MODULE_CODE, STUDENT_ATTENDANCE_MODULE_CODE])
                )
            )
        ).all()
    )
    types: list[str] = []
    # Qator topilmasa (seed'dan oldin) — eski xatti-harakat saqlanadi.
    if rows.get(STAFF_ATTENDANCE_MODULE_CODE, True):
        types.append("xodim")
    if rows.get(STUDENT_ATTENDANCE_MODULE_CODE, True):
        types.append("talaba")
    return types


async def mark_absences_for_day(db: AsyncSession, day: date_type, *, notify: bool = True) -> int:
    """Files 'kelmadi' for every enrolled person with no row for `day`.
    Returns how many rows were actually inserted."""
    types = await tracked_types(db)
    if not types:
        return 0
    enrolled_rows = (
        await db.execute(
            select(StudentStaff.id, StudentStaff.type)
            .where(StudentStaff.biometrics_status == "tasdiqlangan")
            # Yuzi shu kuni (yoki keyin) tasdiqlangan odamni ertalab kamera
            # taniy olmasdi — uni "kelmadi" deyish yolg'on ayblov bo'lardi.
            .where(
                or_(
                    StudentStaff.biometrics_confirmed_at.is_(None),
                    StudentStaff.biometrics_confirmed_at < day_start(day),
                )
            )
            # Faol bo'lmagan (chetlatilgan/arxivlangan) odam — "kelmadi" emas.
            .where(StudentStaff.active.is_(True))
            .where(StudentStaff.type.in_(types))
        )
    ).all()
    if not enrolled_rows:
        return 0

    day_statuses = dict(
        (
            await db.execute(
                select(AttendanceRecord.student_staff_id, AttendanceRecord.status).where(AttendanceRecord.date == day)
            )
        ).all()
    )

    missing: list = []
    for person_type in types:
        people = [person_id for person_id, row_type in enrolled_rows if row_type == person_type]
        if not people:
            continue
        seen = sum(1 for person_id in people if day_statuses.get(person_id) in PRESENT_STATUSES)
        coverage = seen / len(people)
        if coverage < settings.attendance_absence_min_coverage:
            # To'rtinchi himoya: kameralar shu kuni odamlarning ozgina
            # qismini tanigan bo'lsa, qolganlarning "kelmadi"si ularning
            # emas, TIZIMNING holati. Productionda (2026-09-17) 687 xodimdan
            # 22 tasi tanilgan — qolgan 665 tasini kelmadi deb yozish
            # yolg'on ayblov bo'lardi. Bunday kun "ma'lumot yo'q" bo'lib
            # qoladi.
            logger.warning(
                "absence marking skipped: recognition coverage too low to trust",
                extra={
                    "date": day.isoformat(),
                    "type": person_type,
                    "recognized": seen,
                    "enrolled": len(people),
                    "required_coverage": settings.attendance_absence_min_coverage,
                },
            )
            continue
        missing.extend(person_id for person_id in people if person_id not in day_statuses)
    if not missing:
        return 0

    marked: list = []
    for start in range(0, len(missing), INSERT_CHUNK_SIZE):
        chunk = missing[start : start + INSERT_CHUNK_SIZE]
        stmt = (
            insert(AttendanceRecord)
            .values([{"student_staff_id": person_id, "date": day, "status": "kelmadi"} for person_id in chunk])
            .on_conflict_do_nothing(index_elements=["student_staff_id", "date"])
            .returning(AttendanceRecord.student_staff_id)
        )
        result = await db.execute(stmt)
        marked.extend(result.scalars().all())
    await db.commit()
    inserted = len(marked)
    if inserted:
        logger.info("marked absences", extra={"date": day.isoformat(), "count": inserted})
        if notify:
            await notify_absences(marked, day)
        else:
            logger.info("absence notices skipped — quiet hours", extra={"date": day.isoformat(), "count": inserted})
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
    today = business_date(now)
    # Ish kuni boshidan (06:00) o'lchanadi: yarim tundan keyingi dum
    # (00:00–05:59) ham shu kunniki, belgilash o'sha paytda ham ishlaydi.
    past_cutoff = business_seconds(now.time()) >= business_seconds(_cutoff_time())

    async with session_factory() as db:
        await load_policy(db)  # ish kunlari — attendance_policy
        # O'tgan kunlar qayta to'ldirilmaydi (test_yesterdays_absences_are_not_backfilled).
        if not past_cutoff or not is_working_day(today):
            return 0
        # Tungi sokinlik: belgilash kechikkan bo'lsa (jarayon o'chgan edi yoki
        # qamrov kech yetdi), ota-onaga yarim tunda SMS ketmaydi.
        quiet = business_seconds(now.time()) >= business_seconds(_quiet_after())
        return await mark_absences_for_day(db, today, notify=not quiet)


async def absence_marking_loop() -> None:
    while True:
        try:
            await run_absence_marking_once()
        except Exception:
            logger.exception("absence marking sweep failed")
        await asyncio.sleep(settings.attendance_absence_marking_interval_seconds)
