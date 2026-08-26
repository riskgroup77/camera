"""TT kriteriya 15 — qo'l og'iz/burunga yaqin (chekish postura evristikasi).

Sigareta obyektini aniqlamaydi — ikki kadrda ham bilak nuqtasi
burun/muayyan radius ichida bo'lsa, \"qo'l og'izga yaqin\" deb signal.
"""

import math

from app.config import settings
from app.services.pose_detection import LEFT_WRIST, NOSE, RIGHT_WRIST, PoseLandmarks


def _wrist_near_mouth(pose: PoseLandmarks) -> bool:
    nose = pose.points[NOSE]
    if nose[3] < settings.smoking_min_landmark_visibility:
        return False
    nx, ny = float(nose[0]), float(nose[1])
    for wrist_idx in (LEFT_WRIST, RIGHT_WRIST):
        w = pose.points[wrist_idx]
        if w[3] < settings.smoking_min_landmark_visibility:
            continue
        dist = math.hypot(float(w[0]) - nx, float(w[1]) - ny)
        if dist <= settings.smoking_wrist_mouth_distance:
            return True
    return False


def is_smoking_posture(poses: list[PoseLandmarks]) -> bool:
    return any(_wrist_near_mouth(p) for p in poses)
