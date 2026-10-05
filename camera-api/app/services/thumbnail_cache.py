"""Kamera miniatyurasi — AI sweep baribir oladigan kadrdan tayyorlanadi.

Monitoring markazining qavat gridi bir ekranda 20-30 kamerani
ko'rsatadi. Har biriga jonli HLS ochish MediaMTX'da o'shancha ffmpeg
transkodi degani — aynan biz qochmoqchi bo'lgan yuk (oldingi variantda
har tomoshabinga 9 ta oqim ochilardi). Buning o'rniga grid ~320px
JPEG rasmni bir necha soniyada yangilab turadi, jonli video esa faqat
operator tanlagan bitta kamerada ochiladi.

Kadr YANGIDAN olinmaydi: AI sweep'lar hammasi
frame_grabber.grab_frame_for_camera() orqali o'tadi va o'sha kadr shu
yerda keshlanadi. Ya'ni miniatyura kameraga qo'shimcha ulanish
qilmaydi. Sweep tegmagan kamera uchungina (moduldan chiqarilgan,
sinov kvotasi to'lgan va h.k.) endpoint bitta kadr so'raydi — u ham
kamera bo'yicha sovutish oynasi va global semafor ostida.

Redis bo'lsa ikkala uvicorn worker ham bir xil rasmni ko'radi: kadrni
AI leader worker oladi, HTTP so'roviga esa ikkinchisi javob berishi
mumkin. Redis bo'lmasa — jarayon ichidagi dict (dev, bitta worker).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from app.config import settings

logger = logging.getLogger("app.thumbnail")

_REDIS_KEY_PREFIX = "camera:thumb:"
# Oxirgi yaroqli kadr payti (epoch) — faqat raqam. camera_health "tasvir
# kelyaptimi" degan savolga shu orqali javob beradi: kadrni qaysi worker
# olgani muhim emas (camera_health.run_camera_health_sweep_once).
_FRAME_AT_KEY_PREFIX = "camera:frame_at:"

# Kesh: camera_id -> (epoch_seconds, jpeg). Redis yo'q bo'lganda ishlaydi.
_cache: dict[str, tuple[float, bytes]] = {}
# Oxirgi marta miniatyura YOZILGAN payt — har kadrda qayta siqmaslik uchun.
_last_stored: dict[str, float] = {}
# Sweep tegmagan kamera uchun kadr so'rash: bir vaqtda nechtasi mumkin.
_grab_semaphore: asyncio.Semaphore | None = None
_grab_started: dict[str, float] = {}
_redis = None
_redis_tried = False


async def _get_redis():
    global _redis, _redis_tried
    if _redis is not None or _redis_tried:
        return _redis
    _redis_tried = True
    url = (settings.redis_url or "").strip()
    if not url:
        return None
    try:
        from redis.asyncio import Redis

        # decode_responses=False: bu yerda JPEG baytlari saqlanadi,
        # matn emas — boshqa joydagi matnli klientdan farqi shu.
        client = Redis.from_url(url, decode_responses=False)
        await client.ping()
        _redis = client
    except Exception:
        logger.info("thumbnail cache: redis unavailable, using in-process cache")
        _redis = None
    return _redis


def _encode(stored_at: float, jpeg: bytes) -> bytes:
    return str(int(stored_at)).encode("ascii") + b"\n" + jpeg


def _decode(raw: bytes) -> tuple[float, bytes] | None:
    head, sep, jpeg = raw.partition(b"\n")
    if not sep or not jpeg:
        return None
    try:
        return float(head.decode("ascii")), jpeg
    except ValueError:
        return None


def _shrink(frame_bytes: bytes) -> bytes | None:
    """Kadrni miniatyura o'lchamiga keltiradi. Sinxron — chaqiruvchi buni
    alohida oqimda bajaradi, chunki JPEG dekodlash event loop'ni bloklaydi."""
    try:
        import cv2
        import numpy as np

        image = cv2.imdecode(np.frombuffer(frame_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return None
        height, width = image.shape[:2]
        target = max(64, settings.thumbnail_width)
        if width > target:
            image = cv2.resize(image, (target, max(1, round(height * target / width))), interpolation=cv2.INTER_AREA)
        ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), settings.thumbnail_quality])
        return buffer.tobytes() if ok else None
    except Exception:
        logger.debug("thumbnail encode failed", exc_info=True)
        return None


async def remember_frame(camera_id: str, frame_bytes: bytes) -> None:
    """AI kadr olganda chaqiriladi. Hech qachon xato ko'tarmaydi va
    sweep'ni sekinlashtirmasligi uchun kamera bo'yicha oraliq qo'yilgan:
    har kadrni emas, bir necha soniyada bittasini siqadi."""
    if not camera_id or not frame_bytes:
        return
    now = time.monotonic()
    previous = _last_stored.get(camera_id)
    if previous is not None and now - previous < settings.thumbnail_refresh_seconds:
        return
    _last_stored[camera_id] = now
    try:
        jpeg = await asyncio.to_thread(_shrink, frame_bytes)
        if jpeg is None:
            return
        await _store(camera_id, jpeg)
    except Exception:
        logger.debug("thumbnail store failed", exc_info=True)


