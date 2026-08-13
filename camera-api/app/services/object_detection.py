"""YOLOv8 (Ultralytics, COCO-pretrained) object detection — the general-
purpose counterpart to app/services/face_recognition.py's InsightFace
pipeline, for AI criteria that need to recognize specific OBJECT CLASSES
(a phone, a vehicle) rather than faces.

Uses the stock COCO-pretrained yolov8n.pt weights — no custom training,
which means it only ever recognizes COCO's 80 built-in classes. Checked
directly against this exact model before writing any criterion against
it (not assumed): COCO has "cell phone" (67) and vehicle classes
(car=2, motorcycle=3, bus=5, truck=7, bicycle=1), but NO hat/helmet or
mask/glove classes — criteria needing those (TT 11, 13) would need a
custom-trained model this module does not provide, and are out of scope
here for exactly that reason.

Loaded once, shared across every caller (module-level singleton, like
face_recognition.py's InsightFace app) — re-loading YOLO per call would
be wasteful. Same concurrency-limiting rationale as
face_recognition._inference_semaphore: CPU/GPU inference is the real
resource being shared across concurrent sweep loops.
"""

import asyncio
import logging
from dataclasses import dataclass

import cv2
import numpy as np
from ultralytics import YOLO

from app.config import settings

logger = logging.getLogger("app.object_detection")

_model: YOLO | None = None
_inference_semaphore = asyncio.Semaphore(settings.object_detection_inference_concurrency)


def _get_model() -> YOLO:
    global _model
    if _model is None:
        logger.info(
            "loading YOLO object detection model (first use)",
            extra={"model": settings.object_detection_model_path, "gpu_enabled": settings.object_detection_gpu_enabled},
        )
        _model = YOLO(settings.object_detection_model_path)
    return _model


@dataclass
class DetectedObject:
    class_id: int
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 in the source image's pixel coordinates


def _detect_sync(image_bytes: bytes, class_ids: list[int], confidence: float) -> list[DetectedObject]:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return []

    model = _get_model()
    device = 0 if settings.object_detection_gpu_enabled else "cpu"
    results = model.predict(img, classes=class_ids, conf=confidence, device=device, verbose=False)

    detections: list[DetectedObject] = []
    for result in results:
        names = result.names
        for box in result.boxes:
            cls_id = int(box.cls[0])
            detections.append(
                DetectedObject(
                    class_id=cls_id,
                    class_name=names.get(cls_id, str(cls_id)),
                    confidence=float(box.conf[0]),
                    bbox=tuple(float(v) for v in box.xyxy[0]),
                )
            )
    return detections


async def detect_objects(image_bytes: bytes, class_ids: list[int], confidence: float = 0.5) -> list[DetectedObject]:
    """Runs on a worker thread — YOLO inference is CPU/GPU-bound and
    synchronous, same rationale as face_recognition.detect_faces(). Gated
    by _inference_semaphore — see its docstring. `class_ids` restricts
    detection to specific COCO classes (e.g. [67] for cell phone only)
    rather than running full 80-class detection when a caller only cares
    about one or two kinds of object — cheaper and avoids irrelevant
    matches entirely, not just filtering them out after the fact."""
    async with _inference_semaphore:
        return await asyncio.to_thread(_detect_sync, image_bytes, class_ids, confidence)
