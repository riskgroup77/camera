"""Kichik yuzni ASOSIY oqimdan "yaqinlashtirib" qayta tanish (zoom pass).

MUAMMO (production, 2026-09-20). Har bir kamera AI uchun MediaMTX orqali
1280x720 substream beradi. Bir kunda: 112433 kadr tahlil qilindi, 8884 yuz
topildi, ulardan 8079 tasi tanib bo'lmaydigan darajada kichik, yuz
balandligining medianasi 22 px, tanish esa 0 ta. Odamlar shiftdagi/fisheye
kameradan shunchaki uzoqda.

Kameraning ASOSIY oqimi 4K (2560-3840 px) — o'sha yuz u yerda ~3 barobar
katta (~66 px), ya'ni tanish mumkin. Lekin 4K ni DOIMIY o'qib bo'lmaydi:
VM protsessorida AVX yo'q (bitta kadr detektsiyasi 0.4-0.7 s) va tarmoq
ko'p 4K oqimni ko'tarmaydi — shuning uchun doimiy asosiy oqim o'chirilgan
(ai_main_stream_promotion_enabled=False, ai_perimeter_main_stream=False).

QAROR. Odatdagi 720p tekshiruvida "tanish uchun kichik, lekin haqiqiy yuz
bo'lishi uchun katta" ([face_zoom_min_px, face_analysis_min_px) oralig'i)
yuz ko'rinsa, shu kamera uchun BITTA asosiy oqim kadri olinadi va faqat
o'sha yuzlar atrofidagi hududlar qayta tahlil qilinadi
(_detect_faces_sync ning mavjud `roi` imkoniyati). Kadr kamera bo'yicha
face_zoom_interval_seconds da bir martadan tez-tez olinmaydi va bir
vaqtning o'zida face_zoom_max_concurrent_cameras kameradan ko'pi buni
qilmaydi — 4K yuklama shu ikki raqam bilan chegaralangan.

Bu modulda faqat sof (modelsiz, tarmoqsiz) qarorlar: qaysi yuz nomzod,
uning hududi qanday, va kimga hozir ruxsat beriladi. Kadr olish
app/services/frame_grabber.py da, ulash esa app/jobs/attendance_ai.py da.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager

from app.config import settings
from app.services.face_recognition import TRACK_IOU, Box, _iou

__all__ = ["zoom_candidate_boxes", "roi_for_box", "merge_zoom_faces", "zoom_limiter", "ZoomLimiter"]


def _height(box) -> float:
    return float(box[3]) - float(box[1])


def zoom_candidate_boxes(
    faces: list, *, min_px: int, floor_px: int, max_faces: int, matched: tuple = ()
) -> list[Box]:
    """"Tanib bo'lmaydigan, lekin haqiqiy" yuzlarning ramkalari.

    `matched` — shu kadrda ALLAQACHON tanilgan yuzlarning ramkalari: ular
    qayta yaqinlashtirilmaydi (davomati yozilgan, 4K kadr esa qimmat).

    Oraliq [floor_px, min_px): pastki chegara shovqinni (devordagi dog',
    stul suyanchig'i) kesadi, yuqorigisi — allaqachon tahlil qilingan
    yuzni qayta olmaslik uchun. Yuzlar kattaligi bo'yicha saralanadi (eng
    katta — eng ishonchli nomzod) va `max_faces` tasi qoladi: har bir
    hudud 4K kadrda alohida detektor chaqiruvi, ularning soni cheklanmasa
    bitta olomon kadri butun AI navbatini to'xtatib qo'yardi.

    Bo'sh ro'yxat — bu kamera uchun zoom keraksiz."""
    if max_faces <= 0 or floor_px <= 0 or floor_px >= min_px:
        return []
    # Embedding hisoblangan, lekin hech kimga mos kelmagan yuz ham nomzod:
    # 20-45 px oralig'ida vektor hisoblanadi, ammo u tanish uchun juda
    # shovqinli (2026-09-20: shunday 8884 yuzdan 0 ta moslik).
    candidates = [
        face.bbox
        for face in faces
        if not getattr(face, "tracked", False)
        and floor_px <= _height(face.bbox) < min_px
        and not any(_iou(face.bbox, box) >= TRACK_IOU for box in matched)
    ]
    candidates.sort(key=_height, reverse=True)
    return [tuple(float(v) for v in box[:4]) for box in candidates[:max_faces]]


def roi_for_box(box, width: int, height: int, *, margin: float) -> Box:
    """Piksel ramkasidan normallashgan (x1, y1, x2, y2) hudud.

    Ramka markazidan `margin` barobar kengaytiriladi: 22 pikselli yuzning
    o'z ramkasi juda tor — odam substream kadri olingandan keyin biroz
    siljigan bo'ladi, detektorga esa yuz atrofidagi kontekst kerak.
    Natija [0, 1] ga qisiladi va hech qachon bo'sh bo'lmaydi.

    Normallashgan bo'lgani uchun bir xil hudud BOSHQA o'lchamli kadrga
    ham to'g'ri tushadi — aynan shu kerak: ramka 1280x720 kadrdan, hudud
    esa 4K kadrga qo'llanadi."""
    if width <= 0 or height <= 0:
        return (0.0, 0.0, 1.0, 1.0)
    x1, y1, x2, y2 = (float(v) for v in box[:4])
    scale = max(1.0, margin)
    half_w = max((x2 - x1), 1.0) * scale / 2.0
    half_h = max((y2 - y1), 1.0) * scale / 2.0
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0

    def clamp(value: float) -> float:
        return min(1.0, max(0.0, value))

    nx1, ny1 = clamp((cx - half_w) / width), clamp((cy - half_h) / height)
    nx2, ny2 = clamp((cx + half_w) / width), clamp((cy + half_h) / height)
    # Butunlay kadrdan tashqarida qolgan ramka (kalibrlash xatosi) — hech
    # bo'lmaganda bir pikselli hudud qaytsin, aks holda qirqish bo'sh
    # massiv beradi.
    if nx2 <= nx1:
        nx1, nx2 = max(0.0, min(nx1, 1.0 - 1.0 / width)), min(1.0, nx1 + 1.0 / width)
    if ny2 <= ny1:
        ny1, ny2 = max(0.0, min(ny1, 1.0 - 1.0 / height)), min(1.0, ny1 + 1.0 / height)
    return (nx1, ny1, nx2, ny2)


