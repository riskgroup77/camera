"""TT kriteriya 4 ("Egasiz qoldirilgan buyum") — flags a foreground region
that stays in roughly the same place across several consecutive sweep
ticks, using OpenCV's MOG2 background subtraction (classical CV — no
object-detection model like YOLO needed for this one).

Tracks only the SINGLE largest qualifying foreground region per camera at
a time — a genuinely simplified MVP, not full multi-object tracking (no
DeepSORT/ByteTrack here, the same class of limitation
app/jobs/vision_ai.py's module docstring documents for face tracking).
If two objects are abandoned in the same camera's view around the same
time, only the larger one is tracked; the other is invisible to this job
until the first one is flagged (and tracking resets) or leaves.

"Static for N consecutive ticks" (settings.abandoned_object_min_
consecutive_ticks) approximates the real requirement that an abandoned
item sits still for MINUTES, not seconds — counted in sweep ticks rather
than wall-clock time, so a slow/delayed tick still counts as one (an
approximation of duration, not an exact timer).

Cross-checked against InsightFace's own face detection: if a face is
detected inside or near the tracked region in the CURRENT frame, it's
someone standing there, not an abandoned object, and tracking resets —
reusing the same detect_faces() pipeline every other AI job uses rather
than needing a separate person-vs-object classifier.

Uses an explicit, low learningRate on the MOG2 subtractor
(settings.abandoned_object_learning_rate) rather than its automatic
default — found from real testing, not assumed: MOG2's automatic rate is
tuned for real ~30fps video, and at this job's ~30s-apart sweep ticks it
absorbed a genuinely static new object into the background model after
just 1-2 ticks, before min_consecutive_ticks ever had a chance to
observe it. See tests/test_abandoned_object_ai.py, which reproduces this
exact failure and confirms the fix.

Honest scope note: MOG2 is a real, standard background-subtraction
algorithm, but this whole approach is inherently sensitive to camera
shake, lighting changes (a shadow moving across the frame reads as
"foreground"), and any other change that isn't literally an abandoned
object — abandoned_object_min_area/max_area_fraction filter out the most
obvious noise (too small to be an object, or too large — likely a
lighting shift covering much of the frame), but this has NOT been
validated against real footage of an actual abandoned item, only
synthetic test frames.
"""

import asyncio
import logging
import math
from dataclasses import dataclass
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
from app.jobs.sweep_concurrency import camera_sweep_slot
from app.models import Camera, Event
from app.schemas.event import EventOut
from app.services.face_recognition import detect_faces
from app.services.frame_grabber import grab_frame
from app.ws import manager

logger = logging.getLogger("app.abandoned_object_ai")

ABANDONED_MODULE_CODE = 4
ABANDONED_MODULE_NAME = "Egasiz qoldirilgan buyum"

# See app/jobs/attendance_ai.py's _camera_semaphore docstring — same
# rationale, own semaphore so this job can't starve (or be starved by)
# the other AI sweep loops' camera slots.
_sweep_guard = SweepGuard("abandoned_object_ai")

BBox = tuple[int, int, int, int]  # x, y, w, h


@dataclass
class _TrackedRegion:
    bbox: BBox
    consecutive_ticks: int = 1


# Per-camera state, module-level and in-memory (not persisted — resets on
# restart, same tradeoff as app/jobs/crowd_density_ai.py's baseline
# history). One MOG2 model and at most one tracked region per camera.
_subtractors: dict[str, cv2.BackgroundSubtractorMOG2] = {}
_tracked_regions: dict[str, _TrackedRegion | None] = {}


def _get_subtractor(camera_id: str) -> cv2.BackgroundSubtractorMOG2:
    if camera_id not in _subtractors:
        _subtractors[camera_id] = cv2.createBackgroundSubtractorMOG2(detectShadows=False)
    return _subtractors[camera_id]


def _largest_static_candidate(mask: np.ndarray) -> BBox | None:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best: BBox | None = None
    best_area = 0.0
    frame_area = mask.shape[0] * mask.shape[1]
    max_area = frame_area * settings.abandoned_object_max_area_fraction
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < settings.abandoned_object_min_area or area > max_area:
            continue
        if area > best_area:
            best_area = area
            best = cv2.boundingRect(contour)
    return best


def _centroid(bbox: BBox) -> tuple[float, float]:
    x, y, w, h = bbox
    return x + w / 2, y + h / 2


def _bbox_distance(a: BBox, b: BBox) -> float:
    ax, ay = _centroid(a)
    bx, by = _centroid(b)
    return math.hypot(ax - bx, ay - by)


