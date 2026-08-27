"""TT kriteriya 13 — SIZ (niqob/qo'lqop) taxminiy tekshiruv.

Asosiy yo'l: ixtiyoriy custom YOLO og'irliklari (PPE_DETECTION_MODEL_PATH).
Zaxira: yuz pastki qismida teri-dan farq qiluvchi yuqori to'yinganlik
(masalan ko'k niqob) — haqiqiy PPE modeli emas.
"""

import asyncio
import logging
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

from app.config import settings

logger = logging.getLogger("app.ppe_detection")

_ppe_model: YOLO | None = None


def _get_ppe_model() -> YOLO | None:
    global _ppe_model
    path = (settings.ppe_detection_model_path or "").strip()
    if not path:
        return None
    if _ppe_model is None:
        if not Path(path).exists():
            logger.warning("PPE model path not found", extra={"path": path})
            return None
        _ppe_model = YOLO(path)
    return _ppe_model


def _mask_heuristic(image: np.ndarray, face_bbox: tuple[float, float, float, float]) -> bool:
    """Lower-face region: significant non-skin saturated pixels suggest mask."""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = face_bbox
    fx1, fy1 = int(x1), int(y1 + (y2 - y1) * 0.45)
    fx2, fy2 = int(x2), int(y2)
    fx1, fy1 = max(0, fx1), max(0, fy1)
    fx2, fy2 = min(w, fx2), min(h, fy2)
    crop = image[fy1:fy2, fx1:fx2]
    if crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    sat, val = hsv[:, :, 1], hsv[:, :, 2]
    mask_like = (sat >= settings.ppe_mask_saturation_min) & (val >= settings.ppe_mask_value_min)
    frac = float(np.count_nonzero(mask_like)) / float(mask_like.size)
    return frac >= settings.ppe_mask_fraction_threshold


def detect_ppe_sync(image: np.ndarray, face_bbox: tuple[float, float, float, float]) -> bool:
    model = _get_ppe_model()
    if model is not None:
        device = 0 if settings.object_detection_gpu_enabled else "cpu"
        results = model.predict(image, conf=settings.ppe_detection_confidence, device=device, verbose=False)
        for result in results:
            if len(result.boxes) > 0:
                return True
        return False
    return _mask_heuristic(image, face_bbox)


async def detect_ppe(image: np.ndarray, face_bbox: tuple[float, float, float, float]) -> bool:
    """Run PPE inference off the event loop — YOLO/cv2 must not block asyncio."""
    return await asyncio.to_thread(detect_ppe_sync, image, face_bbox)
