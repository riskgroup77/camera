"""TT kriteriya 13 — SIZ (niqob) yo'qligi sanitariya zonalarida."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.jobs.camera_health import is_reachable
from app.jobs.module_status import camera_allows_module, is_module_active
from app.jobs.sweep_guard import SweepGuard
from app.models import Camera, Event
from app.schemas.event import EventOut
from app.services.face_recognition import detect_faces
from app.services.frame_grabber import grab_frame_pair
from app.services.ppe_detection import detect_ppe_sync
from app.ws import manager

logger = logging.getLogger("app.ppe_ai")

PPE_MODULE_CODE = 13
PPE_MODULE_NAME = "Qo'lqop/niqob (kerakli xonalarda)"

_camera_semaphore = asyncio.Semaphore(settings.ai_sweep_camera_concurrency)
_sweep_guard = SweepGuard("ppe_ai")


async def _recently_flagged(db: AsyncSession, camera_id) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.ppe_dedup_minutes)
    result = await db.execute(
        select(Event.id)
        .where(Event.module_code == PPE_MODULE_CODE)
        .where(Event.camera_id == camera_id)
        .where(Event.occurred_at >= cutoff)
    )
    return result.scalar_one_or_none() is not None


def _decode(frame_bytes: bytes) -> np.ndarray | None:
    arr = np.frombuffer(frame_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


async def _frame_missing_ppe(frame_bytes: bytes) -> bool:
    image = _decode(frame_bytes)
    if image is None:
        return False
    faces = await detect_faces(frame_bytes)
    if not faces:
        return False
    for face in faces:
        x1, y1, x2, y2 = face.bbox
        if detect_ppe_sync(image, (float(x1), float(y1), float(x2), float(y2))):
            return False
    return True


async def process_camera_frame_pair_for_ppe(
    frame_a: bytes, frame_b: bytes, db: AsyncSession, camera: Camera
) -> bool:
    if not await _frame_missing_ppe(frame_b):
        return False
    if not await _frame_missing_ppe(frame_a):
        return False
    if await _recently_flagged(db, camera.id):
        return False

    event = Event(
        camera_id=camera.id,
        camera_name=camera.name,
        building=camera.building.name if camera.building else "",
        module_code=PPE_MODULE_CODE,
        module_name=PPE_MODULE_NAME,
        group="C",
        confidence=40,
        severity="o'rta",
        status="yangi",
    )
    db.add(event)
    await db.flush()
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


async def run_ppe_ai_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    async with session_factory() as db:
        if not await is_module_active(db, PPE_MODULE_CODE):
            return 0
        result = await db.execute(
            select(Camera).where(Camera.status == "faol").where(camera_allows_module(PPE_MODULE_CODE))
        )
        cameras = [c for c in result.scalars().all() if c.stream_url and is_reachable(c.last_seen_at)]

    async def _process_one(camera: Camera) -> bool:
        async with _camera_semaphore:
            frames = await grab_frame_pair(camera.stream_url)
            if frames is None:
                return False
            async with session_factory() as camera_db:
                return await process_camera_frame_pair_for_ppe(frames[0], frames[1], camera_db, camera)

    results = await asyncio.gather(*(_process_one(c) for c in cameras), return_exceptions=True)
    total = 0
    for camera, result in zip(cameras, results, strict=True):
        if isinstance(result, BaseException):
            logger.exception("ppe AI failed", extra={"camera_id": str(camera.id)}, exc_info=result)
            continue
        if result:
            total += 1
    return total


async def ppe_ai_loop() -> None:
    while True:
        try:
            count = await _sweep_guard.run(run_ppe_ai_sweep_once)
            if count:
                logger.info("ppe AI raised events", extra={"events": count})
        except Exception:
            logger.exception("ppe AI sweep failed")
        await asyncio.sleep(settings.ppe_ai_interval_seconds)
