"""Bitta kadr — bitta model o'tishi, ko'p modul.

MUAMMO. Har bir AI moduli (jang, zona, chekish, xalat, dars, uyqu, begona
shaxs...) kadrni o'zi oladi va modelni o'zi chaqiradi. Kadr tarixi
(app/services/stream_cache.py) tufayli bir vaqtda ishlayotgan modullar endi
AYNAN bir xil kadr baytlarini oladi — lekin har biri yana o'z yuz/poza/YOLO
hisobini qilardi: dars paytida bitta xona kamerasi ~10 marta yuz, ~6 marta
poza hisobini olardi.

YECHIM. Natija kadr baytlari va chaqiruv parametrlari bo'yicha qisqa muddat
eslab qolinadi. Bir xil kadrni bir vaqtda so'ragan ikkinchi modul birinchi
hisob tugashini kutadi va o'sha natijani oladi (model ikki marta
ishlamaydi). Natijalar faqat o'qiladi — iste'molchilar ularni o'zgartirmaydi.

Kalit — (baytlar uzunligi, baytlar xeshi, parametrlar). Python bytes xeshini
bir marta hisoblab obyektda saqlaydi; 1-2 MB kadr uchun ~1 ms.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")

TTL_SECONDS = 20.0
MAX_ENTRIES = 512


class InferenceCache:
    def __init__(self, ttl_seconds: float = TTL_SECONDS, max_entries: int = MAX_ENTRIES) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._done: OrderedDict[tuple, tuple[float, Any]] = OrderedDict()
        self._pending: dict[tuple, asyncio.Future] = {}
        self.hits = 0
        self.misses = 0

    def _purge(self, now: float) -> None:
        while self._done:
            key, (stored_at, _) = next(iter(self._done.items()))
            if now - stored_at <= self._ttl and len(self._done) <= self._max:
                break
            self._done.popitem(last=False)

    async def get_or_run(self, frame: bytes, params: tuple, run: Callable[[], Awaitable[T]]) -> T:
        key = (len(frame), hash(frame), params)
        now = time.monotonic()
        self._purge(now)
        cached = self._done.get(key)
        if cached is not None:
            self.hits += 1
            return cached[1]
        pending = self._pending.get(key)
        if pending is not None:
            self.hits += 1
            return await asyncio.shield(pending)

        self.misses += 1
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[key] = future
        try:
            result = await run()
        except BaseException as exc:
            # Kutayotganlar ham xatoni oladi; keshga yozilmaydi (keyingi
            # so'rov qaytadan urinadi).
            if not future.done():
                future.set_exception(exc)
                future.exception()  # "never retrieved" ogohlantirishini o'chiradi
            raise
        else:
            future.set_result(result)
            self._done[key] = (time.monotonic(), result)
            return result
        finally:
            self._pending.pop(key, None)

    def clear(self) -> None:
        self._done.clear()
        self._pending.clear()
        self.hits = self.misses = 0


inference_cache = InferenceCache()
