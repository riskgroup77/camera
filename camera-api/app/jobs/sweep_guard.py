"""Prevents AI sweep loops from stacking up when a tick takes longer than
its interval — without this, 16 independent while-True loops each fire
every ~30s regardless of whether the previous sweep finished, so at
hundreds of cameras a slow tick means two (or more) full sweeps running
at once, contending for the same camera/inference semaphores and
duplicating work.

Each job module keeps its own SweepGuard instance; guarded_sweep() wraps
one tick and skips cleanly (log + return) if the previous tick is still
in flight."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger("app.sweep_guard")

T = TypeVar("T")


class SweepGuard:
    def __init__(self, name: str) -> None:
        self.name = name
        self._busy = False
        self._lock = asyncio.Lock()

    async def run(self, sweep: Callable[[], Awaitable[T]]) -> T | None:
        async with self._lock:
            if self._busy:
                logger.warning(
                    "AI sweep skipped — previous tick still running",
                    extra={"sweep": self.name},
                )
                return None
            self._busy = True
        try:
            return await sweep()
        finally:
            async with self._lock:
                self._busy = False
