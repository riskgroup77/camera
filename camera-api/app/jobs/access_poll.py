"""Turniket qurilmalaridan hodisalarni so'rab olish (Hikvision ISAPI).

Har settings.access_poll_interval_seconds da barcha yoqilgan hikvision
qurilmalari parallel (MAX_CONCURRENT_DEVICES tadan) so'raladi; har biri
o'z sessiyasida — bitta qurilmaning xatosi yoki sekinligi qolganlarini
to'xtatmaydi. Webhook/ZKTeco qurilmalari o'zi yuboradi, bu yerda so'ralmaydi.
"""

import asyncio
import logging
import uuid

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import AccessDevice
from app.services.integrations.hikvision_acs import poll_device

logger = logging.getLogger("app.jobs.access_poll")

MAX_CONCURRENT_DEVICES = 8
# Bitta qurilma so'rovi uchun umumiy chegara (sahifalash bilan birga).
DEVICE_POLL_TIMEOUT_SECONDS = 120


async def _poll_one(device_id: uuid.UUID, semaphore: asyncio.Semaphore, session_factory) -> None:
    async with semaphore:
        try:
            async with session_factory() as db:
                device = await db.get(AccessDevice, device_id)
                if device is None or not device.enabled:
                    return
                await asyncio.wait_for(poll_device(db, device), timeout=DEVICE_POLL_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning("access device poll timed out", extra={"device_id": str(device_id)})
        except Exception:
            logger.exception("access device poll crashed", extra={"device_id": str(device_id)})


async def run_access_poll_once(session_factory=SessionLocal) -> int:
    """Bitta aylanish. Qaytaradi: so'ralgan qurilmalar soni."""
    if not settings.access_control_enabled:
        return 0
    async with session_factory() as db:
        device_ids = (
            await db.execute(
                select(AccessDevice.id)
                .where(AccessDevice.enabled.is_(True))
                .where(AccessDevice.kind == "hikvision")
                .where(AccessDevice.ip.is_not(None))
            )
        ).scalars().all()
    if not device_ids:
        return 0
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_DEVICES)
    await asyncio.gather(*(_poll_one(device_id, semaphore, session_factory) for device_id in device_ids))
    return len(device_ids)


async def access_poll_loop() -> None:
    while True:
        try:
            await run_access_poll_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("access poll iteration failed", extra={"event": "access_poll_error"})
        await asyncio.sleep(max(1, settings.access_poll_interval_seconds))
