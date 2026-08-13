"""Pulls a JPEG frame from a camera's live stream — the missing link
between "a camera is registered with MediaMTX" and "an AI module can
actually look at what it sees".

Reads from app/services/stream_cache.py's persistent per-camera reader
rather than spawning a fresh ffmpeg process on every call — see that
module's docstring for why (in short: at hundreds of cameras, reconnecting
from scratch every single sweep tick is real, avoidable overhead). This
module's public contract (JPEG bytes or None per call) is unchanged from
the old spawn-per-call implementation, so callers don't need to know the
difference.
"""

import asyncio
import logging

from app.services.stream_cache import get_cached_frame

logger = logging.getLogger("app.frame_grabber")


async def grab_frame(stream_url: str) -> bytes | None:
    """Returns JPEG bytes of the most recently decoded frame for this
    stream, or None if no fresh-enough frame is available yet (camera
    offline, stream still connecting for the first time, ffmpeg missing,
    etc.) — callers (app/jobs/attendance_ai.py etc.) treat that as
    "nothing to process this tick", not an error worth crashing the sweep
    over. Starts this stream's persistent reader on first call."""
    return await get_cached_frame(stream_url)


async def grab_frame_pair(stream_url: str, gap_seconds: float = 1.0) -> tuple[bytes, bytes] | None:
    """Two frames of the same stream, ~gap_seconds apart — used by
    app/services/fire_detection.py, which needs to see whether a
    fire-colored region's brightness changes between frames (real flame
    flickers; a static warm-colored surface like skin doesn't). Returns
    None if either grab fails, same "nothing to process this tick"
    contract as grab_frame()."""
    first = await grab_frame(stream_url)
    if first is None:
        return None
    await asyncio.sleep(gap_seconds)
    second = await grab_frame(stream_url)
    if second is None:
        return None
    return first, second


async def grab_frame_burst(stream_url: str, count: int, gap_seconds: float) -> list[bytes]:
    """`count` frames of the same stream, `gap_seconds` apart — used by
    app/jobs/vision_ai.py for PERCLOS-style sleep confirmation (majority
    of a several-second window reading as eyes-closed, not just two
    points ~1s apart). Only cheap to do because app/services/
    stream_cache.py already keeps a persistent decoder running per
    stream: each grab here is just reading whatever frame is currently
    cached, not spawning a new ffmpeg process — under the old
    spawn-per-call frame_grabber, a 4-frame burst would have meant 4x the
    process/reconnect overhead of a single grab.

    Returns however many frames were actually available (may be fewer
    than `count`, or empty) rather than failing the whole burst over one
    missed sample — a momentary cache miss mid-burst shouldn't discard
    the frames that DID come through."""
    frames: list[bytes] = []
    for i in range(count):
        if i > 0:
            await asyncio.sleep(gap_seconds)
        frame = await grab_frame(stream_url)
        if frame is not None:
            frames.append(frame)
    return frames
