"""O'qituvchi darsiga kelmadi — kamerasiz xonadagi darslar uchun.

Kamerasi bor xonadagi darsni app/jobs/teacher_punctuality_ai.py (#22) o'zi
tekshiradi. HEMIS jadvalidagi darslarning ko'pchiligi esa kamerasiz xonada
(2026-09-25: 4520 dan 230 tasi kameraga bog'langan). Bunday darsda xonani
ko'rib bo'lmaydi, lekin "o'qituvchi bugun binoga umuman kelganmi" degan
savolga javob bor: dars boshlanganidan settings.teacher_absence_after_minutes
o'tib ham uni birorta kamera ko'rmagan va kunlik davomatda yo'q bo'lsa —
"teacher_absent" xabari (bildirishnoma qoidalari orqali).

Soxta signal bo'lmasligi uchun faqat yuzi bazada TASDIQLANGAN o'qituvchilar
tekshiriladi (yuzi yo'q odamni kamera baribir ko'rmaydi). Har dars bir marta
(punctuality_checked_at).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import AttendanceRecord, LessonSession, StudentStaff
from app.models.presence_visit import PresenceVisit
from app.services.attendance_policy import load_policy
from app.services.notifications import dispatcher
from app.services.notifications.messages import Message
from app.timezone import business_date, INSTITUTE_TZ, local_now
from app.timezone import day_start

logger = logging.getLogger("app.jobs.teacher_absence")

KIND = "teacher_absent"
CHECK_INTERVAL_SECONDS = 120


async def run_teacher_absence_once(now: datetime | None = None) -> int:
    """Qaytaradi: nechta "kelmadi" xabari."""
    if not settings.teacher_absence_alerts:
        return 0
    now = now or local_now()
    after = timedelta(minutes=settings.teacher_absence_after_minutes)
    alerted = 0
    async with SessionLocal() as db:
        # Dam olish kuni / bayram: HEMIS jadvalida dars tursa ham xabar yo'q.
        if not (await load_policy(db)).is_work_day(business_date(now)):
            return 0
        lessons = list(
            (
                await db.execute(
                    select(LessonSession).where(
                        LessonSession.date == now.date(),
                        LessonSession.teacher_id.is_not(None),
                        LessonSession.camera_id.is_(None),
                        LessonSession.punctuality_checked_at.is_(None),
                        LessonSession.scheduled_start_time.is_not(None),
                        LessonSession.scheduled_start_time <= now - after,
                        LessonSession.scheduled_start_time >= now - after - timedelta(minutes=30),
                    )
                )
            ).unique().scalars()
        )
        if not lessons:
            return 0
        teacher_ids = {lesson.teacher_id for lesson in lessons}
        teachers = {
            row.id: row
            for row in (await db.execute(select(StudentStaff).where(StudentStaff.id.in_(teacher_ids)))).scalars()
        }
        started = day_start(business_date(now))
        present = set(
            (
                await db.execute(
                    select(AttendanceRecord.student_staff_id).where(
                        AttendanceRecord.date == business_date(now),
                        AttendanceRecord.student_staff_id.in_(teacher_ids),
                        # dam_olish — ta'til/sababli (admin kiritgan): kelmadi emas.
                        AttendanceRecord.status.in_(("keldi", "kech_keldi", "dam_olish")),
                    )
                )
            ).scalars()
        ) | set(
            (
                await db.execute(
                    select(PresenceVisit.student_staff_id).where(
                        PresenceVisit.student_staff_id.in_(teacher_ids), PresenceVisit.first_seen_at >= started
                    )
                )
            ).scalars()
        )
        to_send: list[tuple[LessonSession, StudentStaff]] = []
        for lesson in lessons:
            lesson.punctuality_checked_at = datetime.now(timezone.utc)
            teacher = teachers.get(lesson.teacher_id)
            if teacher is None or teacher.biometrics_status != "tasdiqlangan" or lesson.teacher_id in present:
                continue
            lesson.teacher_on_time = False
            to_send.append((lesson, teacher))
        # Avval "tekshirildi" belgisi saqlanadi, keyin xabar ketadi: commit
        # yiqilsa keyingi aylanishda xabar ikkinchi marta ketmasin.
        await db.commit()
        for lesson, teacher in to_send:
            alerted += 1
            start = lesson.scheduled_start_time.astimezone(INSTITUTE_TZ).strftime("%H:%M")
            message = Message(
                title="O'qituvchi darsga kelmadi (bugun kamera ko'rmadi)",
                lines=[
                    ("O'qituvchi", teacher.full_name),
                    ("Guruh", lesson.group_name),
                    ("Fan", lesson.subject),
                    ("Xona", ", ".join(part for part in (lesson.auditorium, lesson.building) if part)),
                    ("Boshlanish", start),
                ],
                footer="Kamerasi yo'q xona: o'qituvchi bugun binoning birorta kamerasida ko'rinmagan.",
            )
            try:
                logs = await dispatcher._dispatch_rules(
                    db, KIND, message, ref_id=str(lesson.id), filters={"building_id": None}
                )
                if logs:
                    await dispatcher._save_logs(db, logs)
            except Exception:
                logger.warning("teacher absence notification failed", exc_info=True)
        await db.commit()
    if alerted:
        logger.info("teacher absence alerts", extra={"event": "teacher_absent", "count": alerted})
    return alerted


async def teacher_absence_loop() -> None:
    while True:
        try:
            await run_teacher_absence_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("teacher absence check failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
