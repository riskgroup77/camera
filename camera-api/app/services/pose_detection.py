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

Loaded once, shared across every caller (module-level singleton, same
pattern as face_recognition.py's InsightFace app and
object_detection.py's YOLO model). Same concurrency-limiting rationale as
face_recognition._inference_semaphore.
"""

import asyncio
import logging
from dataclasses import dataclass

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode

from app.config import settings

logger = logging.getLogger("app.pose_detection")

NOSE = 0
LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_HIP, RIGHT_HIP = 23, 24
LEFT_KNEE, RIGHT_KNEE = 25, 26
LEFT_ANKLE, RIGHT_ANKLE = 27, 28
LEFT_WRIST, RIGHT_WRIST = 15, 16

_landmarker: PoseLandmarker | None = None
_inference_semaphore = asyncio.Semaphore(settings.pose_detection_inference_concurrency)


def _get_landmarker() -> PoseLandmarker:
    global _landmarker
    if _landmarker is None:
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


async def detect_poses(image_bytes: bytes) -> list[PoseLandmarks]:
    """Runs on a worker thread — pose inference is CPU/GPU-bound and
    synchronous, same rationale as face_recognition.detect_faces() and
    object_detection.detect_objects(). Gated by _inference_semaphore —
    see its docstring. Returns up to settings.pose_detection_max_poses
    poses, ordered however mediapipe returns them (not guaranteed to be
    left-to-right or by confidence)."""
    async with _inference_semaphore:
        return await asyncio.to_thread(_detect_sync, image_bytes)
