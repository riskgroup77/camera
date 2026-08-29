"""Pulls a JPEG frame from a camera's live stream — the missing link
between "a camera is registered with MediaMTX" and "an AI module can
actually look at what it sees".

When settings.ai_use_direct_rtsp is true, AI modules read the camera's
RTSP substream directly (no MediaMTX/HLS hop). Browser playback still
uses Camera.stream_url (HLS via MediaMTX).
"""

import asyncio
import logging
import time

from app.config import settings
from app.crypto import decrypt
from app.models import Camera
from app.rtsp import build_rtsp_url
from app.services.stream_cache import get_cached_frame
from app.services.video_gateway import public_hls_to_internal

logger = logging.getLogger("app.frame_grabber")


def rtsp_url_for_camera(camera: Camera, *, substream: bool | None = None) -> str:
    use_sub = settings.ai_use_direct_rtsp if substream is None else substream
    path = settings.rtsp_substream_path if use_sub else (camera.rtsp_path or "/Streaming/Channels/101")
    return build_rtsp_url(
        camera.ip,
        camera.port,
        path,
        decrypt(camera.rtsp_username) if camera.rtsp_username else None,
        decrypt(camera.rtsp_password) if camera.rtsp_password else None,
    )


def camera_video_source(camera: Camera) -> str:
    """URL used by AI frame readers — RTSP substream or HLS fallback."""
    if settings.ai_use_direct_rtsp:
        return rtsp_url_for_camera(camera)
    if not camera.stream_url:
        return ""
    return public_hls_to_internal(camera.stream_url)


async def grab_frame_for_camera(camera: Camera, *, wait_seconds: float = 8.0) -> bytes | None:
    source = camera_video_source(camera)
    if not source:
        return None
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        frame = await get_cached_frame(source)
        if frame is not None:
            return frame
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
