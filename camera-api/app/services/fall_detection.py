"""TT kriteriya 24 ("Yiqilib tushish") — per-pose fall detection from
mediapipe's 33 body landmarks (app/services/pose_detection.py). A
well-established, non-invented technique: a standing person's torso
(shoulder-midpoint to hip-midpoint) is roughly vertical and their overall
body bounding box is taller than wide; someone who has fallen reads as
the opposite on both counts — torso close to horizontal, bounding box
wider than tall.

Two independent signals, either one sufficient: torso angle from
vertical (the more direct, primary signal) OR bounding-box aspect ratio
(width/height — a secondary/confirming signal, useful when the torso
landmarks themselves are unreliable but the overall body silhouette
still reads as "lying down"). Both are gated on landmark visibility —
mediapipe reports a low-confidence estimate for occluded/off-frame
landmarks rather than omitting them, so a raw angle computed from
barely-visible points would be meaningless.

Honest scope note: this is a single-frame geometric heuristic, not a
trained fall-detection model — someone sitting cross-legged on the
floor, stretching, or doing floor exercises can read as "fallen" by
this same geometry. app/jobs/fall_ai.py's two-frame confirmation (a real
fall involves a SUSTAINED horizontal posture, not a momentary one)
mitigates but does not eliminate this — it has not been validated
against real fall footage, only the synthetic pose coordinates in
tests/test_fall_detection.py.
"""

import math

import numpy as np

from app.config import settings
from app.services.pose_detection import LEFT_HIP, LEFT_SHOULDER, RIGHT_HIP, RIGHT_SHOULDER


def _torso_angle_from_vertical(points: np.ndarray) -> float | None:
    """Degrees from vertical: 0 = perfectly upright torso, 90 = fully
    horizontal. None if the shoulder/hip landmarks aren't visible enough
    to trust the geometry."""
    required = [LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP]
    if not all(points[i][3] >= settings.fall_min_landmark_visibility for i in required):
        return None

    shoulder_mid = (points[LEFT_SHOULDER][:2] + points[RIGHT_SHOULDER][:2]) / 2
    hip_mid = (points[LEFT_HIP][:2] + points[RIGHT_HIP][:2]) / 2
    dx = float(shoulder_mid[0] - hip_mid[0])
    dy = float(shoulder_mid[1] - hip_mid[1])  # image y increases downward, doesn't affect the angle magnitude
    if dx == 0.0 and dy == 0.0:
        return None
    return math.degrees(math.atan2(abs(dx), abs(dy)))


def _bbox_aspect_ratio(points: np.ndarray) -> float | None:
    """width / height of the bounding box formed by every visible-enough
    landmark. None if too few landmarks are visible to form a meaningful
    box."""
    visible = points[points[:, 3] >= settings.fall_min_landmark_visibility]
    if len(visible) < 4:
        return None
    xs, ys = visible[:, 0], visible[:, 1]
    width = float(xs.max() - xs.min())
    height = float(ys.max() - ys.min())
    if height <= 0:
        return None
    return width / height


def is_fallen(points: np.ndarray) -> bool:
    """points: (33, 4) array — e.g. PoseLandmarks.points."""
    angle = _torso_angle_from_vertical(points)
    if angle is not None and angle >= settings.fall_torso_angle_threshold:
        return True

    aspect = _bbox_aspect_ratio(points)
    if aspect is not None and aspect >= settings.fall_aspect_ratio_threshold:
        return True

    return False
