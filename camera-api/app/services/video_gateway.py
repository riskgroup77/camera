"""RTSP -> HLS gateway integration (MediaMTX). Supports optional horizontal
sharding via MEDIAMTX_SHARD_API_URLS + MEDIAMTX_SHARD_HLS_BASE_URLS
(comma-separated, equal length) — cameras are assigned by stable hash.
"""

import hashlib
import logging
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
    if internal_base != public_base and public_url.startswith(public_base):
        return internal_base + public_url[len(public_base) :]
    return public_url


async def register_camera_stream(camera_id: str, rtsp_url: str) -> str:
    shard = _shard_for(camera_id)
    name = _path_name(camera_id)
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.post(
                f"{shard.api_url}/v3/config/paths/add/{name}",
                json={"source": rtsp_url},
            )
            if resp.status_code == 400:
                resp = await client.patch(
                    f"{shard.api_url}/v3/config/paths/patch/{name}",
                    json={"source": rtsp_url},
                )
            resp.raise_for_status()
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
