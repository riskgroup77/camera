"""Kameralar salomatligi paneli uchun hisob-kitoblar.

Uch manba birlashtiriladi:
  * baza — last_seen_at / last_frame_at va camera_outages (uptime);
  * MediaMTX /v3/paths/list — jonli (`cam-<id>`) va yozuv (`rec-<id>`)
    yo'llari tayyormi, yozuv oqimi necha Mbit/s;
  * AI ish vaqti surati (runtime_snapshot) — kamera oxirgi marta qachon
    tahlil qilingan.

MediaMTX yetib bo'lmasa ham panel ochilishi shart (u aynan nosozlikni
qidirish uchun) — shuning uchun u tomondagi har qanday xato None bo'lib
qaytadi, istisno bo'lib emas.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.services import video_gateway

logger = logging.getLogger("app.camera_health_dashboard")

#: MediaMTX so'rovi uchun qisqa kutish — panel sekin shard sababli qotmasin.
MEDIAMTX_TIMEOUT_SECONDS = 2.0
#: Bitta sahifada so'raladigan yo'llar (standart 100; 100+ kamera x 2 yo'l).
_ITEMS_PER_PAGE = 1000
_MAX_PAGES = 20
#: Bundan qisqa oraliqdagi ikki namuna tezlikni hisoblash uchun ishonchsiz
#: (baytlar MediaMTX'da bo'laklab oshadi) — oldingi natija qaytariladi.
_MIN_SAMPLE_GAP_SECONDS = 5.0


def uptime_percent(
    intervals: list[tuple[datetime, datetime | None]],
    window_start: datetime,
    now: datetime,
) -> float:
    """[window_start, now] oynasida kamera necha foiz vaqt ishlagan.

    Oraliqlar oynaga qirqiladi va ustma-ust tushganlari birlashtiriladi
    (bitta uzilish ikki marta hisoblanmasin). ended_at None — davom
    etayotgan uzilish, `now` gacha."""
    total = (now - window_start).total_seconds()
    if total <= 0:
        return 100.0
    clipped: list[tuple[datetime, datetime]] = []
    for start, end in intervals:
        s = max(start, window_start)
        e = min(end or now, now)
        if e > s:
            clipped.append((s, e))
    clipped.sort()
    down = 0.0
    cur_s: datetime | None = None
    cur_e: datetime | None = None
    for s, e in clipped:
        if cur_e is None or s > cur_e:
            if cur_s is not None and cur_e is not None:
                down += (cur_e - cur_s).total_seconds()
            cur_s, cur_e = s, e
        elif e > cur_e:
            cur_e = e
    if cur_s is not None and cur_e is not None:
        down += (cur_e - cur_s).total_seconds()
    return round(max(0.0, min(100.0, 100.0 * (1 - down / total))), 2)


@dataclass(frozen=True)
class PathState:
    ready: bool
    bytes_received: int


async def _list_shard(client: httpx.AsyncClient, api_url: str) -> dict[str, PathState]:
    out: dict[str, PathState] = {}
    page = 0
    while page < _MAX_PAGES:
        resp = await client.get(
            f"{api_url}/v3/paths/list", params={"itemsPerPage": _ITEMS_PER_PAGE, "page": page}
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items") if isinstance(data, dict) else None
        for item in items if isinstance(items, list) else []:
            name = item.get("name") if isinstance(item, dict) else None
            if not isinstance(name, str):
                continue
            try:
                received = int(item.get("bytesReceived") or 0)
            except (TypeError, ValueError):
                received = 0
            out[name] = PathState(ready=bool(item.get("ready")), bytes_received=received)
        page_count = data.get("pageCount") if isinstance(data, dict) else None
        page += 1
        if not isinstance(page_count, int) or page >= page_count:
            break
    return out


async def fetch_mediamtx_paths() -> dict[str, PathState] | None:
    """Barcha shard'lardagi yo'llar, bir vaqtda so'raladi. Hech bir shard
    javob bermasa — None (panel "noma'lum" ko'rsatadi)."""
    shards = video_gateway._get_shards()
    async with httpx.AsyncClient(timeout=MEDIAMTX_TIMEOUT_SECONDS) as client:
        results = await asyncio.gather(
            *(_list_shard(client, shard.api_url) for shard in shards), return_exceptions=True
        )
    merged: dict[str, PathState] = {}
    any_ok = False
    for shard, result in zip(shards, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning("mediamtx paths list failed", extra={"api_url": shard.api_url, "error": str(result)})
            continue
        any_ok = True
        merged.update(result)
    return merged if any_ok else None


# path name -> (monotonic vaqt, bytesReceived, oxirgi hisoblangan Mbit/s)
_samples: dict[str, tuple[float, int, float | None]] = {}


def bitrate_mbps(name: str, bytes_received: int, *, now: float | None = None) -> float | None:
    """bytesReceived o'sishidan oqim tezligi (Mbit/s).

    MediaMTX faqat jami baytni beradi — tezlik uchun oldingi namuna kerak.
    U shu jarayon xotirasida turadi: panel 30s da bir yangilanadi, ya'ni
    birinchi ochilishda tezlik bo'sh, keyingisida to'ladi. Yo'l qayta
    ulansa hisoblagich nolga tushadi — o'shanda ham bir namuna bo'sh."""
    moment = time.monotonic() if now is None else now
    previous = _samples.get(name)
    if previous is None:
        _samples[name] = (moment, bytes_received, None)
        return None
    prev_t, prev_bytes, prev_rate = previous
    gap = moment - prev_t
    if gap < _MIN_SAMPLE_GAP_SECONDS:
        return prev_rate
    rate: float | None = None
    if bytes_received >= prev_bytes:
        rate = round((bytes_received - prev_bytes) * 8 / gap / 1_000_000, 2)
    _samples[name] = (moment, bytes_received, rate)
    return rate


def reset_for_tests() -> None:
    _samples.clear()
