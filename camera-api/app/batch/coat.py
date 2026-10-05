"""Oq xalat (#10): tanilgan odamning tana sohasi oqmi.

Bitta kadrdagi rang — zaif dalil (oq devor, yorug'lik, oq ko'ylak). Shuning
uchun bu yerda faqat BITTA namunani baholash bor; qaror kun bo'yi ko'p
namunadan ovoz berish bilan chiqariladi (`day_verdict`):

  1. Soha: yuz ostidan (bo'yin tashlab) ko'krak-qorin, eni yelkalar kengligi.
     YOLO odam ramkasi bo'lsa soha shu ramka bilan kesiladi — orqadagi oq
     devor hisobga kirmaydi.
  2. Yorug'lik tuzatish: kadrdagi eng yorqin neytral piksellar bo'yicha
     kanallar kuchaytiriladi (sariq lampa ostida oq xalat sarg'ish
     ko'rinadi).
  3. Lab fazosida "oq" piksel: yorug'lik kadrning o'rtachasidan yuqori va
     rang (xroma) past. Soha piksellarining oq ulushi — namunaning qiymati.

Ixtiyoriy: `settings.coat_model_path` — o'qitilgan YOLO klassifikatori
(sinflar: oq_xalat / boshqa). Berilsa rang qoidasi o'rniga ishlatiladi.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import cv2
import numpy as np

from app.config import settings

logger = logging.getLogger("app.batch.coat")

# Soha yuz o'lchamiga nisbatan (yuz balandligi = 1).
ROI_TOP = 0.35
ROI_BOTTOM = 2.6
ROI_HALF_WIDTH = 1.3
MIN_VISIBLE = 0.5

COAT_YES = "kiygan"
COAT_NO = "kiymagan"
COAT_UNKNOWN = "aniqlanmadi"
COAT_NOT_REQUIRED = "talab_yoq"


@dataclass(frozen=True)
class CoatSample:
    fraction: float  # oq piksellar ulushi (0..1) yoki model ehtimoli
    is_white: bool | None  # None — noaniq (ovozga kirmaydi)


def torso_roi(
    face_bbox, frame_shape: tuple[int, int], person_bbox=None
) -> tuple[int, int, int, int] | None:
    """(x1, y1, x2, y2) — yoki None (soha kadrdan chiqib ketgan / juda kichik)."""
    height, width = frame_shape[:2]
    x1, y1, x2, y2 = (float(v) for v in face_bbox[:4])
    fw, fh = x2 - x1, y2 - y1
    if fw <= 0 or fh <= 0:
        return None
    cx = (x1 + x2) / 2
    nominal = (cx - ROI_HALF_WIDTH * fw, y2 + ROI_TOP * fh, cx + ROI_HALF_WIDTH * fw, y2 + ROI_BOTTOM * fh)
    nominal_area = (nominal[2] - nominal[0]) * (nominal[3] - nominal[1])
    left, top, right, bottom = nominal
    if person_bbox is not None:
        px1, py1, px2, py2 = (float(v) for v in person_bbox[:4])
        left, top, right, bottom = max(left, px1), max(top, py1), min(right, px2), min(bottom, py2)
    left, top = max(0.0, left), max(0.0, top)
    right, bottom = min(float(width), right), min(float(height), bottom)
    if right - left < 4 or bottom - top < 4:
        return None
    if (right - left) * (bottom - top) < MIN_VISIBLE * nominal_area * (0.6 if person_bbox is not None else 1.0):
        return None
    return int(left), int(top), int(right), int(bottom)


def white_balance_gains(image_bgr: np.ndarray) -> np.ndarray:
    """Kadrdagi eng yorqin 2% pikselning o'rtacha rangi neytral (kulrang)
    bo'lishi uchun kanal kuchaytirgichlari. Juda rangli sahnada (yorqin
    piksellar o'zi rangli) kuchaytirish cheklanadi."""
    small = cv2.resize(image_bgr, (160, max(1, int(160 * image_bgr.shape[0] / max(1, image_bgr.shape[1])))))
    pixels = small.reshape(-1, 3).astype(np.float32)
    luminance = pixels.mean(axis=1)
    threshold = np.percentile(luminance, 98)
    bright = pixels[luminance >= threshold]
    if len(bright) == 0:
        return np.ones(3, dtype=np.float32)
    mean = bright.mean(axis=0)
    gains = mean.mean() / np.maximum(mean, 1.0)
    return np.clip(gains, 0.75, 1.33).astype(np.float32)


def white_fraction(roi_bgr: np.ndarray, gains: np.ndarray, frame_lightness: float) -> float:
    if roi_bgr.size == 0:
        return 0.0
    balanced = np.clip(roi_bgr.astype(np.float32) * gains, 0, 255).astype(np.uint8)
    lab = cv2.cvtColor(balanced, cv2.COLOR_BGR2LAB).astype(np.float32)
    lightness = lab[..., 0]
    chroma = np.hypot(lab[..., 1] - 128.0, lab[..., 2] - 128.0)
    # Oq: kadrning yorqin choragiga kiradi VA mutlaq ma'noda yorug' VA
    # rangsiz. Nisbiy chegara xira xonada ham, yorug' koridorda ham ishlaydi.
    light_floor = max(125.0, min(200.0, frame_lightness))
    white = (lightness >= light_floor) & (chroma <= 16.0)
    return float(white.mean())


