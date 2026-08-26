"""Priority gate for InsightFace inference — live-detection and enrollment
should not queue behind a background AI sweep that's holding every slot.

Lower priority number = served first. Background sweeps use
PRIORITY_BACKGROUND; /api/public/.../live-detection and biometric
enrollment use PRIORITY_LIVE."""

import asyncio
import heapq
import itertools
from contextlib import asynccontextmanager

from app.config import settings

PRIORITY_LIVE = 0
PRIORITY_BACKGROUND = 10

_counter = itertools.count()


class PriorityInferenceGate:
    def __init__(self, max_concurrent: int) -> None:
        self._max = max(1, max_concurrent)
        self._in_use = 0
        self._waiters: list[tuple[int, int, asyncio.Event]] = []
        self._lock = asyncio.Lock()

    def _grant_next(self) -> None:
        while self._waiters and self._in_use < self._max:
            _, _, event = heapq.heappop(self._waiters)
            self._in_use += 1
            event.set()

    @asynccontextmanager
    async def slot(self, *, priority: int = PRIORITY_BACKGROUND):
        async with self._lock:
            if self._in_use < self._max and (
                not self._waiters or priority <= self._waiters[0][0]
            ):
                self._in_use += 1
                granted = True
            else:
                event = asyncio.Event()
                heapq.heappush(self._waiters, (priority, next(_counter), event))
                granted = False
        if not granted:
            await event.wait()
        try:
            yield
        finally:
            async with self._lock:
                self._in_use -= 1
                self._grant_next()

    def snapshot(self) -> dict[str, int]:
        return {
            "max": self._max,
            "in_use": self._in_use,
            "waiting": len(self._waiters),
        }


face_inference_gate = PriorityInferenceGate(settings.face_recognition_inference_concurrency)
