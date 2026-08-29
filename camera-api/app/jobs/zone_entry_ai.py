"""TT kriteriya 2 ("Taqiqlangan zonaga kirish") — flags a person whose
detected ground position falls inside a camera's configured restricted-
zone polygon. See app/services/zone_detection.py for the actual position/
point-in-polygon logic and app/models/camera.py's Camera.
restricted_zone_polygon docstring for the coordinate convention.

No admin UI exists yet to actually DRAW a zone polygon on a camera's
view — a camera without restricted_zone_polygon set is simply invisible
to this job (filtered out of the sweep entirely, not just a no-op check
per tick), the same "not configured yet" pattern as
app/jobs/attendance_ai.py skipping cameras with no stream_url. This is
real, working detection logic waiting on real configuration data, not a
placeholder.

Grabs a PAIR of frames (grab_frame_pair, ~1s apart — the same pattern
app/jobs/fall_ai.py uses) and only raises when a person's ground position
falls inside the zone in BOTH — filters a one-off pose-estimation glitch
(an ankle briefly mis-tracked right at the zone boundary) from a genuine
entry. No person tracking across frames — "in zone in frame_a" and "in
zone in frame_b" could technically be different people, though as with
fall_ai.py this is an unlikely coincidence in a ~1s window.
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
from app.services.pose_detection import detect_poses
from app.services.zone_detection import ground_position, is_inside_zone

logger = logging.getLogger("app.zone_entry_ai")

ZONE_MODULE_CODE = 2
ZONE_MODULE_NAME = "Taqiqlangan zonaga kirish"

# See app/jobs/attendance_ai.py's _camera_semaphore docstring — same
# rationale, own semaphore so this job can't starve (or be starved by)
# the other AI sweep loops' camera slots.
_sweep_guard = SweepGuard("zone_entry_ai")


def _any_person_in_zone(poses, polygon: list) -> bool:
    for pose in poses:
        position = ground_position(pose.points)
        if position is not None and is_inside_zone(position, polygon):
            return True
    return False


async def _recently_flagged(db: AsyncSession, camera_id) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.zone_dedup_minutes)
    result = await db.execute(
        select(Event.id)
        .where(Event.module_code == ZONE_MODULE_CODE)
        .where(Event.camera_id == camera_id)
        .where(Event.occurred_at >= cutoff)
    )
    return result.scalar_one_or_none() is not None


async def process_camera_frame_pair_for_zone(frame_a: bytes, frame_b: bytes, db: AsyncSession, camera: Camera) -> bool:
    """Returns True if a (deduped) zone-entry Event was raised. camera
    must have restricted_zone_polygon set (callers should already have
    filtered for this — see run_zone_entry_ai_sweep_once)."""
    if not camera.restricted_zone_polygon:
        return False

    poses_b = await detect_poses(frame_b)
    if not _any_person_in_zone(poses_b, camera.restricted_zone_polygon):
        return False

    poses_a = await detect_poses(frame_a)
    if not _any_person_in_zone(poses_a, camera.restricted_zone_polygon):
        return False  # not in the zone a moment earlier — likely a one-off pose glitch at the boundary

    if await _recently_flagged(db, camera.id):
        return False

    await raise_event(
        db,
        camera=camera,
        module_code=ZONE_MODULE_CODE,
        module_name=ZONE_MODULE_NAME,
        group="A",
        confidence=65,  # real geometric signal, two-frame confirmed, but the hip-fallback ground position is a weaker proxy — see zone_detection.py
        severity="yuqori",
        frame_bytes=frame_b,
    )
    return True


async def run_zone_entry_ai_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """Grabs a frame pair from every reachable 'faol' camera that has a
    restricted_zone_polygon configured and checks it for zone entries —
    cameras run concurrently (bounded by _camera_semaphore). See
    app/jobs/attendance_ai.py's run_attendance_ai_sweep_once, which this
    mirrors. Returns how many zone-entry Events were raised."""
    async with session_factory() as db:
        if not await is_module_active(db, ZONE_MODULE_CODE):
            return 0
        result = await db.execute(
            select(Camera)
            .where(Camera.status == "faol")
            .where(Camera.restricted_zone_polygon.is_not(None))
            .where(camera_allows_module(ZONE_MODULE_CODE))
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
                return await process_camera_frame_pair_for_zone(frame_a, frame_b, camera_db, camera)

    results = await asyncio.gather(*(_process_one(camera) for camera in cameras), return_exceptions=True)

    total = 0
    for camera, result in zip(cameras, results, strict=True):
        if isinstance(result, BaseException):
            logger.exception("zone entry camera task failed", extra={"camera_id": str(camera.id)}, exc_info=result)
            continue
        if result:
            total += 1
    return total


async def zone_entry_ai_loop() -> None:
    while True:
        try:
            count = await _sweep_guard.run(run_zone_entry_ai_sweep_once)
            if count:
                logger.warning("zone entry AI sweep raised events", extra={"events": count})
        except Exception:
            logger.exception("zone entry AI sweep failed")
        await asyncio.sleep(settings.zone_ai_interval_seconds)