async def _store(camera_id: str, jpeg: bytes) -> None:
    stored_at = time.time()
    _cache[camera_id] = (stored_at, jpeg)
    redis = await _get_redis()
    if redis is not None:
        await redis.setex(f"{_REDIS_KEY_PREFIX}{camera_id}", settings.thumbnail_ttl_seconds, _encode(stored_at, jpeg))
        await redis.setex(
            f"{_FRAME_AT_KEY_PREFIX}{camera_id}", max(1, settings.camera_video_stale_seconds), str(int(stored_at))
        )


async def frames_seen_at(camera_ids: list[str]) -> dict[str, float]:
    """Har bir kameraning oxirgi yaroqli kadri qachon olingan (epoch).

    Kadr AI sweep'da ham, miniatyura so'rovida ham olinadi va bu ikkisi
    turli worker'larda bo'lishi mumkin — shuning uchun javob Redis'dan
    (bitta MGET), u bo'lmasa jarayon ichidagi keshdan. Yozuvi yo'q
    kamera lug'atga kirmaydi."""
    seen = {cid: entry[0] for cid in camera_ids if (entry := _cache.get(cid)) is not None}
    redis = await _get_redis()
    if redis is None or not camera_ids:
        return seen
    try:
        values = await redis.mget([f"{_FRAME_AT_KEY_PREFIX}{cid}" for cid in camera_ids])
    except Exception:
        logger.debug("frame timestamps unavailable", exc_info=True)
        return seen
    for cid, raw in zip(camera_ids, values, strict=True):
        if not raw:
            continue
        try:
            moment = float(raw)
        except ValueError:
            continue
        seen[cid] = max(moment, seen.get(cid, 0.0))
    return seen


async def get_thumbnail(camera_id: str) -> tuple[bytes, int] | None:
    """(jpeg, necha soniya oldin olingan) yoki None."""
    redis = await _get_redis()
    if redis is not None:
        raw = await redis.get(f"{_REDIS_KEY_PREFIX}{camera_id}")
        if raw:
            decoded = _decode(raw)
            if decoded is not None:
                stored_at, jpeg = decoded
                return jpeg, max(0, int(time.time() - stored_at))
    entry = _cache.get(camera_id)
    if entry is None:
        return None
    stored_at, jpeg = entry
    return jpeg, max(0, int(time.time() - stored_at))


async def ensure_thumbnail(camera) -> tuple[bytes, int] | None:
    """Keshdagi rasm yetarlicha yangi bo'lsa — o'shani qaytaradi. Aks holda
    bitta kadr so'raydi.

    Ikki qulf bilan: bitta kamera uchun sovutish oynasi (bir nechta
    tomoshabin bir vaqtda ochsa ham bitta ulanish) va global semafor
    (butun grid birdaniga yangilanganda ham server bir necha ffmpeg'dan
    ortig'ini ko'tarmaydi)."""
    global _grab_semaphore

    camera_id = str(camera.id)
    cached = await get_thumbnail(camera_id)
    if cached is not None and cached[1] <= settings.thumbnail_stale_seconds:
        return cached

    now = time.monotonic()
    started = _grab_started.get(camera_id)
    if started is not None and now - started < settings.thumbnail_refresh_seconds:
        return cached  # boshqa so'rov hozir olyapti yoki yaqinda urinib ko'rildi
    _grab_started[camera_id] = now

    if _grab_semaphore is None:
        _grab_semaphore = asyncio.Semaphore(max(1, settings.thumbnail_grab_concurrency))
    if _grab_semaphore.locked() and cached is not None:
        return cached  # navbat band — eski rasm hech yo'qdan yaxshi

    # Aylanma importdan qochish uchun shu yerda: frame_grabber o'zi
    # remember_frame() ni chaqiradi.
    from app.services.frame_grabber import frame_wait_seconds_for_camera, grab_frame_for_camera

    async with _grab_semaphore:
        try:
            frame = await grab_frame_for_camera(camera, wait_seconds=min(4.0, frame_wait_seconds_for_camera(camera)))
        except Exception:
            logger.debug("thumbnail grab failed", exc_info=True)
            return cached
    if frame is None:
        return cached
    jpeg = await asyncio.to_thread(_shrink, frame)
    if jpeg is None:
        return cached
    await _store(camera_id, jpeg)
    _last_stored[camera_id] = time.monotonic()
    return jpeg, 0


def thumbnail_age_header(age_seconds: int) -> str:
    return datetime.fromtimestamp(time.time() - age_seconds, tz=timezone.utc).isoformat()


def reset_thumbnail_cache_for_tests() -> None:
    _cache.clear()
    _last_stored.clear()
    _grab_started.clear()
