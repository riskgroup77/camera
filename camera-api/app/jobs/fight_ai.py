"""TT kriteriya 14 ("Jang/nizolashish holati") — THE LEAST RELIABLE
criterion in this system, and flagged more heavily than any other for
exactly that reason.

Combines two signals that are each individually weak — multiple detected
people in close proximity, AND unusually high motion between two frames
(reusing app/jobs/disorder_ai.py's own per-camera motion-anomaly
baseline/spike logic directly, under a namespaced key so this doesn't
share or distort disorder_ai's own "normal motion" baseline for
kriteriya 17) — since neither means anything alone: people stand close
together constantly without fighting, and high motion happens during
completely ordinary activity (walking quickly, celebrating, a crowd
moving through a hallway). Together they're still only a weak proxy for
"something physically eventful might be happening here", not a
validated fight/altercation detector.

TT's own registry entry for this criterion names "Action recognition
(pose + optical flow)" as the intended method. Pose and optical flow ARE
what's used here, but that alone — without a model actually trained to
distinguish a fight's specific movement pattern from other high-motion
group activity (sports, celebration, a crowd hurrying somewhere) — is
not the same thing as a validated action-recognition classifier. This
has NOT been tested against any real altercation footage (none was
available in this environment — the same honest limitation
app/services/fire_detection.py's module docstring already discloses for
fire detection). Unlike fire detection, this criterion's expected
false-positive rate against ordinary energetic group activity is
substantial and entirely unmeasured.

Raised at deliberately LOW confidence (well below every other Event this
system raises) specifically so it reads, correctly, as "worth a human
glancing at this camera" rather than "confirmed altercation". If real
fight/altercation footage ever becomes available to validate or retune
this, that should happen before this criterion is trusted for anything
more than that.
"""

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.jobs.camera_health import is_reachable
from app.jobs.module_status import camera_allows_module, is_module_active
from app.jobs.sweep_guard import SweepGuard
from app.jobs.sweep_concurrency import camera_sweep_slot
from app.jobs.disorder_ai import _decode_grayscale, _is_motion_spike, _mean_flow_magnitude
from app.models import Camera, Event
from app.services.event_bus import raise_event
from app.services.frame_grabber import grab_frame_pair_for_camera
from app.services.pose_detection import LEFT_HIP, NOSE, RIGHT_HIP, detect_poses

logger = logging.getLogger("app.fight_ai")

FIGHT_MODULE_CODE = 14
FIGHT_MODULE_NAME = "Jang/nizolashish holati"

# See app/jobs/attendance_ai.py's _camera_semaphore docstring — same
# rationale, own semaphore so this job can't starve (or be starved by)
# the other AI sweep loops' camera slots.
_sweep_guard = SweepGuard("fight_ai")


def _person_center(points) -> tuple[float, float] | None:
    if points[LEFT_HIP][3] >= settings.fight_min_landmark_visibility and points[RIGHT_HIP][3] >= settings.fight_min_landmark_visibility:
        return float((points[LEFT_HIP][0] + points[RIGHT_HIP][0]) / 2), float((points[LEFT_HIP][1] + points[RIGHT_HIP][1]) / 2)
    if points[NOSE][3] >= settings.fight_min_landmark_visibility:
        return float(points[NOSE][0]), float(points[NOSE][1])
    return None


def _people_in_close_proximity(poses) -> bool:
    """True if at least two detected people's centers are within
    settings.fight_proximity_threshold of each other (normalized 0-1
    coordinates)."""
    centers = [c for pose in poses if (c := _person_center(pose.points)) is not None]
    for i in range(len(centers)):
        for j in range(i + 1, len(centers)):
            dx = centers[i][0] - centers[j][0]
            dy = centers[i][1] - centers[j][1]
            if math.hypot(dx, dy) <= settings.fight_proximity_threshold:
                return True
    return False


async def _recently_flagged(db: AsyncSession, camera_id) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.fight_dedup_minutes)
    result = await db.execute(
        select(Event.id)
        .where(Event.module_code == FIGHT_MODULE_CODE)
        .where(Event.camera_id == camera_id)
        .where(Event.occurred_at >= cutoff)
    )
    return result.scalar_one_or_none() is not None


async def process_camera_frame_pair_for_fight(frame_a: bytes, frame_b: bytes, db: AsyncSession, camera: Camera) -> bool:
    """Returns True if a (deduped) fight/altercation Event was raised —
    see the module docstring for how weak a signal this actually is."""
    poses_b = await detect_poses(frame_b)
    if len(poses_b) < 2 or not _people_in_close_proximity(poses_b):
        return False

    img_a = _decode_grayscale(frame_a)
    img_b = _decode_grayscale(frame_b)
    if img_a is None or img_b is None or img_a.shape != img_b.shape:
        return False

    magnitude = _mean_flow_magnitude(img_a, img_b)
    # Namespaced key ("...:fight") so this doesn't share (and distort)
    # app/jobs/disorder_ai.py's own per-camera "normal motion" baseline
    # for kriteriya 17 — the two criteria may reasonably want different
    # sensitivity even on the same camera.
    if not _is_motion_spike(
        f"{camera.id}:fight",
        magnitude,
        spike_multiplier=settings.fight_spike_multiplier,
        min_absolute_magnitude=settings.fight_min_absolute_magnitude,
    ):
        return False

    if await _recently_flagged(db, camera.id):
        return False

    await raise_event(
        db,
        camera=camera,
        module_code=FIGHT_MODULE_CODE,
        module_name=FIGHT_MODULE_NAME,
        group="D",
        confidence=35,  # deliberately the lowest confidence this system raises — see module docstring
        severity="yuqori",  # still worth a human look despite the low confidence — a missed real fight is worse than a false alarm
        frame_bytes=frame_b,
    )
    return True


async def run_fight_ai_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """Grabs a frame pair from every reachable 'faol' camera and checks
    it for the proximity+motion combination — cameras run concurrently
    (bounded by _camera_semaphore). See app/jobs/attendance_ai.py's
    run_attendance_ai_sweep_once, which this mirrors. Returns how many
    fight Events were raised."""
    async with session_factory() as db:
        if not await is_module_active(db, FIGHT_MODULE_CODE):
            return 0
        result = await db.execute(
            select(Camera).where(Camera.status == "faol").where(camera_allows_module(FIGHT_MODULE_CODE))
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
                return await process_camera_frame_pair_for_fight(frame_a, frame_b, camera_db, camera)

    results = await asyncio.gather(*(_process_one(camera) for camera in cameras), return_exceptions=True)

    total = 0
    for camera, result in zip(cameras, results, strict=True):
        if isinstance(result, BaseException):
            logger.exception("fight camera task failed", extra={"camera_id": str(camera.id)}, exc_info=result)
            continue
        if result:
            total += 1
    return total


async def fight_ai_loop() -> None:
    while True:
        try:
            count = await _sweep_guard.run(run_fight_ai_sweep_once)
            if count:
                logger.warning("fight AI sweep raised events", extra={"events": count})
        except Exception:
            logger.exception("fight AI sweep failed")
        await asyncio.sleep(settings.fight_ai_interval_seconds)
