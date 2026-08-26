"""TT kriteriya 5 ("Olomon zichligi anomaliyasi") — flags a sudden spike
in how many faces a camera detects, relative to that camera's OWN recent
baseline, instead of a fixed headcount threshold. A busy corridor
junction and a quiet office both need "anomaly relative to normal" to
mean anything useful — a single global threshold would either miss real
crowding at a normally-quiet camera or never stop firing at a normally-
busy one.

Reuses detect_faces() from the same InsightFace pipeline every other
sweep loop uses — no separate crowd-counting model (CSRNet/YOLO-crowd,
per this criterion's original registry entry). Honest scope note: face
count is a LOWER BOUND on people present, not a true headcount — anyone
facing away from the camera, occluded, or too small/far to detect isn't
counted. Real crowding can go undetected if most people have their backs
to the camera; treat this as a coarse anomaly signal, not a precise
density measurement.

Baseline is a per-camera in-memory rolling window of recent face counts
— NOT persisted, resets on restart (same tradeoff as
app/services/stream_cache.py's readers; rebuilds within
crowd_baseline_min_samples sweep ticks). A spike requires the current
count to clear BOTH a configurable absolute floor (so a camera that
normally sees 1-2 people doesn't "anomaly" at 3) AND
settings.crowd_spike_multiplier times its own recent average.
"""

import asyncio
import logging
from collections import defaultdict, deque
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
from app.schemas.event import EventOut
from app.services.face_recognition import detect_faces
from app.services.frame_grabber import grab_frame
from app.ws import manager

logger = logging.getLogger("app.crowd_density_ai")

CROWD_MODULE_CODE = 5
CROWD_MODULE_NAME = "Olomon zichligi anomaliyasi"

# See app/jobs/attendance_ai.py's _camera_semaphore docstring — same
# rationale, own semaphore so this job can't starve (or be starved by)
# the other AI sweep loops' camera slots.
_sweep_guard = SweepGuard("crowd_density_ai")

# Per-camera rolling history of recent face counts, keyed by camera id
# (string). Module-level, in-memory, unbounded number of keys (one per
# camera ever swept) but each value is capped at
# settings.crowd_baseline_window samples.
_face_count_history: dict[str, deque[int]] = defaultdict(lambda: deque(maxlen=settings.crowd_baseline_window))


async def _recently_flagged(db: AsyncSession, camera_id) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.crowd_dedup_minutes)
    result = await db.execute(
        select(Event.id)
        .where(Event.module_code == CROWD_MODULE_CODE)
        .where(Event.camera_id == camera_id)
        .where(Event.occurred_at >= cutoff)
    )
    return result.scalar_one_or_none() is not None


def _is_spike(camera_id: str, current_count: int) -> bool:
    """Updates camera_id's rolling history as a side effect (every call
    counts toward future baselines, whether or not it's a spike) and
    returns whether current_count is a spike relative to the history
    BEFORE this call — a spike frame joining its own baseline would blunt
    detection of a second consecutive spike tick."""
    history = _face_count_history[camera_id]
    is_spike = False
    if len(history) >= settings.crowd_baseline_min_samples:
        baseline = sum(history) / len(history)
        threshold = max(settings.crowd_min_absolute, baseline * settings.crowd_spike_multiplier)
        is_spike = current_count >= threshold
    history.append(current_count)
    return is_spike


async def process_camera_frame_for_crowd(
    frame_bytes: bytes, db: AsyncSession, camera: Camera, faces: list | None = None
) -> bool:
    """Returns True if a (deduped) crowd-anomaly Event was raised."""
    if faces is None:
        faces = await detect_faces(frame_bytes)
    count = len(faces)

    if not _is_spike(str(camera.id), count):
        return False

    if await _recently_flagged(db, camera.id):
        return False

    event = Event(
        camera_id=camera.id,
        camera_name=camera.name,
        building=camera.building.name if camera.building else "",
        module_code=CROWD_MODULE_CODE,
        module_name=CROWD_MODULE_NAME,
        group="A",
        confidence=60,  # a coarse face-count proxy, not a real crowd-density model — see module docstring
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


async def run_crowd_density_ai_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """Grabs one frame from every reachable 'faol' camera and checks its
    face count against that camera's own rolling baseline — cameras run
    concurrently (bounded by _camera_semaphore). See
    app/jobs/attendance_ai.py's run_attendance_ai_sweep_once, which this
    mirrors. Returns how many crowd-anomaly Events were raised."""
    async with session_factory() as db:
        if not await is_module_active(db, CROWD_MODULE_CODE):
            return 0
        result = await db.execute(
            select(Camera).where(Camera.status == "faol").where(camera_allows_module(CROWD_MODULE_CODE))
        )
        cameras = [c for c in result.scalars().all() if c.stream_url and is_reachable(c.last_seen_at)]

    if not cameras:
        return 0

    async def _process_one(camera: Camera) -> bool:
        async with camera_sweep_slot():
            frame = await grab_frame(camera.stream_url)
            if frame is None:
                return False
            async with session_factory() as camera_db:
                return await process_camera_frame_for_crowd(frame, camera_db, camera)

    results = await asyncio.gather(*(_process_one(camera) for camera in cameras), return_exceptions=True)

    total = 0
    for camera, result in zip(cameras, results, strict=True):
        if isinstance(result, BaseException):
            logger.exception("crowd density camera task failed", extra={"camera_id": str(camera.id)}, exc_info=result)
            continue
        if result:
            total += 1
    return total


async def crowd_density_ai_loop() -> None:
    while True:
        try:
            count = await _sweep_guard.run(run_crowd_density_ai_sweep_once)
            if count:
                logger.warning("crowd density AI sweep raised events", extra={"events": count})
        except Exception:
            logger.exception("crowd density AI sweep failed")
        await asyncio.sleep(settings.crowd_ai_interval_seconds)
