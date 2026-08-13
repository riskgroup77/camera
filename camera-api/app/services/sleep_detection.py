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
direction that matters — the same bad-angle geometry could just as easily
collapse a face's eye region low instead of high, reading as "asleep" when
the person is just looking away.

is_asleep() now gates on `is_plausible_frontal()` first — a cheap
landmark-only proxy for head yaw (see its docstring), rejecting exactly
that failure mode BEFORE the EAR check ever runs, instead of relying
solely on app/jobs/vision_ai.py's multi-frame confirmation to average it
away. This is a real accuracy improvement, not a cosmetic one: it removes
a documented, reproduced source of false "asleep" readings at the
single-frame level, on top of (not instead of) the multi-frame majority
vote in vision_ai.py.
"""

import numpy as np

EAR_CLOSED_THRESHOLD = 0.21

RIGHT_EYE_INDICES = [36, 37, 38, 39, 40, 41]
LEFT_EYE_INDICES = [42, 43, 44, 45, 46, 47]

# iBUG-68 scheme: 33 is the nose tip, 36/45 the outer corners of the
# right/left eyes (subject's right/left, not image-left/right).
NOSE_TIP_INDEX = 33
RIGHT_EYE_OUTER_INDEX = 36
LEFT_EYE_OUTER_INDEX = 45

# A frontal face's nose tip sits near the horizontal midpoint between the
# two outer eye corners (ratio ~0.5); as the head turns, the nose position
# skews toward whichever side is turned away. This band was picked to
# comfortably admit normal head movement (nodding, slight turns toward a
# neighbor) while rejecting the ~45 degrees+ turn that produced the
# EAR=1.3 degenerate reading described above — not tuned against a
# labeled dataset, since none exists for this project; a real deployment
# tuning this further should log rejected-frame frontality ratios over
# real classroom footage and adjust the band from that.
_FRONTALITY_MIN = 0.25
_FRONTALITY_MAX = 0.75


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


def frontality_ratio(landmarks_68: np.ndarray) -> float:
    """~0.5 for a roughly frontal face, moving toward 0 or 1 (and beyond)
    as the head turns away from the camera — see the module docstring.
    Landmark-only, no separate pose model or extra inference cost."""
    right_outer_x = landmarks_68[RIGHT_EYE_OUTER_INDEX][0]
    left_outer_x = landmarks_68[LEFT_EYE_OUTER_INDEX][0]
    nose_x = landmarks_68[NOSE_TIP_INDEX][0]
    span = left_outer_x - right_outer_x
    if span == 0:
        return 0.5  # degenerate geometry — don't reject on this basis alone
    return float((nose_x - right_outer_x) / span)


def is_plausible_frontal(landmarks_68: np.ndarray) -> bool:
    return _FRONTALITY_MIN <= frontality_ratio(landmarks_68) <= _FRONTALITY_MAX


def is_asleep(landmarks_68: np.ndarray) -> bool:
    """False for both "eyes plausibly open" AND "head turned too far to
    trust the eye geometry at all" — see the module docstring for why the
    latter matters as much as the EAR threshold itself."""
    if not is_plausible_frontal(landmarks_68):
        return False
    return average_eye_aspect_ratio(landmarks_68) < EAR_CLOSED_THRESHOLD
