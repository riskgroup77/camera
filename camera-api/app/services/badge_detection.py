"""TT kriteriya 12 — ID-badge taxminiy aniqlash (evristika, o'qitilgan model emas).

Ko'krak (elka oralig'i) hududida yuqori kontrastli to'rtburchak
kontur qidiriladi — haqiqiy badge detektori emas, faqat kichik
ochiq/qora to'rtburchak shakl.
"""

import cv2
import numpy as np

from app.config import settings
from app.services.pose_detection import LEFT_SHOULDER, RIGHT_SHOULDER


def chest_bbox(points: np.ndarray, frame_width: int, frame_height: int) -> tuple[int, int, int, int] | None:
    if points[LEFT_SHOULDER][3] < settings.badge_min_landmark_visibility:
        return None
    if points[RIGHT_SHOULDER][3] < settings.badge_min_landmark_visibility:
        return None
    ls, rs = points[LEFT_SHOULDER], points[RIGHT_SHOULDER]
    cx = (ls[0] + rs[0]) / 2
    cy = (ls[1] + rs[1]) / 2
    span = abs(float(rs[0]) - float(ls[0]))
    half_w = span * settings.badge_chest_width_factor
    half_h = span * settings.badge_chest_height_factor
    x1 = max(0.0, cx - half_w)
    x2 = min(1.0, cx + half_w)
    y1 = max(0.0, cy - half_h * 0.3)
    y2 = min(1.0, cy + half_h)
    px1, py1 = int(x1 * frame_width), int(y1 * frame_height)
    px2, py2 = int(x2 * frame_width), int(y2 * frame_height)
    if px2 <= px1 or py2 <= py1:
        return None
    return px1, py1, px2, py2


def has_visible_badge(image: np.ndarray, points: np.ndarray) -> bool:
    bbox = chest_bbox(points, image.shape[1], image.shape[0])
    if bbox is None:
        return False
    x1, y1, x2, y2 = bbox
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return False
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area = crop.shape[0] * crop.shape[1]
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        rect_area = w * h
        if rect_area < area * settings.badge_min_rect_fraction:
            continue
        if rect_area > area * settings.badge_max_rect_fraction:
            continue
        aspect = w / max(h, 1)
        if settings.badge_min_aspect <= aspect <= settings.badge_max_aspect:
            return True
    return False
