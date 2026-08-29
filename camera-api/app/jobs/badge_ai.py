"""TT kriteriya 12 — ID-badge yo'qligi (ko'krak hududida badge evristikasi)."""

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
from app.services.badge_detection import has_visible_badge
from app.services.event_bus import raise_event
from app.services.frame_grabber import grab_frame_pair_for_camera
from app.services.pose_detection import detect_poses

logger = logging.getLogger("app.badge_ai")

BADGE_MODULE_CODE = 12
BADGE_MODULE_NAME = "ID-badge taqilganligi"

_sweep_guard = SweepGuard("badge_ai")


def _decode(frame_bytes: bytes):
    import cv2
    import numpy as np

    arr = np.frombuffer(frame_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


async def _recently_flagged(db: AsyncSession, camera_id) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.badge_dedup_minutes)
    result = await db.execute(
        select(Event.id)
        .where(Event.module_code == BADGE_MODULE_CODE)
        .where(Event.camera_id == camera_id)
        .where(Event.occurred_at >= cutoff)
    )
    return result.scalar_one_or_none() is not None


async def _frame_missing_badge(frame_bytes: bytes) -> bool:
    image = _decode(frame_bytes)
    if image is None:
        return False
    poses = await detect_poses(frame_bytes)
    if not poses:
        return False
    for pose in poses:
        if has_visible_badge(image, pose.points):
            return False
    return True


async def process_camera_frame_pair_for_badge(
    frame_a: bytes, frame_b: bytes, db: AsyncSession, camera: Camera
) -> bool:
    if not await _frame_missing_badge(frame_b):
        return False
    if not await _frame_missing_badge(frame_a):
        return False
    if await _recently_flagged(db, camera.id):
        return False

    await raise_event(
        db,
        camera=camera,
        module_code=BADGE_MODULE_CODE,
        module_name=BADGE_MODULE_NAME,
        group="C",
        confidence=35,
        severity="past",
        frame_bytes=frame_b,
    )
    return True


async def run_badge_ai_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    async with session_factory() as db:
        if not await is_module_active(db, BADGE_MODULE_CODE):
            return 0
        result = await db.execute(
            select(Camera).where(Camera.status == "faol").where(camera_allows_module(BADGE_MODULE_CODE))
        )
        cameras = [c for c in result.scalars().all() if c.stream_url and is_reachable(c.last_seen_at)]

    async def _process_one(camera: Camera) -> bool:
        async with camera_sweep_slot():
            frames = await grab_frame_pair_for_camera(camera)
            if frames is None:
                return False
            async with session_factory() as camera_db:
                return await process_camera_frame_pair_for_badge(frames[0], frames[1], camera_db, camera)

    results = await asyncio.gather(*(_process_one(c) for c in cameras), return_exceptions=True)
    total = 0
    for camera, result in zip(cameras, results, strict=True):
        if isinstance(result, BaseException):
            logger.exception("badge AI failed", extra={"camera_id": str(camera.id)}, exc_info=result)
            continue
        if result:
            total += 1
    return total


async def badge_ai_loop() -> None:
    while True:
        try:
            count = await _sweep_guard.run(run_badge_ai_sweep_once)
            if count:
                logger.info("badge AI raised events", extra={"events": count})
        except Exception:
            logger.exception("badge AI sweep failed")
        await asyncio.sleep(settings.badge_ai_interval_seconds)
