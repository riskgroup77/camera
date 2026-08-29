"""Pulls a JPEG frame from a camera's live stream — the missing link
between "a camera is registered with MediaMTX" and "an AI module can
actually look at what it sees".

When settings.ai_use_direct_rtsp is true, AI modules read the camera's
RTSP substream directly (no MediaMTX/HLS hop). Browser playback still
uses Camera.stream_url (HLS via MediaMTX).

Entrance/perimeter cameras optionally use the main RTSP stream (101)
for face AI — substream is too low-res for corridor-wide shots.
"""

import asyncio
import logging
import time

from app.config import settings
from app.crypto import decrypt
from app.models import Camera
from app.rtsp import build_rtsp_url
from app.services.stream_cache import get_cached_frame, is_stream_known_broken
from app.services.video_gateway import public_hls_to_internal

logger = logging.getLogger("app.frame_grabber")


def _is_security_camera(camera: Camera) -> bool:
    return camera.is_entrance or camera.is_perimeter


def ai_prefers_substream(camera: Camera) -> bool:
    """True → Channels/102; False → main stream (101 or camera.rtsp_path)."""
    if settings.ai_entrance_use_main_stream and _is_security_camera(camera):
        return False
    return True


def rtsp_url_for_camera(camera: Camera, *, substream: bool | None = None) -> str:
    use_sub = ai_prefers_substream(camera) if substream is None else substream
    path = settings.rtsp_substream_path if use_sub else (camera.rtsp_path or "/Streaming/Channels/101")
    return build_rtsp_url(
        camera.ip,
        camera.port,
        path,
        decrypt(camera.rtsp_username) if camera.rtsp_username else None,
        decrypt(camera.rtsp_password) if camera.rtsp_password else None,
    )


def camera_video_source(camera: Camera) -> str:
    """URL used by AI frame readers — RTSP substream/main or HLS fallback."""
    if settings.ai_use_direct_rtsp:
        return rtsp_url_for_camera(camera)
    if not camera.stream_url:
        return ""
    return public_hls_to_internal(camera.stream_url)


def frame_wait_seconds_for_camera(camera: Camera) -> float:
    if settings.ai_entrance_use_main_stream and _is_security_camera(camera):
        return settings.ai_entrance_frame_wait_seconds
    return 8.0


async def grab_frame_for_camera(camera: Camera, *, wait_seconds: float | None = None) -> bytes | None:
    source = camera_video_source(camera)
    if not source:
        return None
    deadline = time.monotonic() + (wait_seconds if wait_seconds is not None else frame_wait_seconds_for_camera(camera))
    while time.monotonic() < deadline:
        frame = await get_cached_frame(source)
        if frame is not None:
            return frame
        if is_stream_known_broken(source):
            return None  # reader had its grace period, decoded nothing — don't burn the rest of the slot
        await asyncio.sleep(0.5)
    return None


async def grab_frame(stream_url: str) -> bytes | None:
    """Legacy HLS grab by stream URL (live-detection endpoint, etc.)."""
    return await get_cached_frame(public_hls_to_internal(stream_url))


async def grab_frame_pair_for_camera(camera: Camera, gap_seconds: float = 1.0) -> tuple[bytes, bytes] | None:
    first = await grab_frame_for_camera(camera)
    if first is None:
        return None
    await asyncio.sleep(gap_seconds)
    second = await grab_frame_for_camera(camera)
    if second is None:
        return None
    return first, second


async def grab_frame_pair(stream_url: str, gap_seconds: float = 1.0) -> tuple[bytes, bytes] | None:
    first = await grab_frame(stream_url)
    if first is None:
        return None
    await asyncio.sleep(gap_seconds)
    second = await grab_frame(stream_url)
    if second is None:
        return None
    return first, second


async def grab_frame_burst_for_camera(camera: Camera, count: int, gap_seconds: float) -> list[bytes]:
    frames: list[bytes] = []
    for i in range(count):
        if i > 0:
            await asyncio.sleep(gap_seconds)
        frame = await grab_frame_for_camera(camera)
        if frame is not None:
            frames.append(frame)
    return frames


async def grab_frame_burst(stream_url: str, count: int, gap_seconds: float) -> list[bytes]:
    frames: list[bytes] = []
    for i in range(count):
        if i > 0:
            await asyncio.sleep(gap_seconds)
        frame = await grab_frame(stream_url)
        if frame is not None:
            frames.append(frame)
    return frames
