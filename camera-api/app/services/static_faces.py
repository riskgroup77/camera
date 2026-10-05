"""Devordagi rasm ("statik yuz") ni tirik odamdan ajratish.

MUAMMO (production, 2026-09-20, yakshanba — bino bo'sh). Bir kunda 1555 ta
"yuz" topildi, 290 marta asosiy oqimdan 4K kadr olindi (zoom pass), moslik
esa 0 ta. Kesimlar ko'rildi: ular ma'lumot stendidagi xodimlar surati va
anatomiya plakatidagi chizma. Ya'ni AI ishining sezilarli qismi — jumladan
eng qimmat 4K yaqinlashtirish (app/services/face_zoom.py) — har safar,
abadiy, devordagi rasmni qayta ko'rishga ketardi. Tashxis raqamlari ham
buziladi: odam statistikaga qarab "bu kamera odamni ko'ryaptimi yoki
plakatnimi" deb ayta olmaydi.

QAROR. Rasm — bu PIKSEL ANIQLIGIDA qimirlamaydigan yuz. Kamera bo'yicha
har bir yuz ramkasi eslab qolinadi; agar o'sha joyda (IoU >=
static_face_iou) yuz ko'p marta, uzoq vaqt oralig'ida takrorlansa, u
"statik" deb belgilanadi. Undan keyin o'sha ramkadagi yuz:

  * embedding olmaydi (detect_faces ning `skip_boxes` i orqali),
  * hech kim bilan solishtirilmaydi,
  * va eng muhimi — hech qachon 4K zoom chaqirmaydi.

TIRIK ODAMNI QAMAB QO'YMASLIK. Uch himoya:

  1. Chegaralar dars davomiyligidan uzun (config izohiga qarang): dars
     tugaydi, plakat esa tugamaydi.
  2. O'sha joydagi yuz BIR MARTA bo'lsa ham odamga mos kelgan bo'lsa,
     ramka darhol unutiladi va static_face_person_memory_seconds davomida
     qayta statik bo'la olmaydi.
  3. Statik ramka static_face_expire_seconds ko'rinmasa o'chadi (stend
     olib tashlandi, kamera burildi).

Hammasi xotirada (DB emas), kamera bo'yicha va umumiy soni chegaralangan.
Modelsiz, tarmoqsiz — faqat ramkalar ustida arifmetika.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from app.config import settings
from app.services.face_recognition import Box, _iou

__all__ = ["StaticBox", "StaticFaceStore", "static_face_store"]


def _box(bbox) -> Box:
    return tuple(float(v) for v in bbox[:4])


def box_height_px(bbox) -> int:
    return max(0, int(float(bbox[3]) - float(bbox[1])))


@dataclass
class StaticBox:
    """Bir kameradagi bitta "qimirlamaydigan" ramka.

    `static` False bo'lsa — hali shunchaki nomzod (kuzatuvdagi ramka)."""

    bbox: Box
    first_seen: float
    last_seen: float
    hits: int = 1
    static: bool = False

    @property
    def height_px(self) -> int:
        return box_height_px(self.bbox)

    @property
    def span_seconds(self) -> float:
        return self.last_seen - self.first_seen


@dataclass
class _CameraMemory:
    boxes: list[StaticBox] = field(default_factory=list)
    # Odam tanilgan joylar: (ramka, qachongacha statik bo'lish taqiqlangan).
    people: list[tuple[Box, float]] = field(default_factory=list)
    touched: float = 0.0


