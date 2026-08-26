"""TT kriteriya 23 ("Yong'in / tutun aniqlash") — color + temporal-flicker
fire detection. See app/services/fire_detection.py for the method itself
and its honest scope/validation limits (short version: validated against
the real false-positive case that killed an earlier color-only attempt,
plus synthetic flicker scenarios — NOT against real fire footage, since
none was available in this environment).

Runs its own camera sweep (separate from vision_ai.py/attendance_ai.py)
because it needs TWO frames a second apart per camera per tick, not one —
see app/services/frame_grabber.py's grab_frame_pair().

Because the underlying signal is still less validated than face-matching
attendance or even the EAR sleep check, a fire Event is deliberately
raised at "yuqori" (high) severity only because a missed fire is far
worse than a missed nap — this is a considered severity choice, not a
confidence claim. Every fire Event needs human confirmation; see
fire_dedup_minutes in app/config.py for why a sustained fire doesn't
re-raise every tick.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.jobs.camera_health import is_reachable
from app.jobs.module_status import camera_allows_module, is_module_active
from app.jobs.sweep_guard import SweepGuard
from app.models import Camera, Event
from app.schemas.event import EventOut
from app.services.fire_detection import fire_pixel_fraction, is_likely_fire
from app.services.frame_grabber import grab_frame_pair
from app.ws import manager

logger = logging.getLogger("app.fire_ai")

FIRE_MODULE_CODE = 23
FIRE_MODULE_NAME = "Yong'in / tutun aniqlash"

# See app/jobs/attendance_ai.py's _camera_semaphore docstring — same
# rationale, own semaphore so fire_ai can't starve (or be starved by)
# attendance_ai/vision_ai's camera slots.
_camera_semaphore = asyncio.Semaphore(settings.ai_sweep_camera_concurrency)
_sweep_guard = SweepGuard("fire_ai")


async def _recently_flagged(db: AsyncSession, camera_id) -> bool:
    """Dedup is per-camera only (unlike vision_ai.py's per-person dedup —
    a fire has no identity to key on): a sustained fire shouldn't re-raise
    an Event every single sweep tick while it's still burning."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.fire_dedup_minutes)
    result = await db.execute(
        select(Event.id)
        .where(Event.module_code == FIRE_MODULE_CODE)
        .where(Event.camera_id == camera_id)
        .where(Event.occurred_at >= cutoff)
    )
    return result.scalar_one_or_none() is not None


async def process_camera_frame_pair_for_fire(
    frame_a: bytes, frame_b: bytes, db: AsyncSession, camera: Camera
) -> bool:
    """Returns True if a (deduped) fire Event was raised."""
    if not is_likely_fire(frame_a, frame_b):
        return False

    if await _recently_flagged(db, camera.id):
        return False

    fraction = fire_pixel_fraction(frame_a, frame_b)
    event = Event(
        camera_id=camera.id,
        camera_name=camera.name,
        building=camera.building.name if camera.building else "",
        module_code=FIRE_MODULE_CODE,
        module_name=FIRE_MODULE_NAME,
        group="F",
        confidence=min(100, round(fraction * 1000)),  # scaled, not a calibrated probability — see module docstring
        severity="yuqori",
        status="yangi",
    )
    db.add(event)
    await db.flush()  # populate event.id/occurred_at before building EventOut
    event_out = EventOut(
        id=str(event.id),
        timestamp=event.occurred_at.strftime("%Y-%m-%d %H:%M"),
        camera_id=str(event.camera_id) if event.camera_id else "",
        camera_name=event.camera_name,
        building=event.building,
        module_code=event.module_code,
        module_name=event.module_name,
        group=event.group,
        confidence=event.confidence,
        severity=event.severity,
        status=event.status,
        person_name=event.person_name,
        reviewed_by=event.reviewed_by,
    )
    await db.commit()
    await manager.broadcast(event_out.model_dump(by_alias=True))
    return True


async def run_fire_ai_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """Grabs a frame pair from every reachable 'faol' camera and checks it
    for fire — cameras run concurrently (bounded by _camera_semaphore),
    not one at a time. See app/jobs/attendance_ai.py's
    run_attendance_ai_sweep_once, which this mirrors. Returns how many
    fire Events were raised."""
    async with session_factory() as db:
        if not await is_module_active(db, FIRE_MODULE_CODE):
            return 0
        result = await db.execute(
            select(Camera).where(Camera.status == "faol").where(camera_allows_module(FIRE_MODULE_CODE))
        )
        cameras = [c for c in result.scalars().all() if c.stream_url and is_reachable(c.last_seen_at)]

    if not cameras:
        return 0

    async def _process_one(camera: Camera) -> bool:
        async with _camera_semaphore:
            frames = await grab_frame_pair(camera.stream_url)
            if frames is None:
                return False
            frame_a, frame_b = frames
            async with session_factory() as camera_db:
                return await process_camera_frame_pair_for_fire(frame_a, frame_b, camera_db, camera)

    results = await asyncio.gather(*(_process_one(camera) for camera in cameras), return_exceptions=True)

    total = 0
    for camera, result in zip(cameras, results, strict=True):
        if isinstance(result, BaseException):
            logger.exception("fire AI camera task failed", extra={"camera_id": str(camera.id)}, exc_info=result)
            continue
        if result:
            total += 1
    return total


async def fire_ai_loop() -> None:
    while True:
        try:
            count = await _sweep_guard.run(run_fire_ai_sweep_once)
            if count:
                logger.warning("fire AI sweep raised events", extra={"fire_events": count})
        except Exception:
            logger.exception("fire AI sweep failed")
        await asyncio.sleep(settings.fire_ai_interval_seconds)
