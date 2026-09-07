"""Dars jadvali asosidagi davomat — TT kriteriya 7 ("Talaba davomati") va
8 ("Darsga kechikish") ning dars darajasidagi qismi.

Muammo. Tizim davomatni kun bo'yicha hisoblardi: kamera odamni tanidi ->
o'sha kunga "keldi" yozildi. Bu institutning haqiqiy savoliga javob
bermaydi. Kirish eshigidan o'tib, keyin darsga kirmagan talaba kun
bo'yicha "keldi" bo'lib qolaverardi, va bu holatni tizim printsipial
ravishda ko'ra olmasdi — chunki u dars jadvalini davomat uchun umuman
ishlatmasdi (jadval faqat kechikish CHEGARASINI hisoblashda qatnashardi).

Yechim. Har bir dars uchun alohida davomat (app/models/lesson_attendance.py):
kim shu darsda ko'rindi, birinchi marta qachon, necha marta. Ma'lumot
manbai — allaqachon olinayotgan kadrlar: app/jobs/lesson_quality_ai.py
har bir FAOL dars kamerasidan kadr olib, undagi yuzlarni ro'yxat bilan
solishtiradi (#19 diqqat balli uchun). Endi o'sha bir solishtiruv
natijasi ikkinchi marta ishlatiladi. Ya'ni bu butun mexanizm nol
qo'shimcha kamera so'rovi va nol qo'shimcha inference bilan ishlaydi.

Shu fayl ikkinchi yarmini bajaradi — YAKUNLASH. Dars tugagach:

  ko'rinmagan talaba              -> kelmadi
  birinchi marta kech ko'rindi    -> kech_keldi
  qolganlari                      -> keldi

Uchta qoida buni ayblov emas, o'lchov qilib turadi:

1. Faqat BIOMETRIKASI TASDIQLANGAN talaba baholanadi. Yuzi tizimga
   kiritilmagan odamni kamera printsipial ravishda tanimaydi — uni
   "kelmadi" deb yozish bizning ma'lumotimiz haqidagi faktni odam
   haqidagi ayblovga aylantirish bo'lardi. Aynan shu qoida
   app/jobs/absence_marker.py da ham qo'llanilgan.

2. Bitta tasodifiy moslik yetarli emas. Yonidan o'tib ketgan odam ham,
   yuz mosligining xatosi ham bitta kadrda ko'rinishi mumkin;
   settings.lesson_attendance_min_sightings dan kam ko'ringan talaba
   ishtirok etgan deb hisoblanmaydi. Dars davomida sweep o'nlab marta
   ishga tushadi, shuning uchun haqiqatan o'tirgan talaba bu chegaradan
   osongina o'tadi.

3. Kamerasi ishlamagan dars umuman yakunlanmaydi. Agar darsda birorta
   ham ko'rish bo'lmagan bo'lsa (na bitta talaba), bu "hech kim
   kelmadi" degani emas — bu "kamera hech narsa bermadi" degani.
   Bunday darsni butun guruh uchun "kelmadi" deb yopish tizimning eng
   yomon xato turi bo'lardi. Shunday darslar yakunlanmagan holda
   qoldiriladi va hisobotda "ma'lumot yo'q" bo'lib ko'rinadi.

Kun bo'yicha davomat bilan aloqasi. Darsda ko'rilgan talaba uchun kunlik
AttendanceRecord ham ON CONFLICT DO NOTHING bilan yaratiladi — ya'ni
mavjud yozuv (kirish kamerasidan kelgani yoki adminning qo'lda
tuzatgani) hech qachon ustidan yozilmaydi. Bu kirish kamerasi
o'tkazib yuborgan talabani kun bo'yicha ham to'g'ri hisoblash uchun:
auditoriyada ko'rilgan odam, albatta, binoda ham bo'lgan.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.models import AttendanceRecord, LessonAttendance, LessonSession, StudentStaff
from app.timezone import local_now, to_local

logger = logging.getLogger("app.lesson_attendance")

STUDENT_ATTENDANCE_MODULE_CODE = 7


async def record_sightings(
    db: AsyncSession, session_row: LessonSession, student_ids: set[str], *, seen_at: datetime | None = None
) -> int:
    """Dars davomida ko'rilgan talabalarni qayd etadi.

    Idempotent va poygaga chidamli: ON CONFLICT DO UPDATE, ya'ni bir vaqtda
    ishlayotgan ikkita worker bir xil talabani ko'rsa ham ikkita qator
    paydo bo'lmaydi. Qaytaradi — nechta qator yozilgani.
    """
    if not student_ids:
        return 0

    moment = seen_at or local_now()
    stmt = (
        insert(LessonAttendance)
        .values(
            [
                {
                    "lesson_session_id": session_row.id,
                    "student_staff_id": student_id,
                    "first_seen_at": moment,
                    "last_seen_at": moment,
                    "sightings": 1,
                }
                for student_id in student_ids
            ]
        )
        .on_conflict_do_update(
            constraint="uq_lesson_attendance_person",
            set_={
                "last_seen_at": moment,
                "sightings": LessonAttendance.__table__.c.sightings + 1,
            },
        )
    )
    await db.execute(stmt)
    await db.commit()
    return len(student_ids)


async def _group_roster(db: AsyncSession, group_name: str) -> list[StudentStaff]:
    """Guruhning baholanadigan talabalari — biometrikasi tasdiqlanganlari.

    Yuzi kiritilmagan talaba kamera uchun ko'rinmas, shuning uchun uning
    davomatini bu yo'l bilan o'lchab bo'lmaydi (yuqoridagi 1-qoida)."""
    result = await db.execute(
        select(StudentStaff)
        .where(StudentStaff.type == "talaba")
        .where(StudentStaff.group_or_position == group_name)
        .where(StudentStaff.biometrics_status == "tasdiqlangan")
    )
    return list(result.scalars().all())


