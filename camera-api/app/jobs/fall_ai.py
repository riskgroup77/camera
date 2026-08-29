"""TT kriteriya 24 ("Yiqilib tushish") — sweep loop wrapping
app/services/fall_detection.py's per-pose geometry check across every
reachable camera. See that module's docstring for the actual detection
method and its honest scope limits.

Grabs a PAIR of frames (grab_frame_pair, ~1s apart — the same pattern
app/jobs/fire_ai.py and app/jobs/unauthorized_person_ai.py use) and only
raises when at least one detected pose reads as fallen in BOTH — a real
fall involves a sustained horizontal posture; someone transiently bending
down (tying shoes, picking something up) shouldn't trigger this. No
person tracking across the two frames (same limitation
app/jobs/unauthorized_person_ai.py's module docstring documents for
faces) — "a fallen pose in frame_a" and "a fallen pose in frame_b" could,
in principle, be two different people, though in practice a fall being
staged by two unrelated people in the same ~1s window is an unlikely
coincidence to worry about.

Raised at "yuqori" (high) severity deliberately, like
app/jobs/fire_ai.py's fire Events — a missed real fall is far worse than
a false alarm from someone stretching on the floor. Every fall Event
still needs human confirmation, same as every other AI-raised Event in
this system.
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
from app.services.fall_detection import is_fallen
from app.services.frame_grabber import grab_frame_pair_for_camera
from app.services.pose_detection import detect_poses

logger = logging.getLogger("app.fall_ai")

FALL_MODULE_CODE = 24
FALL_MODULE_NAME = "Yiqilib tushish"

# See app/jobs/attendance_ai.py's _camera_semaphore docstring — same
# rationale, own semaphore so this job can't starve (or be starved by)
# the other AI sweep loops' camera slots.
_sweep_guard = SweepGuard("fall_ai")


async def _recently_flagged(db: AsyncSession, camera_id) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.fall_dedup_minutes)
    result = await db.execute(
        select(Event.id)
        .where(Event.module_code == FALL_MODULE_CODE)
        .where(Event.camera_id == camera_id)
        .where(Event.occurred_at >= cutoff)
    )
    return result.scalar_one_or_none() is not None


async def process_camera_frame_pair_for_fall(frame_a: bytes, frame_b: bytes, db: AsyncSession, camera: Camera) -> bool:
    """Returns True if a (deduped) fall Event was raised."""
    poses_b = await detect_poses(frame_b)
    if not any(is_fallen(pose.points) for pose in poses_b):
        return False

    poses_a = await detect_poses(frame_a)
    if not any(is_fallen(pose.points) for pose in poses_a):
        return False  # not fallen a moment earlier — likely a transient bend/crouch, not a real fall

    if await _recently_flagged(db, camera.id):
        return False

    await raise_event(
        db,
        camera=camera,
        module_code=FALL_MODULE_CODE,
        module_name=FALL_MODULE_NAME,
        group="F",
        confidence=65,  # real geometric signal, two-frame confirmed, but not validated against real fall footage — see fall_detection.py
        severity="yuqori",  # a missed real fall is worse than a false alarm — see module docstring
        frame_bytes=frame_b,
    )
    return True


async def run_fall_ai_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """Grabs a frame pair from every reachable 'faol' camera and checks
    it for fallen poses — cameras run concurrently (bounded by
    _camera_semaphore). See app/jobs/attendance_ai.py's
    run_attendance_ai_sweep_once, which this mirrors. Returns how many
    fall Events were raised."""
    async with session_factory() as db:
        if not await is_module_active(db, FALL_MODULE_CODE):
            return 0
        result = await db.execute(
            select(Camera).where(Camera.status == "faol").where(camera_allows_module(FALL_MODULE_CODE))
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
                return await process_camera_frame_pair_for_fall(frame_a, frame_b, camera_db, camera)

    results = await asyncio.gather(*(_process_one(camera) for camera in cameras), return_exceptions=True)

    total = 0
    for camera, result in zip(cameras, results, strict=True):
        if isinstance(result, BaseException):
            logger.exception("fall detection camera task failed", extra={"camera_id": str(camera.id)}, exc_info=result)
            continue
        if result:
            total += 1
    return total


async def fall_ai_loop() -> None:
    while True:
        try:
            count = await _sweep_guard.run(run_fall_ai_sweep_once)
            if count:
                logger.warning("fall AI sweep raised events", extra={"events": count})
        except Exception:
            logger.exception("fall AI sweep failed")
        await asyncio.sleep(settings.fall_ai_interval_seconds)
