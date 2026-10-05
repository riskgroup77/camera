"""Hodisa dalili: snapshot ustiga ramka va poligon chizish.

Operator "nega signal?" degan savolga kadrning o'zidan javob topishi
kerak: yuz yoki odam qayerda ekani ramkada ko'rinadi, taqiqlangan zona
chizig'i kadr ustida turadi. Chizish kadr omborga yozilishidan OLDIN bir
marta bajariladi (app/services/event_bus.py) — ko'rish paytida hech narsa
hisoblanmaydi."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger("app.evidence")

# BGR. To'q sariq ramka ko'k, yashil va qizil kiyim fonida ham ko'rinadi.
_BOX_COLOR = (0, 165, 255)
_ZONE_COLOR = (60, 60, 230)
_JPEG_QUALITY = 88


@dataclass(frozen=True)
class Box:
    """Ramka. normalized=True bo'lsa koordinatalar kadr eni/bo'yiga nisbatan (0..1)."""

    x1: float
    y1: float
    x2: float
    y2: float
    label: str = ""
    normalized: bool = False


@dataclass(frozen=True)
class Polygon:
    """Kadr ulushlaridagi (0..1) poligon — masalan taqiqlangan zona."""

    points: tuple[tuple[float, float], ...]
    label: str = ""


Shape = Box | Polygon


def face_box(face, label: str = "") -> Box:
    """InsightFace yuzining piksel koordinatalaridagi ramkasi."""
    x1, y1, x2, y2 = (float(v) for v in face.bbox)
    return Box(x1, y1, x2, y2, label=label)


def pose_box(points: np.ndarray, *, min_visibility: float = 0.3, label: str = "") -> Box | None:
    """Poza nuqtalaridan odam ramkasi (normallashgan). Ko'rinadigan nuqta
    uchtadan kam bo'lsa ramka chizilmaydi — noto'g'ri joyga chizilgan ramka
    dalil emas, chalg'itish."""
    visible = points[points[:, 3] >= min_visibility]
    if len(visible) < 3:
        return None
    x1, y1 = float(visible[:, 0].min()), float(visible[:, 1].min())
    x2, y2 = float(visible[:, 0].max()), float(visible[:, 1].max())
    pad_x, pad_y = (x2 - x1) * 0.08, (y2 - y1) * 0.05
    return Box(
        max(0.0, x1 - pad_x),
        max(0.0, y1 - pad_y),
        min(1.0, x2 + pad_x),
        min(1.0, y2 + pad_y),
        label=label,
        normalized=True,
    )


def zone_polygon(polygon: Sequence, label: str = "") -> Polygon | None:
    """Kameraning restricted_zone_polygon qiymati ([[x, y], ...], 0..1)."""
    try:
        points = tuple((float(point[0]), float(point[1])) for point in polygon)
    except (TypeError, ValueError, IndexError):
        return None
    return Polygon(points, label=label) if len(points) >= 3 else None


def annotate_snapshot(frame_bytes: bytes, shapes: Sequence[Shape]) -> bytes:
    """Ramka va poligonlar chizilgan JPEG. Xato bo'lsa asl kadr qaytadi —
    chizilmagan kadr dalilsiz qolgandan yaxshiroq."""
    if not shapes:
        return frame_bytes
    try:
        image = cv2.imdecode(np.frombuffer(frame_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return frame_bytes
        height, width = image.shape[:2]
        thickness = max(2, round(min(width, height) / 300))
        for shape in shapes:
            if isinstance(shape, Polygon):
                pts = np.array([[round(x * width), round(y * height)] for x, y in shape.points], dtype=np.int32)
                cv2.polylines(image, [pts], isClosed=True, color=_ZONE_COLOR, thickness=thickness)
                continue
            scale_x, scale_y = (width, height) if shape.normalized else (1, 1)
            top_left = (round(shape.x1 * scale_x), round(shape.y1 * scale_y))
            bottom_right = (round(shape.x2 * scale_x), round(shape.y2 * scale_y))
            cv2.rectangle(image, top_left, bottom_right, _BOX_COLOR, thickness)
            if shape.label:
                _put_label(image, shape.label, top_left, thickness)
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY])
        return encoded.tobytes() if ok else frame_bytes
    except Exception:
        logger.exception("snapshot annotation failed")
        return frame_bytes


def _put_label(image: np.ndarray, text: str, origin: tuple[int, int], thickness: int) -> None:
    # Hershey shriftlari faqat ASCII chizadi — yorliqlar qisqa lotincha so'zlar.
    font_scale = max(0.5, thickness / 3)
    (text_w, text_h), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
    x, y = origin[0], max(text_h + baseline + 4, origin[1])
    cv2.rectangle(image, (x, y - text_h - baseline - 4), (x + text_w + 6, y), _BOX_COLOR, -1)
    cv2.putText(image, text, (x + 3, y - baseline - 2), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), 1, cv2.LINE_AA)
