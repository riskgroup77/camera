"""In-memory last AI sweep snapshot per camera — backs monitoring modal badge."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class CameraSweepSnapshot:
    camera_id: str
    swept_at: datetime
    face_count: int
    modules: tuple[str, ...]
    events_raised: int


_cache: dict[str, CameraSweepSnapshot] = {}
_lock = asyncio.Lock()


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


async def get_camera_sweep(camera_id: str) -> CameraSweepSnapshot | None:
    async with _lock:
        return _cache.get(camera_id)


def reset_sweep_cache_for_tests() -> None:
    _cache.clear()
