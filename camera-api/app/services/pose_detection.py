"""mediapipe Pose Landmarker — full-body pose estimation (33 landmarks:
nose, shoulders, hips, knees, ankles, wrists, etc., each with normalized
x/y/z and a visibility score), the third detection backbone alongside
app/services/face_recognition.py (InsightFace, faces) and
app/services/object_detection.py (YOLOv8, generic objects). Used by AI
criteria that need body POSTURE/MOVEMENT rather than identity or object
class (TT kriteriya 24 fall detection, 2 zone entry, 21 teacher
activity).

Uses Google's official mediapipe model hub weights
(pose_landmarker_lite.task, ~5.5MB — the "lite" tier, chosen for CPU
inference speed over the "full"/"heavy" tiers' extra accuracy). Verified
directly against a real photo before writing any criterion against it
(not assumed) — see tests/test_pose_detection.py.

Landmark indices follow mediapipe's standard BlazePose 33-point topology
(not something invented here — the same numbering every mediapipe Pose
consumer uses): 0=nose, 11/12=left/right shoulder, 23/24=left/right hip,
25/26=left/right knee, 27/28=left/right ankle, 15/16=left/right wrist.

Loaded once per worker process (module-level singleton within that
process — see _get_landmarker), same pattern as face_recognition.py's
InsightFace app and object_detection.py's YOLO model. Same
concurrency-limiting rationale as face_recognition._inference_semaphore.

Runs in a dedicated ProcessPoolExecutor, NOT asyncio.to_thread like the
other two backbones. mediapipe's compiled .so has been observed to raise
a native SIGILL ("this binary was compiled with avx enabled, but this
feature is not available on this processor") on hardware lacking AVX —
a hardware fault, not a Python exception, that no try/except can catch,
and asyncio.to_thread shares this process's address space, so it would
kill the entire API (every request, every other AI sweep) instantly and
silently. A real OS subprocess boundary means that fault kills only the
one worker process; detect_poses() catches BrokenProcessPool, logs it,
and returns no poses for that call instead of taking the server down.
"""

import asyncio
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass

import numpy as np

from app.config import settings

logger = logging.getLogger("app.pose_detection")

NOSE = 0
LEFT_EAR, RIGHT_EAR = 7, 8
LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_HIP, RIGHT_HIP = 23, 24
LEFT_KNEE, RIGHT_KNEE = 25, 26
LEFT_ANKLE, RIGHT_ANKLE = 27, 28
LEFT_WRIST, RIGHT_WRIST = 15, 16

# cv2/mediapipe are imported lazily, inside the functions that actually run
# in the worker subprocess (see module docstring) — keeps the heavy native
# mediapipe .so out of the main API process's address space entirely; only
# the disposable worker process ever loads it.
_landmarker = None  # mediapipe.tasks.python.vision.PoseLandmarker, set inside the worker process
_inference_semaphore = asyncio.Semaphore(settings.pose_detection_inference_concurrency)
_pool: ProcessPoolExecutor | None = None


def _get_landmarker():
    global _landmarker
    if _landmarker is None:
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode

        logger.info(
            "loading mediapipe pose landmarker (first use)",
            extra={"model": settings.pose_detection_model_path},
        )
        options = PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=settings.pose_detection_model_path),
            running_mode=RunningMode.IMAGE,
            num_poses=settings.pose_detection_max_poses,
        )
        _landmarker = PoseLandmarker.create_from_options(options)
    return _landmarker


@dataclass
class PoseLandmarks:
    points: np.ndarray  # (33, 4) — columns: x, y (normalized 0-1 of frame width/height), z, visibility

    def visible(self, index: int, min_visibility: float) -> bool:
        return bool(self.points[index][3] >= min_visibility)


def _detect_sync(image_bytes: bytes) -> list[PoseLandmarks]:
    """Runs inside the dedicated worker subprocess (see _get_pool) — a
    native crash here (e.g. mediapipe's AVX SIGILL) takes down only this
    disposable process, never the API itself."""
    import cv2
    import mediapipe as mp

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return []

    landmarker = _get_landmarker()
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    result = landmarker.detect(mp_image)

    poses: list[PoseLandmarks] = []
    for pose in result.pose_landmarks:
        points = np.array([[lm.x, lm.y, lm.z, lm.visibility] for lm in pose])
        poses.append(PoseLandmarks(points=points))
    return poses


def _get_pool() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(
            max_workers=settings.pose_detection_inference_concurrency,
            mp_context=multiprocessing.get_context("spawn"),
        )
    return _pool


async def detect_poses(image_bytes: bytes) -> list[PoseLandmarks]:
    """Runs in a dedicated ProcessPoolExecutor — see module docstring for
    why this is a real OS process boundary rather than asyncio.to_thread.
    Gated by _inference_semaphore, same rationale as
    face_recognition.detect_faces(). Returns up to
    settings.pose_detection_max_poses poses, ordered however mediapipe
    returns them (not guaranteed to be left-to-right or by confidence).

    If the worker process was killed by a native fault, the whole pool is
    left broken by concurrent.futures; this is caught, logged once, and
    the pool is rebuilt fresh for the next call — callers just see "no
    poses" for the call that hit the crash, not an exception, and not a
    dead API."""
    async with _inference_semaphore:
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(_get_pool(), _detect_sync, image_bytes)
        except BrokenProcessPool:
            logger.error("pose detection worker crashed (native fault) — resetting pool")
            global _pool
            _pool = None
            return []


async def shutdown_pose_detection_pool() -> None:
    """Cleanly tears down the worker process(es) — called from main.py's
    lifespan teardown, same pattern as stream_cache.shutdown_stream_cache."""
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None
