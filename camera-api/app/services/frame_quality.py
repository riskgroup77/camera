"""Rejects visibly corrupted frames before any detector sees them.

Why this exists: the readers in stream_cache.py decode keyframes out of a
live RTSP stream. When a keyframe arrives incomplete — a lost packet, a
camera under load — the decoder does not fail, it emits a PARTIALLY
decoded picture: the intact part of the scene plus a large flat block of
garbage. Nothing checked for that, so those frames went into the AI
sweeps. Measured on production: 4 of 23 sampled event snapshots carried
that damage, and all four had produced a false event.

The hard part is telling damage apart from a sunlit window, and a single
frame does not carry enough to do it. Measured across both populations,
every appearance metric overlaps — the texture inside the block scored
69.7 on a corrupt frame and 67.5 on a sunlit classroom; the pure-white
share, the block's fill ratio and its size all overlap the same way. A
first version of this check used size alone and blinded 29 of 107
cameras on the first sunny morning.

What separates them is not how the block LOOKS but how it BEHAVES. A
window is part of the room: it sits in the same place frame after frame.
Decode damage appears, disappears, and lands somewhere else next time.
So the check compares each frame against the one before it, and rejects
a large flat block only when it is NEW.

Two consequences worth stating. A camera pointed at a genuinely blown-out
window keeps working, because its block persists. And the very first
frame after a reader starts is always accepted, because there is nothing
to compare it against — one possible bad frame, against never blinding a
camera at startup.
"""

from dataclasses import dataclass
import logging

import cv2
import numpy as np

from app.config import settings

logger = logging.getLogger("app.frame_quality")


@dataclass(frozen=True)
class FlatBlock:
    """The biggest connected near-white region in a frame."""

    fraction: float
    """Share of the frame it covers."""

    box: tuple[int, int, int, int]
    """(x, y, w, h) in the reduced-resolution grid the check works in."""


def largest_flat_block(jpeg_bytes: bytes) -> FlatBlock | None:
    """None means the bytes could not be decoded at all.

    Decoded at 1/8 scale in grayscale — IMREAD_REDUCED_GRAYSCALE_8 reads
    about a sixty-fourth of the pixels, which is what makes this cheap
    enough to run on every frame handed out. Damage covers hundreds of
    pixels; nothing about it needs full resolution to see.

    The biggest CONNECTED region rather than the total near-white area: a
    sunlit room is bright in many scattered places, while both damage and
    a window are single solid shapes.
    """
    buffer = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    image = cv2.imdecode(buffer, cv2.IMREAD_REDUCED_GRAYSCALE_8)
    if image is None or image.size == 0:
        return None

    mask = (image >= settings.frame_corruption_white_level).astype(np.uint8)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    if count <= 1:
        return FlatBlock(0.0, (0, 0, 0, 0))  # label 0 is background

    index = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    area = int(stats[index, cv2.CC_STAT_AREA])
    box = (
        int(stats[index, cv2.CC_STAT_LEFT]),
        int(stats[index, cv2.CC_STAT_TOP]),
        int(stats[index, cv2.CC_STAT_WIDTH]),
        int(stats[index, cv2.CC_STAT_HEIGHT]),
    )
    return FlatBlock(area / image.size, box)


def _overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    """Intersection over union of two boxes; 0 when either is empty."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0

    left, right = max(ax, bx), min(ax + aw, bx + bw)
    top, bottom = max(ay, by), min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return 0.0

    intersection = (right - left) * (bottom - top)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union else 0.0


def looks_like_decode_damage(current: FlatBlock | None, previous: FlatBlock | None) -> bool:
    """Whether `current` should be withheld from the detectors.

    `previous` is the block measured on the frame before it from the same
    camera, or None if there isn't one yet.
    """
    if current is None:
        return True  # undecodable bytes are the worst case, not a pass

    if current.fraction < settings.frame_corruption_max_flat_block_fraction:
        return False

    if previous is None:
        return False  # no baseline — see the module docstring

    was_there_before = previous.fraction >= settings.frame_corruption_max_flat_block_fraction
    in_the_same_place = _overlap(current.box, previous.box) >= settings.frame_corruption_persistence_overlap
    return not (was_there_before and in_the_same_place)


_NO_BLOCK = FlatBlock(0.0, (0, 0, 0, 0))


def measure_frame(jpeg_bytes: bytes | None) -> FlatBlock | None:
    """largest_flat_block, but never raising.

    A check that throws reports "no block", not "undecodable" — i.e. it
    fails OPEN, letting frames through unfiltered. Failing closed would
    be the more suspicious-looking choice and the wrong one: this filter
    has already blinded 29 cameras once by rejecting too much, and a
    detector missing a check is a smaller fault than a fleet going dark
    because a helper raised."""
    if not jpeg_bytes:
        return None
    try:
        return largest_flat_block(jpeg_bytes)
    except Exception:  # noqa: BLE001
        logger.warning("frame quality measurement failed; not filtering this frame", exc_info=True)
        return _NO_BLOCK
