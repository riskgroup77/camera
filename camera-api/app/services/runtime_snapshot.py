"""AI ish holati suratini API jarayonlari o'rtasida ulashish.

MUAMMO. Productionda WEB_CONCURRENCY=2: ikkita uvicorn jarayoni. AI
sweeplari faqat bittasida (leader, app/jobs/leader_lock.py) ishlaydi, lekin
yuz tanish statistikasi (recognition_stats) va sweep ko'rsatkichlari
(scheduler_metrics) o'sha jarayon XOTIRASIDA. HTTP so'rov esa ikkala
jarayondan biriga tasodifan tushadi — "Davomat kameralari" tashxisi va
boshqaruv panelidagi "N modul ishladi" taxminan har ikkinchi yangilashda
"hali tekshirilmadi" / "0 modul" bo'lib ko'rinardi.

YECHIM. Leader har SNAPSHOT_INTERVAL_SECONDS da suratni Redis'ga yozadi
(TTL bilan — leader o'lsa, eskirgan surat o'zi yo'qoladi). Leader o'z
xotirasidan o'qiydi, qolgan jarayonlar Redis'dan. Redis sozlanmagan yoki
ishlamayotgan bo'lsa — har jarayon o'z xotirasidan (bitta jarayonli
o'rnatishda bu to'g'ri javob).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time

from app.jobs import camera_health_metrics, scheduler_metrics
from app.jobs.scheduler_metrics import SweepRunStats
from app.jobs.sweep_concurrency import entrance_exit_sweep_concurrency_snapshot, sweep_concurrency_snapshot
from app.redis_bus import _get_redis, _redis_url
from app.services import recognition_stats
from app.services.gpu_status import get_gpu_status
from app.services.inference_gate import face_inference_gate
from app.services.recognition_stats import RecognitionView
from app.services.stream_cache import active_stream_reader_count

logger = logging.getLogger("app.runtime_snapshot")

KEY_RECOGNITION = "camera:runtime:recognition"
KEY_SWEEPS = "camera:runtime:sweeps"
# Leader jarayonining slotlari, inference navbati va GPU holati. Boshqaruv
# paneli bularni so'rov qaysi jarayonga tushganiga qarab 0/18 yoki 18/18
# deb ko'rsatardi — AI faqat leader'da ishlaydi, demak javob o'shaniki.
KEY_LEADER_PROCESS = "camera:runtime:leader_process"
# ffmpeg o'quvchilari HAR jarayonda bor (miniatyura, jonli aniqlash) —
# bu yerda jarayon -> "soni:epoch", panel yig'indini ko'rsatadi.
KEY_STREAM_READERS = "camera:runtime:stream_readers"
SNAPSHOT_INTERVAL_SECONDS = 5
SNAPSHOT_TTL_SECONDS = 60
# Shundan eski yozuv — to'xtagan jarayonniki, hisobga olinmaydi.
STREAM_READERS_FRESH_SECONDS = 20

# Shu jarayon suratni YOZUVCHI (leader) bo'lsa — o'z xotirasi eng yangi manba.
_is_publisher = False


def local_process_view() -> dict[str, object]:
    """Shu jarayonning AI resurslari — leader'da bu butun tizimning holati."""
    # Kech import: attendance_ai katta modul, bu yerdan yuqorida yuklash shart emas.
    from app.jobs.attendance_ai import entrance_watcher_count

    return {
        "sweep_slots": sweep_concurrency_snapshot(),
        "entrance_exit_sweep_slots": entrance_exit_sweep_concurrency_snapshot(),
        "face_inference_gate": face_inference_gate.snapshot(),
        "gpu": get_gpu_status(),
        "camera_health_sweep": camera_health_metrics.export_last_sweep(),
        "entrance_watchers": entrance_watcher_count(),
    }


