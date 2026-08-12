"""TT kriteriya 20 ("Talabaning uxlab qolishi") — eye-aspect-ratio (EAR)
based eye-closure detection from InsightFace's landmark_3d_68 (the
standard 68-point iBUG/dlib scheme — verified empirically against a real
photo before writing this, not assumed: right eye is points 36-41, left
eye 42-47, both cluster into eye-sized regions as expected). No extra
model or external AI API — landmark_3d_68 is already computed as part of
every detection app/services/face_recognition.py does.

The EAR formula and 0.21 threshold are the standard ones from Soukupová &
Čech's "Real-Time Eye Blink Detection using Facial Landmarks" (2016) — the
same reference virtually every open-source drowsiness-detection project
uses; not a number invented for this project.

Honest scope note: a single-frame EAR check can't tell a blink (normal,
well under a second) from someone actually asleep. app/jobs/vision_ai.py
mitigates this by only raising a sleep Event once per dedup window per
person, and at "past" (low) severity — this is a meaningfully
lower-confidence signal than a face-match attendance record, and the rest
of the system should treat it that way, not as an equally-trustworthy
alert.

Found in real testing (not hypothetical): at an oblique head angle — e.g.
someone looking down at a keyboard instead of at the camera — the 68-point
landmark predictor still returns *a* set of points, but the eye geometry
it infers is degenerate, since the model is trained on roughly-frontal
faces. That produced an EAR reading of 1.3 on a real (awake) frame from
this project's own camera — a real open eye tops out around 0.4-0.45. That
specific direction (implausibly HIGH) never risks a false "asleep" anyway,
since it's already nowhere near EAR_CLOSED_THRESHOLD; it's the opposite
direction that matters. A genuinely closed eye is also low, so there's no
EAR-value-alone way to tell a real closure apart from the same bad-angle
geometry collapsing low instead of high — that would need an actual
head-pose check (e.g. from landmark symmetry or the detector's own pose
estimate), which isn't implemented here. What app/jobs/vision_ai.py does
instead is require the SAME identity to read as asleep across two frames
~1s apart before raising anything — a blink doesn't last that long, and
that's the real mitigation for what this module can't distinguish alone.
"""

import numpy as np

EAR_CLOSED_THRESHOLD = 0.21

RIGHT_EYE_INDICES = [36, 37, 38, 39, 40, 41]
LEFT_EYE_INDICES = [42, 43, 44, 45, 46, 47]


def _eye_aspect_ratio(landmarks: np.ndarray, indices: list[int]) -> float:
    p1, p2, p3, p4, p5, p6 = (landmarks[i][:2] for i in indices)
    vertical = np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)
    horizontal = np.linalg.norm(p1 - p4)
    if horizontal == 0:
        return 0.0
    return float(vertical / (2.0 * horizontal))


def average_eye_aspect_ratio(landmarks_68: np.ndarray) -> float:
    """landmarks_68: (68, 2+) array — e.g. DetectedFace.landmarks_68."""
    right = _eye_aspect_ratio(landmarks_68, RIGHT_EYE_INDICES)
    left = _eye_aspect_ratio(landmarks_68, LEFT_EYE_INDICES)
    return (right + left) / 2.0


def is_asleep(landmarks_68: np.ndarray) -> bool:
    return average_eye_aspect_ratio(landmarks_68) < EAR_CLOSED_THRESHOLD
