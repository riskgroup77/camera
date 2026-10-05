"""Klassik OpenCV hisoblari uchun cheklangan oqimlar havzasi.

Yong'in, tartib, jang, xalat va niqob modullari kadrni to'liq dekodlaydi,
HSV va optik oqim hisoblaydi. Bu ishlar ilgari event loop'ning o'zida
bajarilardi: Farneback bitta kamera uchun 432p da ~90 ms, 1440p da ~1 s
(o'lchangan) — shu vaqt ichida API, WebSocket va kirish davomati to'xtab
turardi.

asyncio.to_thread o'rniga ALOHIDA, kichik havza: standart havza 30 dan
ortiq oqimga ega va 40 ta kamera sloti bilan bir vaqtda o'nlab Farneback
ishga tushib, konteynerning CPU chegarasini (va yuz tanishni) bosib
ketardi. settings.cv_thread_pool_size — bir vaqtda nechta shunday hisob.
"""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from app.config import settings

T = TypeVar("T")

_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=max(1, settings.cv_thread_pool_size), thread_name_prefix="cv"
        )
    return _executor


async def run_cpu(func: Callable[..., T], *args) -> T:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_get_executor(), func, *args)


def shutdown_cpu_pool() -> None:
    global _executor
    executor, _executor = _executor, None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)
