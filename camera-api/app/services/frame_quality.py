"""Rejects visibly corrupted frames before any detector sees them.

Why this exists: the readers in stream_cache.py decode keyframes out of a
live RTSP stream. When a keyframe arrives incomplete — a lost packet, a
camera under load — the decoder does not fail, it emits a PARTIALLY
decoded picture: the intact part of the scene plus a large flat block of
garbage, usually near-white with a regular dotted texture and hard
rectangular edges.

Nothing checked for that, so those frames went straight into the AI
sweeps. Measured on production by pulling the stored snapshot of every
sampled event: 4 of 23 carried decode damage, and every one of those four
had produced a false event — a "vehicle in the courtyard" raised against
an indoor laboratory, and three "disorder" alerts against empty rooms
between 23:37 and 23:55. A detector asked to explain a quarter-frame of
garbage will find something in it.

The check runs when a frame is READ rather than when it is decoded. The
readers decode at stream_cache_capture_fps (2/s per camera, ~214/s across
the fleet); sweeps read roughly one frame per camera per interval. Same
protection, an order of magnitude less work.

Rejecting a frame yields no frame at all, and that is deliberate: for a
detector, a missing frame costs one skipped cycle, while a corrupt frame
costs a false alarm that a human then has to review and dismiss.
"""

import logging

import cv2
import numpy as np

from app.config import settings

logger = logging.getLogger("app.frame_quality")


def largest_flat_block_fraction(jpeg_bytes: bytes) -> float | None:
    """Share of the frame taken by its biggest connected near-white
    region, or None if the JPEG cannot be decoded at all.

    Decoded at 1/8 scale and in grayscale — IMREAD_REDUCED_GRAYSCALE_8
    reads roughly a sixty-fourth of the pixels, which is what makes this
    cheap enough to run on every frame handed out. Decode damage covers
    hundreds of pixels; nothing about it needs full resolution to see.

    Why the biggest CONNECTED region rather than the total near-white
    area: a sunlit room is bright in many scattered places, while decode
    damage is one solid slab. Measured over the production sample, that
    distinction is what separates the two cleanly — the brightest intact
    frame scored 1.8% here, the least damaged corrupt frame 6.6%.
    """
    buffer = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    image = cv2.imdecode(buffer, cv2.IMREAD_REDUCED_GRAYSCALE_8)
    if image is None or image.size == 0:
        return None

    mask = (image >= settings.frame_corruption_white_level).astype(np.uint8)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    if count <= 1:
        return 0.0  # label 0 is the background; no near-white pixels at all

    largest_area = int(stats[1:, cv2.CC_STAT_AREA].max())
    return largest_area / image.size


def is_frame_corrupt(jpeg_bytes: bytes | None) -> bool:
    """True when the frame should not be shown to a detector."""
    if not jpeg_bytes:
        return False  # nothing to judge; callers already handle "no frame"

    try:
        fraction = largest_flat_block_fraction(jpeg_bytes)
    except Exception:  # noqa: BLE001 - a quality check must never break a sweep
        logger.warning("frame corruption check failed; treating frame as usable", exc_info=True)
        return False

    if fraction is None:
        return True  # undecodable bytes are the worst case, not a pass

    return fraction >= settings.frame_corruption_max_flat_block_fraction
