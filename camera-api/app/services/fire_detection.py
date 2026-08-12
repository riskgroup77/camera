"""TT kriteriya 23 ("Yong'in / tutun aniqlash") — color + temporal-flicker
based fire detection, not a single-frame color rule.

An earlier attempt at plain color-based fire detection (HSV/YCbCr
thresholding on one frame) was tested against a real human photo
(insightface's t1.jpg) and rejected: skin tones under normal/warm
lighting fall into the same HSV range as fire, producing a ~20-26% false
positive pixel fraction on an ordinary photo with no fire in it at all —
i.e. it would have false-alarmed on nearly every frame containing a
visible person.

This version adds the standard second filter the fire-detection
literature (Toreyin et al., "Computer Vision Based Method for Real-Time
Fire and Flame Detection", 2005; and Celik & Demirel's own follow-up
work) uses to reject exactly that failure mode: real flame flickers
(intensity fluctuates noticeably within roughly a second, from the
flame's own turbulent combustion), while a static warm-colored surface —
skin, a wall, backlighting — does not. Only pixels that are BOTH
fire-colored AND show a large intensity change between two frames spaced
~1 second apart count as a fire signal.

Honest scope note: this was validated against (1) the real false-positive
case from the earlier attempt — two identical frames of a human photo,
which now correctly produces zero flicker and no detection — and (2)
constructed synthetic flicker/no-flicker scenarios. No real fire footage
was available in this environment to validate against (none exists
here) — that is a genuine, disclosed gap, not an oversight.
app/jobs/fire_ai.py's honest-scope docstring carries the same caveat
forward to where Events actually get raised.
"""

import cv2
import numpy as np

# Same HSV rule validated (for color alone) in the earlier attempt — kept
# because it correctly separates bright orange/red from blue/green/dim
# tones; the problem was never the color range, it was using color alone.
_HUE_LOW_MAX = 35
_HUE_HIGH_MIN = 170
_SATURATION_MIN = 120
_VALUE_MIN = 180

# A real flame's turbulent combustion changes a pixel's brightness a lot
# within ~1 second; a static warm surface barely moves at all.
_FLICKER_VALUE_DIFF_MIN = 40

# Fraction of frame pixels that must be simultaneously fire-colored AND
# flickering before this reads as fire — deliberately small, since this is
# a much rarer, more specific combination than color alone.
FIRE_PIXEL_FRACTION_THRESHOLD = 0.015


def _decode(image_bytes: bytes) -> np.ndarray | None:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _fire_color_mask(bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hue, saturation, value = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    hue_ok = (hue <= _HUE_LOW_MAX) | (hue >= _HUE_HIGH_MIN)
    return hue_ok & (saturation >= _SATURATION_MIN) & (value >= _VALUE_MIN)


def fire_pixel_fraction(frame_a_bytes: bytes, frame_b_bytes: bytes) -> float:
    """frame_a/frame_b should be two frames of the same camera, roughly a
    second apart. Returns the fraction of frame_b's pixels that are both
    fire-colored and show a large brightness change from frame_a — 0.0 if
    either frame fails to decode or the two frames aren't the same size
    (e.g. the camera's resolution changed mid-sweep)."""
    frame_a = _decode(frame_a_bytes)
    frame_b = _decode(frame_b_bytes)
    if frame_a is None or frame_b is None or frame_a.shape != frame_b.shape:
        return 0.0

    color_mask = _fire_color_mask(frame_b)
    value_a = cv2.cvtColor(frame_a, cv2.COLOR_BGR2HSV)[:, :, 2].astype(np.int16)
    value_b = cv2.cvtColor(frame_b, cv2.COLOR_BGR2HSV)[:, :, 2].astype(np.int16)
    flicker_mask = np.abs(value_b - value_a) >= _FLICKER_VALUE_DIFF_MIN

    fire_mask = color_mask & flicker_mask
    return float(np.count_nonzero(fire_mask)) / fire_mask.size


def is_likely_fire(frame_a_bytes: bytes, frame_b_bytes: bytes) -> bool:
    return fire_pixel_fraction(frame_a_bytes, frame_b_bytes) >= FIRE_PIXEL_FRACTION_THRESHOLD
