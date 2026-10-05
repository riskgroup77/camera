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
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import cv2
import numpy as np
from ultralytics import YOLO

from app.config import settings
from app.services.inference_cache import inference_cache

logger = logging.getLogger("app.object_detection")

_inference_semaphore = asyncio.Semaphore(settings.object_detection_inference_concurrency)

# Ultralytics bitta YOLO obyektini bir nechta oqimda birga ishlatishni
# xavfsiz deb hisoblamaydi (predictor holati umumiy). Shuning uchun
# inference o'z kichik havzasida ishlaydi va HAR BIR oqim modelning o'z
# nusxasiga ega. Havza hajmi = bir vaqtdagi chaqiruvlar chegarasi, ya'ni
# nusxalar soni ham shu bilan cheklangan.
_thread_models = threading.local()
_model_load_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None


def _get_model() -> YOLO:
    model = getattr(_thread_models, "model", None)
    if model is None:
        # Birinchi yuklash (kerak bo'lsa vazn faylini yuklab olish ham) bir
        # vaqtda bitta oqimda — aks holda bir nechta oqim bitta faylga yozardi.
        with _model_load_lock:
            logger.info(
                "loading YOLO object detection model for a worker thread",
                extra={"model": settings.object_detection_model_path, "gpu_enabled": settings.object_detection_gpu_enabled},
            )
            model = YOLO(settings.object_detection_model_path)
        _thread_models.model = model
    return model


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=max(1, settings.object_detection_inference_concurrency),
            thread_name_prefix="yolo-object",
        )
    return _executor


async def _run_inference(func, *args):
    return await asyncio.get_running_loop().run_in_executor(_get_executor(), func, *args)


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


def _decode_image(image_bytes: bytes):
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _detect_batch_sync(
    images: list[bytes], class_ids: list[int], confidence: float
) -> list[list[DetectedObject]]:
    decoded = [_decode_image(b) for b in images]
    valid_indices = [i for i, img in enumerate(decoded) if img is not None]
    if not valid_indices:
        return [[] for _ in images]

    imgs = [decoded[i] for i in valid_indices]
    model = _get_model()
    device = 0 if settings.object_detection_gpu_enabled else "cpu"
    batch_size = max(1, settings.object_detection_batch_size)
    per_image: list[list[DetectedObject]] = [[] for _ in images]

    for start in range(0, len(imgs), batch_size):
        chunk = imgs[start : start + batch_size]
        chunk_indices = valid_indices[start : start + batch_size]
        results = model.predict(chunk, classes=class_ids, conf=confidence, device=device, verbose=False)
        for idx, result in zip(chunk_indices, results, strict=True):
            names = result.names
            detections: list[DetectedObject] = []
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
            per_image[idx] = detections
    return per_image


async def detect_objects(image_bytes: bytes, class_ids: list[int], confidence: float = 0.5) -> list[DetectedObject]:
    """Runs on a worker thread — YOLO inference is CPU/GPU-bound and
    synchronous, same rationale as face_recognition.detect_faces(). Gated
    by _inference_semaphore — see its docstring. `class_ids` restricts
    detection to specific COCO classes (e.g. [67] for cell phone only)
    rather than running full 80-class detection when a caller only cares
    about one or two kinds of object — cheaper and avoids irrelevant
    matches entirely, not just filtering them out after the fact."""
    async def run() -> list[DetectedObject]:
        async with _inference_semaphore:
            return await _run_inference(_detect_sync, image_bytes, class_ids, confidence)

    # Bir xil kadr va sinflar — bir marta (app/services/inference_cache.py).
    return await inference_cache.get_or_run(image_bytes, ("objects", tuple(class_ids), confidence), run)


async def detect_objects_batch(
    image_bytes_list: list[bytes], class_ids: list[int], confidence: float = 0.5
) -> list[list[DetectedObject]]:
    """YOLO batch predict — chunks by object_detection_batch_size."""
    if not image_bytes_list:
        return []
    async with _inference_semaphore:
        return await _run_inference(_detect_batch_sync, image_bytes_list, class_ids, confidence)