async def _finished_unfinalized_sessions(db: AsyncSession) -> list[LessonSession]:
    """Vaqti tugagan, lekin hali yakunlanmagan darslar.

    "Yakunlangan" belgisi alohida ustunda emas, LessonAttendance da
    status yozilgan qator bor-yo'qligida — shu bilan qo'shimcha ustun va
    uni yangilashdagi nomuvofiqlik xavfi paydo bo'lmaydi."""
    now = local_now()
    result = await db.execute(
        select(LessonSession)
        .where(LessonSession.camera_id.is_not(None))
        .where(LessonSession.scheduled_start_time.is_not(None))
    )
    finished = []
    for row in result.scalars().all():
        end = row.scheduled_start_time + timedelta(minutes=settings.lesson_duration_minutes)
        if now < end:
            continue
        already = await db.scalar(
            select(LessonAttendance.id)
            .where(LessonAttendance.lesson_session_id == row.id)
            .where(LessonAttendance.status.is_not(None))
            .limit(1)
        )
        if already is None:
            finished.append(row)
    return finished


async def finalize_lesson(db: AsyncSession, session_row: LessonSession) -> int:
    """Bitta tugagan darsning davomatini yopadi. Qaytaradi — nechta
    talabaga status yozilgani (0 = yakunlanmadi, sababi pastda)."""
    roster = await _group_roster(db, session_row.group_name)
    if not roster:
        # Guruhda biometrikasi tasdiqlangan talaba yo'q — o'lchash uchun
        # hech narsa yo'q, "hamma kelmadi" degani emas.
        return 0

    result = await db.execute(
        select(LessonAttendance).where(LessonAttendance.lesson_session_id == session_row.id)
    )
    seen_rows = {str(r.student_staff_id): r for r in result.scalars().all()}

    min_sightings = settings.lesson_attendance_min_sightings
    confirmed = {pid: row for pid, row in seen_rows.items() if row.sightings >= min_sightings}
    if not confirmed:
        # 3-qoida: darsda birorta ishonchli ko'rish bo'lmagan. Kamera
        # ishlamagan yoki hech kim tanilmagan — ikkalasi ham "butun guruh
        # kelmadi" degan xulosani ko'tarmaydi.
        logger.info(
            "lesson attendance not finalized (no confirmed sightings)",
            extra={"lesson_session_id": str(session_row.id), "group": session_row.group_name},
        )
        return 0

    late_after = session_row.scheduled_start_time + timedelta(
        minutes=settings.attendance_late_to_lesson_grace_minutes
    )

    written = 0
    for student in roster:
        pid = str(student.id)
        row = confirmed.get(pid)
        if row is None:
            missing = seen_rows.get(pid)
            if missing is not None:
                missing.status = "kelmadi"
            else:
                db.add(
                    LessonAttendance(
                        lesson_session_id=session_row.id,
                        student_staff_id=student.id,
                        sightings=0,
                        status="kelmadi",
                    )
                )
            written += 1
            continue

        row.status = "kech_keldi" if row.first_seen_at and row.first_seen_at > late_after else "keldi"
        written += 1
        await _credit_day_attendance(db, student, row)

    await db.commit()
    logger.info(
        "lesson attendance finalized",
        extra={
            "lesson_session_id": str(session_row.id),
            "group": session_row.group_name,
            "roster": len(roster),
            "present": len(confirmed),
        },
    )
    return written


async def _credit_day_attendance(db: AsyncSession, student: StudentStaff, row: LessonAttendance) -> None:
    """Auditoriyada ko'rilgan odam binoda ham bo'lgan — kunlik yozuvni
    ham to'ldiramiz, lekin HECH QACHON mavjudini ustidan yozmaymiz
    (ON CONFLICT DO NOTHING): kirish kamerasidan kelgan aniqroq vaqt ham,
    adminning qo'lda tuzatgani ham shu yerda buzilib ketmasligi kerak."""
    if row.first_seen_at is None:
        return
    local_seen = to_local(row.first_seen_at)
    await db.execute(
        insert(AttendanceRecord)
        .values(
            student_staff_id=student.id,
            date=local_seen.date(),
            status=row.status,
            check_in=local_seen.time(),
        )
        .on_conflict_do_nothing(constraint="uq_attendance_person_date")
    )


async def run_lesson_attendance_finalization_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """Tugagan darslarni yakunlaydi. Qaytaradi — nechta talabaga status
    yozilgani (darslar soni emas)."""
    async with session_factory() as db:
        from app.jobs.module_status import is_module_active

        if not await is_module_active(db, STUDENT_ATTENDANCE_MODULE_CODE):
            return 0
        sessions = await _finished_unfinalized_sessions(db)
        total = 0
        for session_row in sessions:
            try:
                total += await finalize_lesson(db, session_row)
            except Exception:
                await db.rollback()
                logger.exception(
                    "lesson attendance finalization failed",
                    extra={"lesson_session_id": str(session_row.id)},
                )
    return total


async def lesson_attendance_loop() -> None:
    while True:
        try:
            count = await run_lesson_attendance_finalization_once()
            if count:
                logger.info("lesson attendance finalized", extra={"records": count})
        except Exception:
            logger.exception("lesson attendance finalization sweep failed")
        await asyncio.sleep(settings.lesson_attendance_finalize_interval_seconds)
