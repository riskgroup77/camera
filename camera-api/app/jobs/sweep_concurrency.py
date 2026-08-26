"""Shared concurrency cap for every AI camera sweep module.

When the central scheduler runs modules in parallel, a per-module
Semaphore(N) would allow up to (module_count × N) concurrent camera
pipelines — hundreds of simultaneous ffmpeg readers and DB sessions.
Every sweep acquires global_camera_semaphore so the total in-flight
camera count stays bounded regardless of how many modules are due.
"""

import asyncio
from contextlib import asynccontextmanager

from app.config import settings

_global_camera_semaphore: asyncio.Semaphore | None = None


def global_camera_semaphore() -> asyncio.Semaphore:
    global _global_camera_semaphore
    if _global_camera_semaphore is None:
        _global_camera_semaphore = asyncio.Semaphore(settings.ai_global_sweep_concurrency)
    return _global_camera_semaphore


@asynccontextmanager
async def camera_sweep_slot():
    async with global_camera_semaphore():
        yield


def reset_global_camera_semaphore_for_tests() -> None:
    """Tests only — next acquire rebuilds the semaphore from current settings."""
    global _global_camera_semaphore
    _global_camera_semaphore = None