def _face_overlaps_bbox(faces, bbox: BBox) -> bool:
    """Loose containment check (expanded by 50% on each side) — a face
    detected near, not just exactly inside, the tracked region is enough
    to call it "someone standing there", since a person's face sits above
    where their hands/body would be relative to an object they're next
    to."""
    x, y, w, h = bbox
    x_min, x_max = x - w * 0.5, x + w * 1.5
    y_min, y_max = y - h * 0.5, y + h * 1.5
    for face in faces:
        fx1, fy1, fx2, fy2 = face.bbox
        fx, fy = (fx1 + fx2) / 2, (fy1 + fy2) / 2
        if x_min <= fx <= x_max and y_min <= fy <= y_max:
            return True
    return False


def _update_tracking(camera_id: str, mask: np.ndarray, faces) -> _TrackedRegion | None:
    """Mutates the module-level tracking state for camera_id. Returns the
    tracked region once it has reached abandoned_object_min_consecutive_
    ticks, else None."""
    candidate = _largest_static_candidate(mask)
    current = _tracked_regions.get(camera_id)

    if candidate is None:
        _tracked_regions[camera_id] = None
        return None

    if _face_overlaps_bbox(faces, candidate):
        _tracked_regions[camera_id] = None  # someone's standing there — not an abandoned object
        return None

    if current is not None and _bbox_distance(current.bbox, candidate) <= settings.abandoned_object_match_distance_px:
        current.bbox = candidate
        current.consecutive_ticks += 1
    else:
        current = _TrackedRegion(bbox=candidate)

    _tracked_regions[camera_id] = current

    if current.consecutive_ticks >= settings.abandoned_object_min_consecutive_ticks:
        return current
    return None


async def _recently_flagged(db: AsyncSession, camera_id) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.abandoned_object_dedup_minutes)
    result = await db.execute(
        select(Event.id)
        .where(Event.module_code == ABANDONED_MODULE_CODE)
        .where(Event.camera_id == camera_id)
        .where(Event.occurred_at >= cutoff)
    )
    return result.scalar_one_or_none() is not None


async def process_camera_frame_for_abandoned_object(frame_bytes: bytes, db: AsyncSession, camera: Camera) -> bool:
    """Returns True if a (deduped) abandoned-object Event was raised."""
    arr = np.frombuffer(frame_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return False

    faces = await detect_faces(frame_bytes)

    camera_id = str(camera.id)
    subtractor = _get_subtractor(camera_id)
    mask = subtractor.apply(img, learningRate=settings.abandoned_object_learning_rate)
    _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))

    region = _update_tracking(camera_id, mask, faces)
    if region is None:
        return False

    if await _recently_flagged(db, camera.id):
        return False

    event = Event(
        camera_id=camera.id,
        camera_name=camera.name,
        building=camera.building.name if camera.building else "",
        module_code=ABANDONED_MODULE_CODE,
        module_name=ABANDONED_MODULE_NAME,
        group="A",
        confidence=55,  # classical background-subtraction heuristic, not validated against real footage — see module docstring
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
    _tracked_regions[camera_id] = None  # reset so it doesn't keep counting past the threshold every tick
    return True


async def run_abandoned_object_ai_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """Grabs one frame from every reachable 'faol' camera and updates its
    background-subtraction tracking — cameras run concurrently (bounded
    by _camera_semaphore). See app/jobs/attendance_ai.py's
    run_attendance_ai_sweep_once, which this mirrors. Returns how many
    abandoned-object Events were raised."""
    async with session_factory() as db:
        if not await is_module_active(db, ABANDONED_MODULE_CODE):
            return 0
        result = await db.execute(
            select(Camera).where(Camera.status == "faol").where(camera_allows_module(ABANDONED_MODULE_CODE))
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
                return await process_camera_frame_for_abandoned_object(frame, camera_db, camera)

    results = await asyncio.gather(*(_process_one(camera) for camera in cameras), return_exceptions=True)

    total = 0
    for camera, result in zip(cameras, results, strict=True):
        if isinstance(result, BaseException):
            logger.exception(
                "abandoned object camera task failed", extra={"camera_id": str(camera.id)}, exc_info=result
            )
            continue
        if result:
            total += 1
    return total


async def abandoned_object_ai_loop() -> None:
    while True:
        try:
            count = await _sweep_guard.run(run_abandoned_object_ai_sweep_once)
            if count:
                logger.warning("abandoned object AI sweep raised events", extra={"events": count})
        except Exception:
            logger.exception("abandoned object AI sweep failed")
        await asyncio.sleep(settings.abandoned_object_ai_interval_seconds)
