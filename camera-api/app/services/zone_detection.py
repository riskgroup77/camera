"""TT kriteriya 2 ("Taqiqlangan zonaga kirish") — checks whether a
detected person's GROUND position (where their feet are, not their face
or torso) falls inside a camera's configured restricted-zone polygon
(Camera.restricted_zone_polygon — see that model's docstring for the
coordinate convention).

Ground position prefers the ankle midpoint (mediapipe pose landmarks 27,
28) — the truest "where is this person standing" signal — and falls back
to the hip midpoint (23, 24) when the ankles aren't visible enough to
trust (a common case: many camera angles crop out feet, or a person is
partially occluded by furniture/other people). The hip fallback is
deliberately a worse proxy (a person leaning into a zone without their
feet crossing the line would misread as "inside"), documented here
rather than silently treated as equally reliable.
"""

import cv2
import numpy as np

from app.config import settings
from app.services.pose_detection import LEFT_ANKLE, LEFT_HIP, RIGHT_ANKLE, RIGHT_HIP


def ground_position(points: np.ndarray) -> tuple[float, float] | None:
    if points[LEFT_ANKLE][3] >= settings.zone_min_landmark_visibility and points[RIGHT_ANKLE][3] >= settings.zone_min_landmark_visibility:
        x = float((points[LEFT_ANKLE][0] + points[RIGHT_ANKLE][0]) / 2)
        y = float((points[LEFT_ANKLE][1] + points[RIGHT_ANKLE][1]) / 2)
        return x, y

    if points[LEFT_HIP][3] >= settings.zone_min_landmark_visibility and points[RIGHT_HIP][3] >= settings.zone_min_landmark_visibility:
        x = float((points[LEFT_HIP][0] + points[RIGHT_HIP][0]) / 2)
        y = float((points[LEFT_HIP][1] + points[RIGHT_HIP][1]) / 2)
        return x, y

    return None


def is_inside_zone(position: tuple[float, float], polygon: list) -> bool:
    """polygon: list of [x, y] pairs (Camera.restricted_zone_polygon),
    normalized 0-1 — same convention as `position`."""
    if len(polygon) < 3:
        return False  # not a real polygon
    poly = np.array(polygon, dtype=np.float32)
    return cv2.pointPolygonTest(poly, position, False) >= 0
