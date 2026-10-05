"""Operator kuzatayotgan kamera — real vaqtdagi yuz skaneri.

MUAMMO (2026-09-24 o'lchovi). Operator kamerani ochganda video ustidagi
"Skanerlanmoqda…" 5-12 s turardi, keyin natija har 6-12 s da yangilanardi:
har so'rovda API konteyneri o'zi 4K oqimga ulanib (birinchi kadr 3-6 s),
kadrni noldan tahlil qilardi (AVX'siz CPU'da aniqlash 1.7 s + har yuzga
~0.6 s). Shu paytning o'zida ai-worker o'sha kamerani baribir o'qib,
tahlil qilib turardi — ish ikki marta bajarilardi, natija esa kechikardi.

YECHIM. Skaner ai-worker'ning doimiy kuzatuvchisidan oziqlanadi:
  * API `mark_focus()` bilan "bu kamerani operator ko'ryapti" deb belgilaydi
    (Redis, qisqa TTL — so'rovlar to'xtasa o'zi o'chadi);
  * ai-worker o'sha kamerada kutishni bekor qiladi, uni eng yuqori
    navbat bilan va har yangi kadrda tahlil qiladi, natijani (ramkalar,
    ismlar) `publish_result()` bilan yozadi;
  * API natijani shunchaki o'qiydi — so'rov millisoniyalarda qaytadi.

Redis bo'lmasa (dev, testlar) — jarayon ichidagi dict: API va kuzatuvchi
bir jarayonda bo'lganda ham xuddi shunday ishlaydi."""

from __future__ import annotations

import json
import logging
import time
from collections import deque

from app.config import settings

logger = logging.getLogger("app.live_focus")

_FOCUS_KEY = "camera:focus"  # zset: camera_id -> amal qilish muddati (epoch)
# Shu kameralarni operator HLS orqali ko'ryapti (WebRTC ishlamagan) — faqat
# ularda video soati farqi o'lchanadi (app/services/live_clock.py).
_HLS_KEY = "camera:focus:hls"
_RESULT_PREFIX = "camera:live:"
_HISTORY_SUFFIX = ":h"
# Brauzer ramkalarni ikki natija orasida silliq siljitadi (interpolatsiya) —
# buning uchun oxirgi bir necha natija kerak (~1 s oraliqda, ~10 s).
HISTORY_LENGTH = 10

_focus_local: dict[str, float] = {}
_hls_local: dict[str, float] = {}
_hls_snapshot: tuple[float, frozenset[str]] = (0.0, frozenset())
_results_local: dict[str, dict] = {}
_history_local: dict[str, deque] = {}
# ai-worker har kadrda Redis'ga murojaat qilmasin: ro'yxat qisqa muddat eslanadi.
_focus_snapshot: tuple[float, frozenset[str]] = (0.0, frozenset())
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

        client = Redis.from_url(url, decode_responses=True)
        await client.ping()
        _redis = client
    except Exception:
        logger.warning("live focus: redis unavailable, using in-process state", exc_info=True)
        _redis = None
    return _redis


async def mark_focus(camera_id: str, *, hls: bool = False) -> None:
    """Operator shu kamerani ko'ryapti — keyingi live_focus_ttl_seconds davomida.
    `hls` — video HLS orqali (vaqt belgisi farqini o'lchash kerak)."""
    until = time.time() + settings.live_focus_ttl_seconds
    client = await _get_redis()
    if client is None:
        _focus_local[camera_id] = until
        if hls:
            _hls_local[camera_id] = until
        return
    try:
        async with client.pipeline(transaction=False) as pipe:
            pipe.zadd(_FOCUS_KEY, {camera_id: until})
            pipe.zremrangebyscore(_FOCUS_KEY, "-inf", time.time())
            if hls:
                pipe.zadd(_HLS_KEY, {camera_id: until})
            pipe.zremrangebyscore(_HLS_KEY, "-inf", time.time())
            await pipe.execute()
    except Exception:
        logger.warning("live focus: mark failed", exc_info=True)


