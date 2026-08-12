"""RTSP -> HLS gateway integration (MediaMTX). This is the piece the old
frontend-only prototype could never have — a browser cannot speak RTSP,
so something has to pull the camera's RTSP stream and re-serve it as
HLS/WebRTC. MediaMTX does that; this module just tells it which camera
to pull from and hands back the URL LiveVideoPlayer.tsx actually plays.
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger("app.video_gateway")


def _path_name(camera_id: str) -> str:
    return f"cam-{camera_id}"


async def check_reachable() -> None:
    """Raises if MediaMTX's control API is unreachable — used by GET
    /health. Unlike register_camera_stream()/unregister_camera_stream(),
    this is NOT best-effort: /health exists specifically to surface this
    kind of dependency outage to an operator."""
    async with httpx.AsyncClient(timeout=3.0) as client:
        resp = await client.get(f"{settings.mediamtx_api_url}/v3/paths/list")
        resp.raise_for_status()


def hls_url_for(camera_id: str) -> str:
    return f"{settings.mediamtx_hls_base_url}/{_path_name(camera_id)}/index.m3u8"


async def register_camera_stream(camera_id: str, rtsp_url: str) -> str:
    """Registers (or updates) a MediaMTX path that pulls from rtsp_url and
    returns the HLS URL to store on the camera row. Best-effort: if the
    gateway is unreachable this logs and returns the URL anyway — cameras
    with stream_url set won't play, but the resource still exists and the
    rest of the API stays usable (an outage of the video gateway shouldn't
    also take down camera CRUD)."""
    name = _path_name(camera_id)
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.post(
                f"{settings.mediamtx_api_url}/v3/config/paths/add/{name}",
                json={"source": rtsp_url},
            )
            if resp.status_code == 400:
                # path already exists from a previous registration — update it instead.
                resp = await client.patch(
                    f"{settings.mediamtx_api_url}/v3/config/paths/patch/{name}",
                    json={"source": rtsp_url},
                )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("video gateway registration failed", extra={"camera_id": camera_id, "error": str(exc)})

    return hls_url_for(camera_id)


async def unregister_camera_stream(camera_id: str) -> None:
    name = _path_name(camera_id)
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            await client.delete(f"{settings.mediamtx_api_url}/v3/config/paths/delete/{name}")
        except httpx.HTTPError as exc:
            logger.warning("video gateway unregistration failed", extra={"camera_id": camera_id, "error": str(exc)})