async def publish_once() -> bool:
    client = await _get_redis()
    if client is None:
        return False
    recognition = json.dumps(recognition_stats.export_snapshot())
    sweeps = json.dumps(scheduler_metrics.export_sweeps())
    process = json.dumps(local_process_view())
    async with client.pipeline(transaction=False) as pipe:
        pipe.set(KEY_RECOGNITION, recognition, ex=SNAPSHOT_TTL_SECONDS)
        pipe.set(KEY_SWEEPS, sweeps, ex=SNAPSHOT_TTL_SECONDS)
        pipe.set(KEY_LEADER_PROCESS, process, ex=SNAPSHOT_TTL_SECONDS)
        await pipe.execute()
    return True


def _process_id() -> str:
    # Ikkala worker bitta konteynerda — xost nomi bir xil, pid farq qiladi.
    return f"{socket.gethostname()}:{os.getpid()}"


async def publish_stream_readers_once() -> bool:
    client = await _get_redis()
    if client is None:
        return False
    await client.hset(KEY_STREAM_READERS, _process_id(), f"{active_stream_reader_count()}:{int(time.time())}")
    return True


async def process_snapshot_loop() -> None:
    """HAR BIR jarayonda ishlaydi (app/main.py) — o'z o'quvchilari sonini e'lon qiladi."""
    if not _redis_url():
        return
    while True:
        try:
            await publish_stream_readers_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("stream reader count publish failed")
        await asyncio.sleep(SNAPSHOT_INTERVAL_SECONDS)


async def total_stream_readers() -> int:
    """Barcha jarayonlardagi ffmpeg o'quvchilari. Redis bo'lmasa — faqat shu jarayon."""
    total = active_stream_reader_count()
    if not _redis_url():
        return total
    client = await _get_redis()
    if client is None:
        return total
    try:
        rows = await client.hgetall(KEY_STREAM_READERS)
    except Exception:
        logger.exception("stream reader counts unavailable")
        return total
    own = _process_id()
    now = time.time()
    stale: list[str] = []
    for process, raw in rows.items():
        if process == own:
            continue
        count, _, stamp = str(raw).partition(":")
        try:
            readers, published_at = int(count), float(stamp)
        except ValueError:
            stale.append(process)
            continue
        if now - published_at > STREAM_READERS_FRESH_SECONDS:
            stale.append(process)
            continue
        total += readers
    if stale:
        try:
            await client.hdel(KEY_STREAM_READERS, *stale)
        except Exception:
            logger.debug("could not prune stale reader counts", exc_info=True)
    return total


async def runtime_snapshot_loop() -> None:
    """Faqat leader jarayonida ishga tushiriladi (app/main.py)."""
    global _is_publisher
    _is_publisher = True
    if not _redis_url():
        return  # bitta jarayon — ulashish shart emas, o'qish o'z xotirasidan
    while True:
        try:
            await publish_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("runtime snapshot publish failed")
        await asyncio.sleep(SNAPSHOT_INTERVAL_SECONDS)


async def _read_json(key: str):
    if _is_publisher or not _redis_url():
        return None
    client = await _get_redis()
    if client is None:
        return None
    try:
        raw = await client.get(key)
    except Exception:
        logger.exception("runtime snapshot read failed", extra={"key": key})
        return None
    return json.loads(raw) if raw else {}


async def load_recognition_views() -> dict[str, RecognitionView]:
    data = await _read_json(KEY_RECOGNITION)
    if data is None:
        return recognition_stats.local_views()
    views = (recognition_stats.view_from_dict(row) for row in data.values())
    return {camera_id: view for camera_id, view in zip(data.keys(), views, strict=True) if view is not None}


async def load_leader_process_view() -> dict[str, object]:
    data = await _read_json(KEY_LEADER_PROCESS)
    if not data:
        # Shu jarayon leader, Redis yo'q, yoki leader hali e'lon qilmagan.
        return local_process_view()
    return data


async def load_sweep_stats() -> list[SweepRunStats]:
    data = await _read_json(KEY_SWEEPS)
    if data is None:
        return scheduler_metrics.get_sweep_stats()
    return scheduler_metrics.sweeps_from_dicts(data if isinstance(data, list) else [])


def reset_for_tests() -> None:
    global _is_publisher
    _is_publisher = False
