"""RTSP -> HLS gateway integration (MediaMTX). Supports optional horizontal
sharding via MEDIAMTX_SHARD_API_URLS + MEDIAMTX_SHARD_HLS_BASE_URLS
(comma-separated, equal length) — cameras are assigned by stable hash.
"""

import hashlib
import logging
import shlex
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger("app.video_gateway")


@dataclass(frozen=True)
class _Shard:
    api_url: str
    hls_base_url: str


_shards: list[_Shard] | None = None


def _parse_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _get_shards() -> list[_Shard]:
    global _shards
    if _shards is not None:
        return _shards
    api_urls = _parse_csv(settings.mediamtx_shard_api_urls)
    hls_urls = _parse_csv(settings.mediamtx_shard_hls_base_urls)
    if api_urls and hls_urls and len(api_urls) == len(hls_urls):
        _shards = [_Shard(api, hls) for api, hls in zip(api_urls, hls_urls, strict=True)]
    else:
        _shards = [_Shard(settings.mediamtx_api_url.rstrip("/"), settings.mediamtx_hls_base_url.rstrip("/"))]
    return _shards


def _shard_index(camera_id: str, count: int) -> int:
    digest = hashlib.sha256(camera_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % count


def _shard_for(camera_id: str) -> _Shard:
    shards = _get_shards()
    return shards[_shard_index(camera_id, len(shards))]


def shard_count() -> int:
    return len(_get_shards())


def shard_index_for(camera_id: str) -> int:
    return _shard_index(camera_id, shard_count())


async def probe_shards() -> list[dict[str, object]]:
    """Live probe of each MediaMTX control API — path counts and reachability."""
    shards = _get_shards()
    out: list[dict[str, object]] = []
    async with httpx.AsyncClient(timeout=3.0) as client:
        for index, shard in enumerate(shards):
            path_count = 0
            reachable = False
            error: str | None = None
            try:
                resp = await client.get(f"{shard.api_url}/v3/paths/list")
                resp.raise_for_status()
                data = resp.json()
                items = data.get("items") if isinstance(data, dict) else None
                path_count = len(items) if isinstance(items, list) else 0
                reachable = True
            except httpx.HTTPError as exc:
                error = str(exc)
            out.append(
                {
                    "index": index,
                    "api_url": shard.api_url,
                    "hls_base_url": shard.hls_base_url,
                    "reachable": reachable,
                    "path_count": path_count,
                    "error": error,
                }
            )
    return out


def _path_name(camera_id: str) -> str:
    return f"cam-{camera_id}"


def _path_config(rtsp_url: str) -> dict:
    """MediaMTX path registration — on-demand RTSP relay or H264 transcode."""
    if settings.mediamtx_relay_h264_substream or not settings.mediamtx_transcode_h264:
        return {
            "source": rtsp_url,
            "sourceOnDemand": True,
            "sourceOnDemandStartTimeout": "45s",
            "sourceOnDemandCloseAfter": "300s",
        }

    height = settings.mediamtx_transcode_height
    quoted_url = shlex.quote(rtsp_url)
    # Framerate cap. A live encoder that can't sustain realtime doesn't
    # drop frames politely — its output falls further behind its input
    # every second, which is how a wall ends up minutes behind reality.
    # Halving the framerate roughly halves the encode cost, and a
    # monitoring wall does not need 25fps.
    fps_arg = f"-r {settings.mediamtx_transcode_fps} " if settings.mediamtx_transcode_fps > 0 else ""
    # height <= 0 => masshtablamaymiz. Bu registratsiya SUBSTREAM ustida
    # ishlaydi (stream_sync._rtsp_url_for), substreamlar esa allaqachon
    # kichik (o'lchangan: 640x360 va 768x432). Qat'iy balandlik qo'yish
    # aralash parkda muqarrar ravishda ba'zi kameralarni KATTALASHTIRadi —
    # yo'q detal paydo bo'lmaydi, enkoder esa bir necha barobar ko'p
    # piksel ishlaydi (production'da 360p -> 720p, ya'ni 4 barobar).
    scale_arg = f"-vf scale=-2:{height} " if height > 0 else ""
    cmd = (
        f"/ffmpeg -hide_banner -loglevel error "
        f"-fflags nobuffer -flags low_delay -probesize 32 -analyzeduration 0 "
        f"-rtsp_transport tcp -i {quoted_url} "
        f"-c:v libx264 -preset ultrafast -tune zerolatency "
        f"-profile:v baseline -level 3.1 -pix_fmt yuv420p "
        f"{fps_arg}"
        f"{scale_arg}-an "
        f"-f rtsp rtsp://127.0.0.1:$RTSP_PORT/$MTX_PATH"
    )
    return {
        "runOnDemand": cmd,
        "runOnDemandRestart": True,
        "runOnDemandStartTimeout": "20s",
        # Ko'ruvchi ketgach enkoder qancha vaqt ishlab turishi. Uzun
        # bo'lsa, miniatyura sahifalari orasida yurgan operator ortidan
        # bir necha o'nlab enkoder bir vaqtda ishlab qolishi mumkin —
        # har biri CPU yeydi va qolganlarini real vaqtdan orqada qoldiradi.
        "runOnDemandCloseAfter": f"{settings.mediamtx_transcode_close_after_seconds}s",
    }


async def _upsert_path(client: httpx.AsyncClient, api_url: str, name: str, payload: dict) -> None:
    resp = await client.post(f"{api_url}/v3/config/paths/add/{name}", json=payload)
    if resp.status_code == 400:
        resp = await client.patch(f"{api_url}/v3/config/paths/patch/{name}", json=payload)
    if resp.status_code == 400:
        await client.delete(f"{api_url}/v3/config/paths/delete/{name}")
        resp = await client.post(f"{api_url}/v3/config/paths/add/{name}", json=payload)
    resp.raise_for_status()


async def check_reachable() -> None:
    """Raises if any configured MediaMTX shard control API is unreachable."""
    async with httpx.AsyncClient(timeout=3.0) as client:
        for shard in _get_shards():
            resp = await client.get(f"{shard.api_url}/v3/paths/list")
            resp.raise_for_status()


def hls_url_for(camera_id: str) -> str:
    shard = _shard_for(camera_id)
    return f"{shard.hls_base_url}/{_path_name(camera_id)}/index.m3u8"


def public_hls_to_internal(public_url: str) -> str:
    """Rewrite a browser-facing shard HLS URL to the docker-internal base the API
    container can reach (frame_grabber / stream_cache ffmpeg)."""
    public_bases = _parse_csv(settings.mediamtx_shard_hls_base_urls)
    internal_bases = _parse_csv(settings.mediamtx_shard_hls_internal_base_urls)
    if public_bases and internal_bases and len(public_bases) == len(internal_bases):
        for pub, internal in zip(public_bases, internal_bases, strict=True):
            pub = pub.rstrip("/")
            internal = internal.rstrip("/")
            if public_url.startswith(pub + "/") or public_url == pub:
                return internal + public_url[len(pub) :]
    public_base = settings.mediamtx_hls_base_url.rstrip("/")
    internal_base = (settings.mediamtx_hls_internal_base_url or settings.mediamtx_hls_base_url).rstrip("/")
    if public_base.startswith("/"):
        if public_url.startswith(public_base + "/") or public_url == public_base:
            return internal_base + public_url[len(public_base) :]
    elif internal_base != public_base and public_url.startswith(public_base):
        return internal_base + public_url[len(public_base) :]
    return public_url


async def register_camera_stream(camera_id: str, rtsp_url: str) -> str:
    shard = _shard_for(camera_id)
    name = _path_name(camera_id)
    payload = _path_config(rtsp_url)
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await _upsert_path(client, shard.api_url, name, payload)
        except httpx.HTTPError as exc:
            logger.error(
                "video gateway registration failed",
                extra={"camera_id": camera_id, "shard": shard.api_url, "error": str(exc)},
            )

    return hls_url_for(camera_id)


async def unregister_camera_stream(camera_id: str) -> None:
    shard = _shard_for(camera_id)
    name = _path_name(camera_id)
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            await client.delete(f"{shard.api_url}/v3/config/paths/delete/{name}")
        except httpx.HTTPError as exc:
            logger.warning(
                "video gateway unregistration failed",
                extra={"camera_id": camera_id, "shard": shard.api_url, "error": str(exc)},
            )