def frame_lightness(image_bgr: np.ndarray) -> float:
    """Kadr yorqinligining 75-persentili (Lab L, 0-255)."""
    small = cv2.resize(image_bgr, (96, max(1, int(96 * image_bgr.shape[0] / max(1, image_bgr.shape[1])))))
    return float(np.percentile(cv2.cvtColor(small, cv2.COLOR_BGR2LAB)[..., 0], 75))


def classify_fraction(fraction: float) -> bool | None:
    if fraction >= settings.coat_white_fraction:
        return True
    if fraction <= settings.coat_dark_fraction:
        return False
    return None


_model_lock = threading.Lock()
_model_state: dict[str, object] = {}


def _coat_model():
    path = settings.coat_model_path.strip()
    if not path:
        return None
    with _model_lock:
        if _model_state.get("path") != path:
            try:
                from ultralytics import YOLO

                _model_state["model"] = YOLO(path)
            except Exception:  # noqa: BLE001 — model bo'lmasa rang qoidasi
                logger.exception("coat classifier could not be loaded", extra={"path": path})
                _model_state["model"] = None
            _model_state["path"] = path
        return _model_state["model"]


def _model_white_probability(model, crop_bgr: np.ndarray) -> float | None:
    try:
        result = model.predict(crop_bgr, verbose=False)[0]
        names = {int(k): str(v).lower() for k, v in result.names.items()}
        probs = result.probs.data.cpu().numpy() if hasattr(result.probs.data, "cpu") else np.asarray(result.probs.data)
    except Exception:  # noqa: BLE001
        logger.exception("coat classifier failed")
        return None
    for index, name in names.items():
        if "xalat" in name or "coat" in name or name in ("oq", "white"):
            return float(probs[index])
    return None


def evaluate(image_bgr: np.ndarray, face_bbox, person_bbox=None, context: tuple | None = None) -> CoatSample | None:
    """Bitta yuz uchun bitta namuna. `context` — (gains, lightness) bir
    kadrdagi bir nechta yuz uchun qayta hisoblanmasin."""
    roi = torso_roi(face_bbox, image_bgr.shape, person_bbox)
    if roi is None:
        return None
    x1, y1, x2, y2 = roi
    crop = image_bgr[y1:y2, x1:x2]
    model = _coat_model()
    if model is not None:
        probability = _model_white_probability(model, crop)
        if probability is not None:
            if probability >= 0.6:
                return CoatSample(probability, True)
            if probability <= 0.4:
                return CoatSample(probability, False)
            return CoatSample(probability, None)
    gains, lightness = context if context is not None else (white_balance_gains(image_bgr), frame_lightness(image_bgr))
    fraction = white_fraction(crop, gains, lightness)
    return CoatSample(fraction, classify_fraction(fraction))


def frame_context(image_bgr: np.ndarray) -> tuple[np.ndarray, float]:
    return white_balance_gains(image_bgr), frame_lightness(image_bgr)


def observation_vote(white_frames: int, judged_frames: int) -> bool | None:
    """Bitta kuzatuv (bir klipdagi bir odam) — kadrlarining ko'pchiligi."""
    if judged_frames <= 0:
        return None
    if white_frames * 2 > judged_frames:
        return True
    if white_frames * 2 < judged_frames:
        return False
    return None


def day_verdict(votes: list[bool], required: bool) -> str:
    """Kun bo'yicha: kamida coat_min_samples ta aniq kuzatuv (alohida
    kliplar) kerak; oq ulushi coat_ok_ratio dan yuqori — kiygan,
    coat_violation_ratio dan past — kiymagan, oralig'i — aniqlanmadi."""
    if not required:
        return COAT_NOT_REQUIRED
    if len(votes) < settings.coat_min_samples:
        return COAT_UNKNOWN
    ratio = sum(1 for vote in votes if vote) / len(votes)
    if ratio >= settings.coat_ok_ratio:
        return COAT_YES
    if ratio <= settings.coat_violation_ratio:
        return COAT_NO
    return COAT_UNKNOWN


def coat_required(person_type: str | None, position: str | None, group_or_position: str | None = None) -> bool:
    types = {t.strip() for t in settings.coat_required_types.split(",") if t.strip()}
    if person_type in types:
        return True
    if person_type != "xodim":
        return False
    text = f"{position or ''} {group_or_position or ''}".lower().replace("‘", "'").replace("ʻ", "'")
    keywords = [k.strip().lower() for k in settings.coat_required_positions.split(",") if k.strip()]
    return any(keyword in text for keyword in keywords)