def merge_zoom_faces(detections: list[list]) -> list:
    """Bir necha hududdan topilgan yuzlarni bitta ro'yxatga yig'adi.

    Hududlar kengaytirilgani uchun ustma-ust tushishi mumkin, ya'ni bitta
    odam ikki hududda ham topilishi mumkin — u bir marta qolsin (aks holda
    bir odam ikki marta solishtiriladi va log ikki marta yoziladi).
    Ramkalar to'liq kadr koordinatalarida (detect_faces shunday qaytaradi),
    shuning uchun ularni to'g'ridan-to'g'ri solishtirish mumkin."""
    merged: list = []
    for faces in detections:
        for face in faces:
            if any(_iou(face.bbox, kept.bbox) >= TRACK_IOU for kept in merged):
                continue
            merged.append(face)
    return merged


class ZoomLimiter:
    """4K yuklamani ikki tomondan cheklaydi: kamera bo'yicha oraliq va bir
    vaqtda zoom qilayotgan kameralar soni.

    Oddiy `threading.Lock` yetarli — barcha chaqiruvlar bitta event
    loop'dan keladi va qulf ichida hech narsa kutilmaydi."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_attempt: dict[str, float] = {}
        self._active = 0

    def reset(self) -> None:
        with self._lock:
            self._last_attempt.clear()
            self._active = 0

    @property
    def active(self) -> int:
        return self._active

    def _due(self, camera_id: str, now: float) -> bool:
        last = self._last_attempt.get(camera_id)
        return last is None or now - last >= settings.face_zoom_interval_seconds

    def acquire(self, camera_id: str, *, now: float | None = None) -> bool:
        """True — shu kamera hozir asosiy oqimdan kadr olishi mumkin.
        Ruxsat berilgan payt eslab qolinadi (urinish muvaffaqiyatsiz
        tugasa ham: kadr bermayotgan 4K oqimga har kadrda urinish aynan
        tejamoqchi bo'lgan tarmoqni yeydi)."""
        moment = time.monotonic() if now is None else now
        with self._lock:
            if not self._due(camera_id, moment):
                return False
            if self._active >= max(0, settings.face_zoom_max_concurrent_cameras):
                return False
            self._last_attempt[camera_id] = moment
            self._active += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)

    @contextmanager
    def slot(self, camera_id: str, *, now: float | None = None):
        """`with zoom_limiter.slot(id) as allowed:` — allowed False bo'lsa
        hech narsa qilinmaydi."""
        allowed = self.acquire(camera_id, now=now)
        try:
            yield allowed
        finally:
            if allowed:
                self.release()


zoom_limiter = ZoomLimiter()
