"""TT kriteriya 17 ("Tartib-intizom buzilishi") — flags unusually large
frame-to-frame motion (running, chaotic movement) relative to a camera's
OWN recent baseline, using dense optical flow (Farneback — classical CV,
already available via opencv-python-headless; no pose-estimation model
needed for this one).

Same "anomaly relative to the camera's own history" design as
app/jobs/crowd_density_ai.py, for the same reason: a busy stairwell's
normal foot-traffic motion and a quiet reading room's normal stillness
need different absolute thresholds to both be usable — comparing each
camera against its own recent average is what makes one threshold
formula work across very different locations.

Grabs a PAIR of frames (grab_frame_pair, ~1s apart — the same pattern
app/jobs/fire_ai.py and app/jobs/unauthorized_person_ai.py use) and
computes the mean optical-flow magnitude across the whole frame between
them. Real calibration numbers from actual OpenCV runs (not assumed —
see tests/test_disorder_ai.py): two identical frames read as ~0.0003
(including real JPEG-encode/decode round-trip noise, ~0.0006), while a
frame shifted by 5-10px reads 5-10. settings.disorder_min_absolute_
magnitude and the baseline comparison are calibrated against these real
numbers, not guessed.

Honest scope note: this is a GLOBAL average over the whole frame, not
per-person motion — a single person sprinting across an otherwise empty,
mostly-static frame moves the average much less than the same sprint
would in a frame already full of moving people (their motion partially
averages out against the sprinter's). It also can't distinguish
"deliberately fast/aggressive" from "several people walking normally at
once" — both raise the frame's average motion. This is a coarse
whole-scene anomaly signal, not validated against real footage of actual
disorderly conduct, only synthetic shifted-frame test cases.
"""

import asyncio
import logging
from collections import defaultdict, deque
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
from app.services.event_bus import raise_event
from app.services.frame_grabber import grab_frame_pair

logger = logging.getLogger("app.disorder_ai")

DISORDER_MODULE_CODE = 17
DISORDER_MODULE_NAME = "Tartib-intizom buzilishi"

# See app/jobs/attendance_ai.py's _camera_semaphore docstring — same
# rationale, own semaphore so this job can't starve (or be starved by)
# the other AI sweep loops' camera slots.
_sweep_guard = SweepGuard("disorder_ai")

# Per-camera rolling history of recent flow magnitudes — see
# app/jobs/crowd_density_ai.py's _face_count_history for the identical
# pattern and the same in-memory/not-persisted tradeoff.
_motion_history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=settings.disorder_baseline_window))


def _decode_grayscale(frame_bytes: bytes) -> np.ndarray | None:
    arr = np.frombuffer(frame_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)


def _mean_flow_magnitude(frame_a: np.ndarray, frame_b: np.ndarray) -> float:
    flow = cv2.calcOpticalFlowFarneback(frame_a, frame_b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    magnitude, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
    return float(np.mean(magnitude))


def _is_motion_spike(
    camera_id: str,
    magnitude: float,
    *,
    spike_multiplier: float | None = None,
    min_absolute_magnitude: float | None = None,
) -> bool:
    """Same update-then-decide contract as app/jobs/crowd_density_ai.py's
    _is_spike — updates camera_id's rolling history as a side effect
    regardless of the outcome, and judges against the history BEFORE this
    call."""
    mult = spike_multiplier if spike_multiplier is not None else settings.disorder_spike_multiplier
    min_abs = min_absolute_magnitude if min_absolute_magnitude is not None else settings.disorder_min_absolute_magnitude
    history = _motion_history[camera_id]
    is_spike = False
    if len(history) >= settings.disorder_baseline_min_samples:
        baseline = sum(history) / len(history)
        threshold = max(min_abs, baseline * mult)
        is_spike = magnitude >= threshold
    history.append(magnitude)
    return is_spike


def reset_motion_history_for_tests() -> None:
    """Tests only — motion baselines must not leak between test cases."""
    _motion_history.clear()


async def _recently_flagged(db: AsyncSession, camera_id) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.disorder_dedup_minutes)
    result = await db.execute(
        select(Event.id)
        .where(Event.module_code == DISORDER_MODULE_CODE)
        .where(Event.camera_id == camera_id)
        .where(Event.occurred_at >= cutoff)
    )
    return result.scalar_one_or_none() is not None


async def process_camera_frame_pair_for_disorder(
    frame_a: bytes, frame_b: bytes, db: AsyncSession, camera: Camera
) -> bool:
    """Returns True if a (deduped) disorder/motion-anomaly Event was
    raised."""
    img_a = _decode_grayscale(frame_a)
    img_b = _decode_grayscale(frame_b)
    if img_a is None or img_b is None or img_a.shape != img_b.shape:
        return False

    magnitude = _mean_flow_magnitude(img_a, img_b)
    if not _is_motion_spike(str(camera.id), magnitude):
        return False

    if await _recently_flagged(db, camera.id):
        return False

    await raise_event(
        db,
        camera=camera,
        module_code=DISORDER_MODULE_CODE,
        module_name=DISORDER_MODULE_NAME,
        group="D",
        confidence=55,  # a coarse whole-frame motion heuristic, not validated against real footage — see module docstring
        severity="past",
        frame_bytes=frame_b,
    )
    return True


async def run_disorder_ai_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """Grabs a frame pair from every reachable 'faol' camera and checks
    its motion magnitude against that camera's own rolling baseline —
    cameras run concurrently (bounded by _camera_semaphore). See
    app/jobs/attendance_ai.py's run_attendance_ai_sweep_once, which this
    mirrors. Returns how many disorder Events were raised."""
    async with session_factory() as db:
        if not await is_module_active(db, DISORDER_MODULE_CODE):
            return 0
        result = await db.execute(
            select(Camera).where(Camera.status == "faol").where(camera_allows_module(DISORDER_MODULE_CODE))
        )
        cameras = [c for c in result.scalars().all() if c.stream_url and is_reachable(c.last_seen_at)]

    if not cameras:
        return 0

    async def _process_one(camera: Camera) -> bool:
        async with camera_sweep_slot():
            frames = await grab_frame_pair(camera.stream_url)
            if frames is None:
                return False
            frame_a, frame_b = frames
            async with session_factory() as camera_db:
                return await process_camera_frame_pair_for_disorder(frame_a, frame_b, camera_db, camera)

    results = await asyncio.gather(*(_process_one(camera) for camera in cameras), return_exceptions=True)

    total = 0
    for camera, result in zip(cameras, results, strict=True):
        if isinstance(result, BaseException):
            logger.exception("disorder camera task failed", extra={"camera_id": str(camera.id)}, exc_info=result)
            continue
        if result:
            total += 1
    return total


async def disorder_ai_loop() -> None:
    while True:
        try:
            count = await _sweep_guard.run(run_disorder_ai_sweep_once)
            if count:
                logger.warning("disorder AI sweep raised events", extra={"events": count})
        except Exception:
            logger.exception("disorder AI sweep failed")
        await asyncio.sleep(settings.disorder_ai_interval_seconds)
