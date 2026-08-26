"""TT kriteriya 18 — talaba kiyim-boshi (umumiy evristika).

Tanilgan TALABA uchun: yuqori tana (elka-son) ochiqroq,
pastki qism (sondan past) qoraroq — institut formasi taxminiy namuna.
O'qitilgan klassifikator emas.
"""

import cv2
import numpy as np

from app.config import settings
from app.services.pose_detection import LEFT_HIP, LEFT_SHOULDER, RIGHT_HIP, RIGHT_SHOULDER


def _region_mean_value(image: np.ndarray, bbox: tuple[int, int, int, int]) -> float:
    x1, y1, x2, y2 = bbox
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    return float(np.mean(hsv[:, :, 2]))


def torso_and_legs_bboxes(
    points: np.ndarray, frame_width: int, frame_height: int
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]] | None:
    required = [LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP]
    if not all(points[i][3] >= settings.student_uniform_min_landmark_visibility for i in required):
        return None
    shoulder_y = (points[LEFT_SHOULDER][1] + points[RIGHT_SHOULDER][1]) / 2
    hip_y = (points[LEFT_HIP][1] + points[RIGHT_HIP][1]) / 2
    xs = [points[i][0] for i in required]
    x1, x2 = max(0.0, min(xs) - 0.04), min(1.0, max(xs) + 0.04)
    torso = (
        int(x1 * frame_width),
        int(max(0.0, shoulder_y - 0.02) * frame_height),
        int(x2 * frame_width),
        int(hip_y * frame_height),
    )
    leg_bottom = min(1.0, hip_y + (hip_y - shoulder_y) * 1.2)
    legs = (
        int(x1 * frame_width),
        int(hip_y * frame_height),
        int(x2 * frame_width),
        int(leg_bottom * frame_height),
    )
    if torso[2] <= torso[0] or legs[2] <= legs[0]:
        return None
    return torso, legs


def is_uniform_compliant(image: np.ndarray, points: np.ndarray) -> bool:
    """True = reads as compliant (light top + darker bottom)."""
    boxes = torso_and_legs_bboxes(points, image.shape[1], image.shape[0])
    if boxes is None:
        return True
    torso, legs = boxes
    upper_v = _region_mean_value(image, torso)
    lower_v = _region_mean_value(image, legs)
    return upper_v - lower_v >= settings.student_uniform_contrast_min
