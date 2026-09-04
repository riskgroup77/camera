"""Last AI sweep snapshot per camera — backs monitoring modal badge.

Uses Redis when REDIS_URL is set so all uvicorn workers see the same data.
Falls back to in-process dict for dev/single-worker.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import settings

_REDIS_KEY_PREFIX = "camera:sweep:"
_REDIS_TTL_SECONDS = 3600


@dataclass(frozen=True)
class CameraSweepSnapshot:
    camera_id: str
    swept_at: datetime
    face_count: int
    modules: tuple[str, ...]
    events_raised: int


_cache: dict[str, CameraSweepSnapshot] = {}
_lock = asyncio.Lock()
_redis = None


async def _get_redis():
    global _redis
    if _redis is not None:
        return _redis
    url = (settings.redis_url or "").strip()
    if not url:
        return None
    try:
        from redis.asyncio import Redis

        _redis = Redis.from_url(url, decode_responses=True)
        await _redis.ping()
    except Exception:
        _redis = None
    return _redis


def _snap_to_dict(snap: CameraSweepSnapshot) -> dict:
    return {
        "camera_id": snap.camera_id,
        "swept_at": snap.swept_at.isoformat(),
        "face_count": snap.face_count,
        "modules": list(snap.modules),
        "events_raised": snap.events_raised,
    }


def _snap_from_dict(data: dict) -> CameraSweepSnapshot:
    swept = data["swept_at"]
    if isinstance(swept, str):
        swept = datetime.fromisoformat(swept)
    return CameraSweepSnapshot(
        camera_id=data["camera_id"],
        swept_at=swept,
        face_count=int(data["face_count"]),
        modules=tuple(data.get("modules") or ()),
        events_raised=int(data.get("events_raised") or 0),
    )


async def record_camera_sweep(
    camera_id: str,
    *,
    face_count: int,
    modules: list[str],
    events_raised: int = 0,
) -> None:
    snap = CameraSweepSnapshot(
        camera_id=camera_id,
        swept_at=datetime.now(timezone.utc),
        face_count=face_count,
        modules=tuple(modules),
        events_raised=events_raised,
    )
    async with _lock:
        _cache[camera_id] = snap
    redis = await _get_redis()
    if redis is not None:
        await redis.setex(
            f"{_REDIS_KEY_PREFIX}{camera_id}",
            _REDIS_TTL_SECONDS,
            json.dumps(_snap_to_dict(snap)),
        )


async def get_camera_sweep(camera_id: str) -> CameraSweepSnapshot | None:
    redis = await _get_redis()
    if redis is not None:
        raw = await redis.get(f"{_REDIS_KEY_PREFIX}{camera_id}")
        if raw:
            return _snap_from_dict(json.loads(raw))
    async with _lock:
        return _cache.get(camera_id)


def reset_sweep_cache_for_tests() -> None:
    _cache.clear()
