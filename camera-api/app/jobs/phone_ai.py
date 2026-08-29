"""TT kriteriya 16 ("Imtihonda telefondan foydalanish") — flags a mobile
phone detected in frame, using YOLOv8's COCO-pretrained "cell phone"
class (id 67) via app/services/object_detection.py.

Honest scope note: this detects "a phone is visible in frame", not
specifically "during an exam" — there is no exam-session/schedule
awareness here. The TT criterion's name assumes exam context, but
nothing in this system currently distinguishes an exam period from a
normal class period (the same kind of gap app/jobs/teacher_punctuality_ai.py
needed a real LessonSession.scheduled_start_time to close — this
criterion would need the equivalent "this camera, this time window, is
an exam" data source, which doesn't exist yet). Every phone-in-frame
Event should be read as "a phone was seen on this camera", not "cheating
confirmed" — a human reviewer's job, same as every other AI-raised Event
in this system.

Grabs a PAIR of frames (grab_frame_pair, ~1s apart — the same pattern
app/jobs/fire_ai.py and app/jobs/unauthorized_person_ai.py use) and only
raises when a phone is detected in BOTH — filters out a single
misclassified frame (YOLO on a compressed webcam frame can mistake other
small dark rectangular objects for a phone at moderate confidence).
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
from app.jobs.sweep_concurrency import camera_sweep_slot
from app.models import Camera, Event
from app.services.event_bus import raise_event
from app.services.frame_grabber import grab_frame_pair_for_camera
from app.services.object_detection import detect_objects

logger = logging.getLogger("app.phone_ai")

PHONE_MODULE_CODE = 16
PHONE_MODULE_NAME = "Imtihonda telefondan foydalanish"
PHONE_CLASS_ID = 67  # COCO "cell phone" — verified against this exact model, see app/services/object_detection.py

# See app/jobs/attendance_ai.py's _camera_semaphore docstring — same
# rationale, own semaphore so this job can't starve (or be starved by)
# the other AI sweep loops' camera slots.
_sweep_guard = SweepGuard("phone_ai")


async def _recently_flagged(db: AsyncSession, camera_id) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.phone_dedup_minutes)
    result = await db.execute(
        select(Event.id)
        .where(Event.module_code == PHONE_MODULE_CODE)
        .where(Event.camera_id == camera_id)
        .where(Event.occurred_at >= cutoff)
    )
    return result.scalar_one_or_none() is not None


async def process_camera_frame_pair_for_phone(frame_a: bytes, frame_b: bytes, db: AsyncSession, camera: Camera) -> bool:
    """Returns True if a (deduped) phone-detection Event was raised."""
    detections_b = await detect_objects(frame_b, class_ids=[PHONE_CLASS_ID], confidence=settings.phone_detection_confidence)
    if not detections_b:
        return False

    detections_a = await detect_objects(frame_a, class_ids=[PHONE_CLASS_ID], confidence=settings.phone_detection_confidence)
    if not detections_a:
        return False  # not detected a moment earlier — likely a one-off misclassification

    if await _recently_flagged(db, camera.id):
        return False

    best_confidence = min(
        max(d.confidence for d in detections_a),
        max(d.confidence for d in detections_b),
    )

    await raise_event(
        db,
        camera=camera,
        module_code=PHONE_MODULE_CODE,
        module_name=PHONE_MODULE_NAME,
        group="D",
        confidence=round(best_confidence * 100),  # real YOLO detection confidence, scaled to 0-100
        severity="o'rta",
        frame_bytes=frame_b,
    )
    return True


async def run_phone_ai_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """Grabs a frame pair from every reachable 'faol' camera and checks
    it for phones — cameras run concurrently (bounded by
    _camera_semaphore). See app/jobs/attendance_ai.py's
    run_attendance_ai_sweep_once, which this mirrors. Returns how many
    phone-detection Events were raised."""
    async with session_factory() as db:
        if not await is_module_active(db, PHONE_MODULE_CODE):
            return 0
        result = await db.execute(
            select(Camera).where(Camera.status == "faol").where(camera_allows_module(PHONE_MODULE_CODE))
        )
        cameras = [c for c in result.scalars().all() if c.stream_url and is_reachable(c.last_seen_at)]

    if not cameras:
        return 0

    async def _process_one(camera: Camera) -> bool:
        async with camera_sweep_slot():
            frames = await grab_frame_pair_for_camera(camera)
            if frames is None:
                return False
            frame_a, frame_b = frames
            async with session_factory() as camera_db:
                return await process_camera_frame_pair_for_phone(frame_a, frame_b, camera_db, camera)

    results = await asyncio.gather(*(_process_one(camera) for camera in cameras), return_exceptions=True)

    total = 0
    for camera, result in zip(cameras, results, strict=True):
        if isinstance(result, BaseException):
            logger.exception("phone detection camera task failed", extra={"camera_id": str(camera.id)}, exc_info=result)
            continue
        if result:
            total += 1
    return total


async def phone_ai_loop() -> None:
    while True:
        try:
            count = await _sweep_guard.run(run_phone_ai_sweep_once)
            if count:
                logger.warning("phone AI sweep raised events", extra={"events": count})
        except Exception:
            logger.exception("phone AI sweep failed")
        await asyncio.sleep(settings.phone_ai_interval_seconds)
