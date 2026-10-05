"""Hodisa klipi va arxiv diskining nazorati.

Arxiv faqat oxirgi bir necha soatni saqlaydi (app/services/recording.py).
Hodisa esa haftalar o'tib ham ko'rib chiqiladi, shuning uchun har hodisa
uchun uning atrofidagi qisqa video (hodisadan `event_clip_before_seconds`
oldin, `event_clip_after_seconds` keyin) arxivdan kesib olinadi va MinIO'da
`event_clip_retention_days` kun saqlanadi — Milestone/Genetec'dagi "dalil
klipi" kabi.

Shu sikl diskni ham kuzatadi: umumiy server diskida bo'sh joy
`recording_min_free_percent` dan kamaysa, yozuv to'xtatiladi — arxiv
boshqa loyihalarning ishiga xalal bermasligi kerak.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.models import Camera, Event
from app.services import recording
from app.timezone import local_now

logger = logging.getLogger("app.event_clips")

# Bir aylanishda eng ko'pi bilan shuncha klip — arxiv serveri va tarmoqni
# to'ldirib yubormaslik uchun (odatda bir necha hodisa bo'ladi).
BATCH = 6

_disk_stopped = False


def disk_free_percent(path: str | None = None) -> float | None:
    try:
        usage = shutil.disk_usage(path or settings.recordings_dir)
    except OSError:
        return None
    return usage.free / usage.total * 100 if usage.total else None


def recording_stopped_for_disk() -> bool:
    return _disk_stopped


async def _guard_disk(session_factory: async_sessionmaker[AsyncSession]) -> None:
    global _disk_stopped
    free = disk_free_percent()
    if free is None or _disk_stopped or free >= settings.recording_min_free_percent:
        return
    _disk_stopped = True
    logger.error(
        "archive recording stopped: shared disk is running out of space",
        extra={"free_percent": round(free, 1), "limit_percent": settings.recording_min_free_percent},
    )
    async with session_factory() as db:
        ids = (await db.execute(select(Camera.id))).scalars().all()
    for camera_id in ids:
        await recording.unregister_recording(str(camera_id))


async def _save_clip(db: AsyncSession, event: Event) -> bool:
    from app.storage import upload_file

    start = event.occurred_at - timedelta(seconds=settings.event_clip_before_seconds)
    duration = settings.event_clip_before_seconds + settings.event_clip_after_seconds
    data = await recording.fetch_clip(
        str(event.camera_id), start, duration, max_bytes=settings.event_clip_max_bytes
    )
    if not data:
        event.clip_status = "none"
        return False
    _file_id, key = await asyncio.to_thread(upload_file, data, f"{event.id}.mp4", "video/mp4", "klip")
    event.clip_key = key
    event.clip_status = "ok"
    event.clip_saved_at = local_now()
    return True


async def _expire_old_clips(db: AsyncSession) -> int:
    from app.storage import delete_files_quietly

    cutoff = local_now() - timedelta(days=settings.event_clip_retention_days)
    rows = (
        await db.execute(
            select(Event.id, Event.clip_key).where(Event.clip_key.is_not(None)).where(Event.clip_saved_at < cutoff).limit(200)
        )
    ).all()
    if not rows:
        return 0
    await delete_files_quietly(key for _id, key in rows)
    await db.execute(
        update(Event).where(Event.id.in_([row_id for row_id, _key in rows])).values(clip_key=None, clip_status="muddati")
    )
    await db.commit()
    return len(rows)


async def run_event_clips_once(session_factory: async_sessionmaker[AsyncSession] = SessionLocal) -> int:
    if not settings.recording_enabled:
        return 0
    await _guard_disk(session_factory)
    if not settings.event_clip_enabled:
        return 0
    now = local_now()
    # Hodisadan keyingi qism ham yozilib bo'lishi kerak; arxivdan chiqib
    # ketgan (retention) hodisalar uchun urinish befoyda.
    newest = now - timedelta(seconds=settings.event_clip_after_seconds + 20)
    oldest = now - timedelta(hours=settings.recording_retention_hours) + timedelta(seconds=settings.event_clip_before_seconds)
    saved = 0
    async with session_factory() as db:
        events = (
            await db.execute(
                select(Event)
                .where(Event.camera_id.is_not(None))
                .where(Event.clip_status.is_(None))
                .where(Event.occurred_at <= newest)
                .where(Event.occurred_at >= oldest)
                .where(or_(Event.is_trial.is_(False), Event.severity == "yuqori"))
                .order_by(Event.occurred_at.desc())
                .limit(BATCH)
            )
        ).scalars().all()
        for event in events:
            try:
                if await _save_clip(db, event):
                    saved += 1
            except Exception:
                logger.warning("event clip failed", extra={"event_id": str(event.id)}, exc_info=True)
                event.clip_status = "none"
            await db.commit()
        await _expire_old_clips(db)
    return saved
