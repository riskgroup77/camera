"""Yuz ko'rinadigan, lekin kichikligi sababli tanilmaydigan xona kameralarini
byudjet doirasida ASOSIY oqimga o'tkazish.

Production (2026-09-19): 107 kameraning 99 tasi AI uchun 640x360
substreamdan o'qiladi; yuzlar 8-20 px, tanish chegarasi esa 40 px. Tarmoq
hamma kameraning asosiy oqimini ko'tarmaydi (ai_room_cameras_main_stream=False),
lekin bir nechtasini ko'taradi. Asosiy oqim (1920x1080 / 2560x1440) da
o'sha yuz 3-4 barobar katta — 12-15 px lik yuz 40-60 px bo'ladi.

Tanlov bugungi statistikadan (app/services/recognition_stats.py):
yetarlicha yuz ko'ringan (>= ai_main_stream_promotion_min_faces) va ularning
median balandligi [min_px, max_px) oralig'ida — ya'ni odamlar bor, lekin
substream ularni tanishga yetmaydi. Ko'p yuz ko'rgan kameralar birinchi.

Tanlangan kamera kamida ai_main_stream_promotion_hold_seconds asosiy oqimda
qoladi; muddat tugaganda shu davrda yana yuz ko'ringan bo'lsa qoladi, aks
holda bo'shatiladi va shuncha vaqt qayta tanlanmaydi (tebranish bo'lmasin).
Asosiy oqim kadr bermasa — frame_grabber'ning mavjud zaxira mexanizmi
(substreamga qaytish) ishlaydi.
"""

import threading
import time
from dataclasses import dataclass

from app.config import settings
from app.services import recognition_stats


@dataclass
class _Promotion:
    since: float
    faces_at_start: int


_lock = threading.Lock()
_promoted: dict[str, _Promotion] = {}
_cooldown_until: dict[str, float] = {}
_room_cameras: set[str] = set()
_last_refresh = [0.0]


def reset_for_tests() -> None:
    with _lock:
        _promoted.clear()
        _cooldown_until.clear()
        _room_cameras.clear()
        _last_refresh[0] = 0.0


def promoted_cameras() -> list[str]:
    with _lock:
        return sorted(_promoted)


def _faces(camera_id: str) -> int:
    stats = recognition_stats.snapshot(camera_id)
    return stats.faces if stats is not None else 0


def _eligible(camera_id: str) -> bool:
    stats = recognition_stats.snapshot(camera_id)
    if stats is None or stats.faces < settings.ai_main_stream_promotion_min_faces:
        return False
    px = stats.face_px_median
    if px is None:
        return False
    return settings.ai_main_stream_promotion_min_px <= px < settings.ai_main_stream_promotion_max_px


def refresh(now: float | None = None) -> None:
    """Tanlovni qayta ko'rib chiqadi (qulf ichida, arzon — faqat xotira)."""
    moment = time.monotonic() if now is None else now
    hold = settings.ai_main_stream_promotion_hold_seconds
    budget = max(0, settings.ai_main_stream_promotion_budget)
    with _lock:
        _last_refresh[0] = moment
        for camera_id, promotion in list(_promoted.items()):
            if moment - promotion.since < hold:
                continue
            gained = _faces(camera_id) - promotion.faces_at_start
            if gained >= max(1, settings.ai_main_stream_promotion_min_faces // 2):
                _promoted[camera_id] = _Promotion(moment, _faces(camera_id))
            else:
                del _promoted[camera_id]
                _cooldown_until[camera_id] = moment + hold
        while len(_promoted) > budget:
            # Byudjet kamaytirilgan — eng oxirgi tanlanganlar bo'shatiladi.
            newest = max(_promoted, key=lambda key: _promoted[key].since)
            del _promoted[newest]
        free = budget - len(_promoted)
        if free <= 0:
            return
        candidates = [
            camera_id
            for camera_id in _room_cameras
            if camera_id not in _promoted
            and _cooldown_until.get(camera_id, 0.0) <= moment
            and _eligible(camera_id)
        ]
        candidates.sort(key=_faces, reverse=True)
        for camera_id in candidates[:free]:
            _promoted[camera_id] = _Promotion(moment, _faces(camera_id))


def is_promoted(camera_id: str, now: float | None = None) -> bool:
    """Xona kamerasi hozir asosiy oqimdan o'qilsinmi. Faqat xona kameralari
    uchun chaqiriladi (kirish/perimetr kameralari allaqachon asosiy oqimda)."""
    if not settings.ai_main_stream_promotion_enabled or settings.ai_main_stream_promotion_budget <= 0:
        return False
    moment = time.monotonic() if now is None else now
    with _lock:
        _room_cameras.add(camera_id)
        due = moment - _last_refresh[0] >= settings.ai_main_stream_promotion_refresh_seconds
    if due:
        refresh(moment)
    with _lock:
        return camera_id in _promoted
