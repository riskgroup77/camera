"""HEMIS bilan davriy sinxronlash (settings.hemis_sync_interval_hours).

0 — faqat qo'lda (admin paneldagi "Sinxronlash" tugmasi). Navbat
integration_sync_runs jadvalidagi oxirgi urinishdan hisoblanadi, ya'ni
server qayta ishga tushganda sinxronlash darhol takrorlanmaydi. Xato bilan
tugagan urinish uzog'i bilan bir soatdan keyin qayta sinab ko'riladi.
Qo'lda boshlangan sinxronlash bilan ustma-ust tushmaydi (start_run).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import settings
from app.models import IntegrationSyncRun
from app.services.integrations import hemis

logger = logging.getLogger("app.jobs.hemis_sync")

CHECK_INTERVAL_SECONDS = 600
FAILED_RETRY_AFTER = timedelta(hours=1)
SCHEDULED_TRIGGER = "tizim (jadval)"


async def is_sync_due(db, now: datetime | None = None) -> bool:
    interval_hours = settings.hemis_sync_interval_hours
    if interval_hours <= 0 or not hemis.hemis_configured():
        return False
    now = now or datetime.now(timezone.utc)
    last = (
        await db.execute(
            select(IntegrationSyncRun)
            .where(IntegrationSyncRun.source == hemis.SOURCE)
            .order_by(IntegrationSyncRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last is None or last.started_at is None:
        return True
    interval = timedelta(hours=interval_hours)
    if last.status == "xato":
        interval = min(interval, FAILED_RETRY_AFTER)
    return now - last.started_at >= interval


async def run_scheduled_sync_once() -> bool:
    """Navbati kelgan bo'lsa sinxronlaydi. True — ishga tushirildi."""
    async with hemis.session_factory() as db:
        if not await is_sync_due(db):
            return False
        run = await hemis.start_run(db, SCHEDULED_TRIGGER)
    if run is None:
        return False
    await hemis.run_sync(run.id)
    return True


# Jadvalning o'zi to'liq sinxronlashdan tez-tez yangilanadi: dars ko'chiriladi,
# xona almashadi — kamera va punktuallik tekshiruvi eskirgan jadvalga qaramasin.
_last_schedule_refresh: list[datetime | None] = [None]


async def run_schedule_refresh_once(now: datetime | None = None) -> dict | None:
    """Faqat dars jadvali (settings.hemis_schedule_interval_hours). None —
    navbati kelmagan, HEMIS sozlanmagan yoki to'liq sinxronlash ishlamoqda."""
    from app.services.integrations import hemis_schedule

    if settings.hemis_schedule_interval_hours <= 0 or not hemis.hemis_configured():
        return None
    now = now or datetime.now(timezone.utc)
    last = _last_schedule_refresh[0]
    if last is not None and now - last < timedelta(hours=settings.hemis_schedule_interval_hours):
        return None
    async with hemis.session_factory() as db:
        running = (
            await db.execute(
                select(IntegrationSyncRun.id).where(
                    IntegrationSyncRun.source == hemis.SOURCE, IntegrationSyncRun.status == "ishlamoqda"
                )
            )
        ).first()
        if running is not None:
            return None
        _last_schedule_refresh[0] = now
        first, last_day = hemis_schedule.schedule_window()
        async with hemis.HemisClient() as client:
            items = await hemis_schedule.fetch_lessons(client, first, last_day)
            numbers = hemis.employee_numbers(await hemis.fetch_employees(client))
        stats = await hemis_schedule.sync_schedule(db, items, numbers, first=first, last=last_day)
        await db.commit()
    logger.info("HEMIS schedule refreshed", extra={"event": "hemis_schedule_refreshed", "stats": stats})
    return stats


async def hemis_sync_loop() -> None:
    while True:
        try:
            await run_scheduled_sync_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("scheduled HEMIS sync failed", extra={"event": "hemis_sync_loop_error"})
        try:
            await run_schedule_refresh_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("HEMIS schedule refresh failed", extra={"event": "hemis_schedule_error"})
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
