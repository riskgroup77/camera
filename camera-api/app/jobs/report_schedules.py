"""Avtomatik hisobotlar: haftalik (dushanba 08:00 dan keyin) va oylik
(1-sana 08:00 dan keyin) hisobotni Telegram'ga yuboradi.

Faqat DB va Telegram — kamera talab qilmaydi. Har 5 daqiqada tekshiradi;
davr uchun bir martalik yuborishni report_schedules.last_sent_at
kafolatlaydi (app/services/report_schedule.py).
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import SessionLocal
from app.services import report_schedule

INTERVAL_SECONDS = 300


async def run_report_schedules_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    return await report_schedule.run_due(session_factory)