class StaticFaceStore:
    """Kamera -> statik ramkalar xotirasi.

    Oddiy `threading.Lock` yetarli: qulf ichida hech narsa kutilmaydi,
    barcha amallar bir nechta ramka ustidagi sanoq."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cameras: dict[str, _CameraMemory] = {}

    # ── xizmat ──────────────────────────────────────────────────────────
    def clear(self) -> None:
        with self._lock:
            self._cameras.clear()

    def camera_count(self) -> int:
        with self._lock:
            return len(self._cameras)

    def _memory(self, camera_key: str, now: float) -> _CameraMemory:
        memory = self._cameras.get(camera_key)
        if memory is None:
            # Umumiy chegara: eng uzoq vaqt tegilmagan kamera unutiladi.
            # Kamera ro'yxati o'zgarib turadi (import, o'chirish), xotira
            # esa cheksiz o'smasligi kerak.
            limit = max(1, settings.static_face_max_cameras)
            while len(self._cameras) >= limit:
                oldest = min(self._cameras, key=lambda key: self._cameras[key].touched)
                del self._cameras[oldest]
            memory = _CameraMemory()
            self._cameras[camera_key] = memory
        memory.touched = now
        return memory

    def _expire(self, memory: _CameraMemory, now: float) -> None:
        """Ko'rinmay qolgan ramkalar va eskirgan "bu yerda odam bor" belgilari."""
        ttl = settings.static_face_expire_seconds
        memory.boxes = [b for b in memory.boxes if now - b.last_seen <= ttl]
        memory.people = [(box, until) for box, until in memory.people if until > now]

    def _blocked(self, memory: _CameraMemory, bbox) -> bool:
        return any(_iou(bbox, box) >= settings.static_face_iou for box, _ in memory.people)

    # ── o'qish ──────────────────────────────────────────────────────────
    def static_boxes(self, camera_key: str | None, *, now: float | None = None) -> tuple[Box, ...]:
        """Shu kamerada hozir statik hisoblanadigan ramkalar.

        detect_faces ga `skip_boxes` sifatida beriladi — shunda rasm uchun
        ArcFace umuman chaqirilmaydi."""
        if camera_key is None or not settings.static_face_skip_enabled:
            return ()
        moment = time.monotonic() if now is None else now
        with self._lock:
            memory = self._cameras.get(camera_key)
            if memory is None:
                return ()
            self._expire(memory, moment)
            return tuple(b.bbox for b in memory.boxes if b.static)

    def static_heights(self, camera_key: str | None) -> list[int]:
        """Statik ramkalarning piksel balandligi — tashxisda odam yuzining
        medianasi bilan solishtirish uchun ("stenddagi suratlar bu kameraga
        tirik yuzdan kattaroq ko'rinadi")."""
        if camera_key is None:
            return []
        with self._lock:
            memory = self._cameras.get(camera_key)
            return [b.height_px for b in memory.boxes if b.static] if memory else []

    # ── yozish ──────────────────────────────────────────────────────────
    def split(self, camera_key: str | None, faces: list, *, now: float | None = None) -> tuple[list, list]:
        """Yuzlarni (tirik nomzodlar, statik) ga ajratadi.

        Statik deb topilgan yuzning ramkasi yangilanadi (ko'rinish vaqti va
        soni), ya'ni plakat ko'rinib turgan ekan u eskirmaydi."""
        if camera_key is None or not settings.static_face_skip_enabled or not faces:
            return list(faces), []
        moment = time.monotonic() if now is None else now
        threshold = settings.static_face_iou
        with self._lock:
            memory = self._cameras.get(camera_key)
            if memory is None:
                return list(faces), []
            self._expire(memory, moment)
            memory.touched = moment
            fresh: list = []
            skipped: list = []
            for face in faces:
                hit = next(
                    (b for b in memory.boxes if b.static and _iou(face.bbox, b.bbox) >= threshold),
                    None,
                )
                if hit is None:
                    fresh.append(face)
                    continue
                hit.last_seen = moment
                hit.hits += 1
                skipped.append(face)
            return fresh, skipped

    def note_matched(self, camera_key: str | None, boxes, *, now: float | None = None) -> None:
        """Shu ramkalarda HAQIQIY odam tanildi.

        Nomzod (yoki hatto statik) ramka darhol unutiladi va bir muddat
        qayta statik bo'la olmaydi — stulda uzoq o'tirgan odamni rasm deb
        belgilab qo'yish eng xavfli xato."""
        if camera_key is None or not boxes:
            return
        moment = time.monotonic() if now is None else now
        threshold = settings.static_face_iou
        until = moment + settings.static_face_person_memory_seconds
        with self._lock:
            memory = self._memory(camera_key, moment)
            self._expire(memory, moment)
            for bbox in boxes:
                box = _box(bbox)
                memory.boxes = [b for b in memory.boxes if _iou(box, b.bbox) < threshold]
                memory.people = [(b, u) for b, u in memory.people if _iou(box, b) < threshold]
                memory.people.append((box, until))
            limit = max(1, settings.static_face_max_boxes_per_camera)
            if len(memory.people) > limit:
                del memory.people[: len(memory.people) - limit]

    def observe(self, camera_key: str | None, faces: list, *, now: float | None = None) -> list[StaticBox]:
        """Tanilmagan yuzlarni kuzatuvga oladi; YANGI statik bo'lganlarni qaytaradi.

        Bitta kadrda bir ramka ko'pi bilan bir marta sanaladi (`claimed`), va
        ikki sanoq orasida static_face_min_gap_seconds bo'lishi shart —
        sekundiga bir kadr o'qiydigan kuzatuvchi (kirish kamerasi) sanoqni
        bir necha daqiqada to'ldirib yubormasligi uchun."""
        if camera_key is None or not settings.static_face_skip_enabled or not faces:
            return []
        moment = time.monotonic() if now is None else now
        threshold = settings.static_face_iou
        gap = settings.static_face_min_gap_seconds
        min_hits = max(2, settings.static_face_min_hits)
        min_span = settings.static_face_min_span_seconds
        promoted: list[StaticBox] = []
        with self._lock:
            memory = self._memory(camera_key, moment)
            self._expire(memory, moment)
            claimed: set[int] = set()
            for face in faces:
                bbox = _box(face.bbox)
                if self._blocked(memory, bbox):
                    continue
                index = next(
                    (
                        i
                        for i, b in enumerate(memory.boxes)
                        if i not in claimed and _iou(bbox, b.bbox) >= threshold
                    ),
                    None,
                )
                if index is None:
                    if len(memory.boxes) >= max(1, settings.static_face_max_boxes_per_camera):
                        # Chegara to'ldi: faqat eng kam ishonchli (statik
                        # bo'lmagan, eng eski ko'ringan) nomzod chiqariladi.
                        weak = [i for i, b in enumerate(memory.boxes) if not b.static]
                        if not weak:
                            continue
                        del memory.boxes[min(weak, key=lambda i: memory.boxes[i].last_seen)]
                        claimed = set()
                    memory.boxes.append(StaticBox(bbox=bbox, first_seen=moment, last_seen=moment))
                    claimed.add(len(memory.boxes) - 1)
                    continue
                claimed.add(index)
                tracked = memory.boxes[index]
                if moment - tracked.last_seen < gap:
                    continue
                tracked.last_seen = moment
                tracked.hits += 1
                # Ramka sekin "suzib" ketmasligi uchun boshlang'ich
                # koordinatalar saqlanadi: IoU baribir har safar asl
                # ramkaga nisbatan tekshiriladi.
                if not tracked.static and tracked.hits >= min_hits and tracked.span_seconds >= min_span:
                    tracked.static = True
                    promoted.append(tracked)
        return promoted


static_face_store = StaticFaceStore()


def reset_for_tests() -> None:
    static_face_store.clear()