async def focused_cameras() -> frozenset[str]:
    """Hozir kuzatilayotgan kameralar. Natija live_focus_poll_seconds
    davomida eslanadi — 107 ta kuzatuvchi har kadrda so'rasa ham Redis'ga
    soniyasiga bir-ikki murojaat bo'ladi."""
    global _focus_snapshot
    now = time.time()
    fetched_at, cameras = _focus_snapshot
    if now - fetched_at < settings.live_focus_poll_seconds:
        return cameras
    client = await _get_redis()
    if client is None:
        cameras = frozenset(cid for cid, until in _focus_local.items() if until > now)
    else:
        try:
            cameras = frozenset(await client.zrangebyscore(_FOCUS_KEY, now, "+inf"))
        except Exception:
            logger.warning("live focus: read failed", exc_info=True)
    _focus_snapshot = (now, cameras)
    return cameras


async def is_focused(camera_id: str) -> bool:
    return camera_id in await focused_cameras()


async def watched_over_hls(camera_id: str) -> bool:
    """Operator bu kamerani HLS orqali ko'ryaptimi (qisqa muddat eslanadi)."""
    global _hls_snapshot
    now = time.time()
    fetched_at, cameras = _hls_snapshot
    if now - fetched_at >= settings.live_focus_poll_seconds:
        client = await _get_redis()
        if client is None:
            cameras = frozenset(cid for cid, until in _hls_local.items() if until > now)
        else:
            try:
                cameras = frozenset(await client.zrangebyscore(_HLS_KEY, now, "+inf"))
            except Exception:
                logger.warning("live focus: hls read failed", exc_info=True)
        _hls_snapshot = (now, cameras)
    return camera_id in cameras


async def publish_result(camera_id: str, payload: dict) -> None:
    """Kuzatuvchining oxirgi kadr natijasi (LiveDetectionOut shaklida)."""
    payload = {**payload, "analysed_at": time.time()}
    payload.setdefault("captured_at", payload["analysed_at"])
    client = await _get_redis()
    if client is None:
        _results_local[camera_id] = payload
        _history_local.setdefault(camera_id, deque(maxlen=HISTORY_LENGTH)).append(payload)
        return
    encoded = json.dumps(payload)
    history_key = _RESULT_PREFIX + camera_id + _HISTORY_SUFFIX
    try:
        async with client.pipeline(transaction=False) as pipe:
            pipe.set(_RESULT_PREFIX + camera_id, encoded, ex=settings.live_result_ttl_seconds)
            pipe.lpush(history_key, encoded)
            pipe.ltrim(history_key, 0, HISTORY_LENGTH - 1)
            pipe.expire(history_key, settings.live_result_ttl_seconds)
            await pipe.execute()
    except Exception:
        logger.warning("live focus: publish failed", exc_info=True)


async def recent_results(camera_id: str, *, max_age_seconds: float) -> list[dict]:
    """Oxirgi natijalar, eskisidan yangisiga (captured_at bo'yicha)."""
    client = await _get_redis()
    if client is None:
        items = list(_history_local.get(camera_id, ()))
    else:
        try:
            raw = await client.lrange(_RESULT_PREFIX + camera_id + _HISTORY_SUFFIX, 0, HISTORY_LENGTH - 1)
        except Exception:
            logger.warning("live focus: history read failed", exc_info=True)
            return []
        items = [json.loads(item) for item in raw]
    now = time.time()
    fresh = [item for item in items if now - float(item.get("analysed_at") or 0) <= max_age_seconds]
    return sorted(fresh, key=lambda item: float(item.get("captured_at") or 0))


async def latest_result(camera_id: str, *, max_age_seconds: float) -> dict | None:
    """Yetarlicha yangi natija yoki None."""
    client = await _get_redis()
    if client is None:
        payload = _results_local.get(camera_id)
    else:
        try:
            raw = await client.get(_RESULT_PREFIX + camera_id)
        except Exception:
            logger.warning("live focus: result read failed", exc_info=True)
            return None
        payload = json.loads(raw) if raw else None
    if not payload:
        return None
    if time.time() - float(payload.get("analysed_at") or 0) > max_age_seconds:
        return None
    return payload


def reset_for_tests() -> None:
    global _focus_snapshot, _hls_snapshot, _redis, _redis_tried
    _hls_local.clear()
    _hls_snapshot = (0.0, frozenset())
    _focus_local.clear()
    _results_local.clear()
    _history_local.clear()
    _focus_snapshot = (0.0, frozenset())
    _redis = None
    _redis_tried = False
