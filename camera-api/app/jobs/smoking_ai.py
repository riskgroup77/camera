"""TT kriteriya 15 — qo'l og'izga yaqin postura (chekish taxminiy signal)."""

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
from app.jobs.sweep_concurrency import camera_sweep_slot
from app.models import Camera, Event
from app.services.event_bus import raise_event
from app.services.frame_grabber import grab_frame_pair_for_camera
from app.services.pose_detection import detect_poses
from app.services.smoking_detection import is_smoking_posture

logger = logging.getLogger("app.smoking_ai")

SMOKING_MODULE_CODE = 15
SMOKING_MODULE_NAME = "Chekish / elektron sigareta"

_sweep_guard = SweepGuard("smoking_ai")


async def _recently_flagged(db: AsyncSession, camera_id) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.smoking_dedup_minutes)
    result = await db.execute(
        select(Event.id)
        .where(Event.module_code == SMOKING_MODULE_CODE)
        .where(Event.camera_id == camera_id)
        .where(Event.occurred_at >= cutoff)
    )
    return result.scalar_one_or_none() is not None


async def _frame_smoking_posture(frame_bytes: bytes) -> bool:
    poses = await detect_poses(frame_bytes)
    return is_smoking_posture(poses)


async def process_camera_frame_pair_for_smoking(
    frame_a: bytes, frame_b: bytes, db: AsyncSession, camera: Camera
) -> bool:
    if not await _frame_smoking_posture(frame_b):
        return False
    if not await _frame_smoking_posture(frame_a):
        return False
    if await _recently_flagged(db, camera.id):
        return False

    await raise_event(
        db,
        camera=camera,
        module_code=SMOKING_MODULE_CODE,
        module_name=SMOKING_MODULE_NAME,
        group="D",
        confidence=35,
        severity="o'rta",
        frame_bytes=frame_b,
    )
    return True


async def run_smoking_ai_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    async with session_factory() as db:
        if not await is_module_active(db, SMOKING_MODULE_CODE):
            return 0
        result = await db.execute(
            select(Camera).where(Camera.status == "faol").where(camera_allows_module(SMOKING_MODULE_CODE))
        )
        cameras = [c for c in result.scalars().all() if c.stream_url and is_reachable(c.last_seen_at)]

    async def _process_one(camera: Camera) -> bool:
        async with camera_sweep_slot():
            frames = await grab_frame_pair_for_camera(camera)
            if frames is None:
                return False
            async with session_factory() as camera_db:
                return await process_camera_frame_pair_for_smoking(frames[0], frames[1], camera_db, camera)

    results = await asyncio.gather(*(_process_one(c) for c in cameras), return_exceptions=True)
    total = 0
    for camera, result in zip(cameras, results, strict=True):
        if isinstance(result, BaseException):
            logger.exception("smoking AI failed", extra={"camera_id": str(camera.id)}, exc_info=result)
            continue
        if result:
            total += 1
    return total


async def smoking_ai_loop() -> None:
    while True:
        try:
            count = await _sweep_guard.run(run_smoking_ai_sweep_once)
            if count:
                logger.info("smoking AI raised events", extra={"events": count})
        except Exception:
            logger.exception("smoking AI sweep failed")
        await asyncio.sleep(settings.smoking_ai_interval_seconds)
