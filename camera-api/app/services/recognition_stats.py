"""Yuzni tanish statistikasi (har kamera, bugungi kun) va "yumshoq"
mosliklarni takroriy ko'rinish bilan tasdiqlash.

NEGA KERAK. Davomatda "tizimdan o'tganlar ko'p, lekin hech kim davomatga
tushmayapti" holatida savol har doim bir xil: kamera yuzni ko'rmayaptimi,
ko'rib tanimayaptimi yoki umuman tekshirilmayaptimi? Bu modul uchalasini
raqam bilan ko'rsatadi:

  * frames / faces     — kamera tekshirildimi, kadrda yuz bormi;
  * face_px_median     — yuz necha piksel (40 dan kichik yuz tanilmaydi);
  * similarity buckets — eng yaqin nomzodga o'xshashlik taqsimoti: agar
    ko'pchilik 0.47-0.55 oralig'ida bo'lsa, chegara juda qat'iy;
  * strict / relaxed_confirmed / relaxed_pending — nechta moslik yozildi.

Hammasi xotirada (DB emas): bu tashxis uchun, bir necha soniyada
yangilanadi va qayta ishga tushganda nol bo'ladi.

YUMSHOQ MOSLIKNI TASDIQLASH. relaxed moslik (face_matching.graded_matches)
bitta kadrning o'zida yetarli emas. Xuddi shu odam
settings.attendance_relaxed_confirm_window_seconds ichida YANA bir marta
(boshqa kadrda, istalgan kamerada) yumshoq yoki qat'iy mos kelsagina
davomatga yoziladi. Tasodifiy o'xshash begona odam ketma-ket ikki kadrda
bir xil ro'yxatdagi odamga eng yaqin bo'lib chiqishi ehtimoli juda past.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import median

from app.config import settings
from app.timezone import local_now
from app.timezone import business_today

SIMILARITY_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("<0.30", -2.0, 0.30),
    ("0.30-0.40", 0.30, 0.40),
    ("0.40-0.47", 0.40, 0.47),
    ("0.47-0.55", 0.47, 0.55),
    (">=0.55", 0.55, 2.0),
)


@dataclass
class CameraRecognitionStats:
    day: date
    frames: int = 0
    frames_with_faces: int = 0
    faces: int = 0
    small_faces: int = 0
    strict: int = 0
    relaxed_confirmed: int = 0
    relaxed_pending: int = 0
    best_similarity: float = -1.0
    last_frame_at: datetime | None = None
    last_face_at: datetime | None = None
    last_match_at: datetime | None = None
    buckets: dict[str, int] = field(default_factory=lambda: {name: 0 for name, _, _ in SIMILARITY_BUCKETS})
    # Kamera bir marta to'liq tekshirilishi (kadr olish + tahlil) necha soniya.
    cycles: int = 0
    last_cycle_seconds: float | None = None
    last_grab_seconds: float | None = None
    # AI qaysi oqimni o'qiyapti: "asosiy", "substream" yoki "substream (zaxira)".
    stream: str | None = None
    # Harakat yo'qligi sababli tahlil qilinmagan kadrlar (app/services/motion_gate.py)
    # va allaqachon tanilgan odam sifatida qayta hisoblanmagan yuzlar (tracking).
    motion_skipped: int = 0
    tracked_faces: int = 0
    # Yaroqli yuz bermagani uchun navbatni bo'shatib kutgan marta va
    # soniyalar (app/services/camera_pacing.py).
    idle_waits: int = 0
    idle_seconds: float = 0.0
    # Asosiy oqimdan yaqinlashtirib tanish (app/services/face_zoom.py):
    # nechta 4K kadr olindi, unda nechta yuz topildi, nechtasi davomatga
    # yozildi va o'sha yuzlar necha piksel edi. Aynan shu to'rt raqam
    # "zoom ishladimi" degan savolga javob beradi.
    zoom_attempts: int = 0
    zoom_faces: int = 0
    zoom_matches: int = 0
    # Devordagi rasm sifatida o'tkazib yuborilgan yuzlar va hozir shu
    # kamerada nechta statik ramka eslanayotgani (app/services/static_faces.py).
    # static_px_median ni face_px_median bilan solishtirish mumkin: stenddagi
    # surat ko'pincha tirik yuzdan kattaroq ko'rinadi.
    static_faces: int = 0
    static_boxes: int = 0
    _face_heights: deque[int] = field(default_factory=lambda: deque(maxlen=500))
    _zoom_heights: deque[int] = field(default_factory=lambda: deque(maxlen=500))
    _static_heights: tuple[int, ...] = ()

    @property
    def face_px_median(self) -> int | None:
        return int(median(self._face_heights)) if self._face_heights else None

    @property
    def zoom_px_median(self) -> int | None:
        return int(median(self._zoom_heights)) if self._zoom_heights else None

    @property
    def static_px_median(self) -> int | None:
        return int(median(self._static_heights)) if self._static_heights else None


_stats: dict[str, CameraRecognitionStats] = {}
# person_id -> monotonic vaqt: yumshoq moslik birinchi marta ko'ringan payt.
_pending_relaxed: dict[str, float] = {}
# person_id -> birinchi yumshoq ko'rinish qaysi kamerada bo'lgani.
_pending_camera: dict[str, str | None] = {}


def _bucket(similarity: float) -> str:
    for name, low, high in SIMILARITY_BUCKETS:
        if low <= similarity < high:
            return name
    return SIMILARITY_BUCKETS[-1][0]


def _camera_stats(camera_id: str) -> CameraRecognitionStats:
    today = business_today()
    current = _stats.get(camera_id)
    if current is None or current.day != today:
        current = CameraRecognitionStats(day=today)
        _stats[camera_id] = current
    return current


def face_height_px(face) -> int:
    bbox = getattr(face, "bbox", None)
    if bbox is None or len(bbox) < 4:
        return 0
    return max(0, int(bbox[3] - bbox[1]))


def record_frame(camera_id: str | None, faces: list, graded: list) -> None:
    """Bitta tahlil qilingan kadr natijasini qayd etadi (yuz bo'lmasa ham)."""
    if camera_id is None:
        return
    stats = _camera_stats(camera_id)
    now = local_now()
    stats.frames += 1
    stats.last_frame_at = now
    if not faces:
        return
    stats.frames_with_faces += 1
    stats.last_face_at = now
    stats.faces += len(faces)
    for face in faces:
        height = face_height_px(face)
        stats._face_heights.append(height)
        if height < settings.attendance_min_face_px:
            stats.small_faces += 1
    for match in graded:
        if match.similarity > stats.best_similarity:
            stats.best_similarity = match.similarity
        stats.buckets[_bucket(match.similarity)] += 1


def is_face_blind(camera_id: str) -> bool:
    """Shu kamera bugun BIRORTA ham tanib bo'ladigan yuz bermadimi.

    "Ko'r" deb hisoblanadi: yetarlicha yuz ko'rilgan (tasodifiy bir-ikki
    kadr emas), ularning deyarli hammasi minimal o'lchamdan kichik VA
    birorta ham moslik yozilmagan. Uchinchi shart muhim: bir marta
    bo'lsa ham odam tanigan kamera hech qachon o'chirilmaydi.

    Statistika har kuni noldan boshlanadi (CameraRecognitionStats.day),
    shuning uchun qaror ham har kuni qaytadan olinadi."""
    if not settings.face_blind_skip_enabled:
        return False
    stats = _stats.get(camera_id)
    if stats is None or stats.day != business_today():
        return False
    if stats.faces < settings.face_blind_min_faces:
        return False
    if stats.strict or stats.relaxed_confirmed or stats.relaxed_pending:
        return False
    return stats.small_faces >= stats.faces * settings.face_blind_small_ratio


def record_credit(camera_id: str | None, grade: str) -> None:
    if camera_id is None:
        return
    stats = _camera_stats(camera_id)
    if grade == "strict":
        stats.strict += 1
    elif grade == "relaxed_confirmed":
        stats.relaxed_confirmed += 1
    elif grade == "relaxed_pending":
        stats.relaxed_pending += 1
        return
    stats.last_match_at = local_now()


def record_cycle(
    camera_id: str | None, *, total_seconds: float, grab_seconds: float, stream: str | None = None
) -> None:
    """Kameraning bitta to'liq tekshiruvi qancha davom etdi — CPU yetishmasligi
    kadr olishdami (oqim/dekodlash) yoki tahlildami, shu ikki raqamdan ko'rinadi.
    Doimiy kuzatuvda (kirish kameralari) bu ikki tahlil qilingan kadr orasidagi vaqt."""
    if camera_id is None:
        return
    stats = _camera_stats(camera_id)
    stats.cycles += 1
    stats.last_cycle_seconds = round(total_seconds, 1)
    stats.last_grab_seconds = round(grab_seconds, 1)
    if stream is not None:
        stats.stream = stream


def record_motion_skip(camera_id: str | None) -> None:
    if camera_id is None:
        return
    _camera_stats(camera_id).motion_skipped += 1


def record_idle(camera_id: str | None, seconds: float) -> None:
    if camera_id is None or seconds <= 0:
        return
    stats = _camera_stats(camera_id)
    stats.idle_waits += 1
    stats.idle_seconds += seconds


def record_tracked(camera_id: str | None, count: int) -> None:
    if camera_id is None or count <= 0:
        return
    _camera_stats(camera_id).tracked_faces += count


def record_zoom_attempt(camera_id: str | None) -> None:
    """Asosiy oqimdan kadr olishga urinildi (kadr kelmasa ham sanaladi —
    urinish 4K tarmoq yuklamasini beradi)."""
    if camera_id is None:
        return
    _camera_stats(camera_id).zoom_attempts += 1


def record_zoom_faces(camera_id: str | None, heights: list[int]) -> None:
    if camera_id is None or not heights:
        return
    stats = _camera_stats(camera_id)
    stats.zoom_faces += len(heights)
    stats._zoom_heights.extend(heights)


def record_static(camera_id: str | None, *, skipped: int, heights: list[int]) -> None:
    """Shu kadrda nechta yuz "devordagi rasm" deb o'tkazib yuborildi va
    kamerada hozir qanday statik ramkalar bor. Hech narsa jimgina
    yo'qolmasligi uchun alohida sanaladi — kamerada yuz "kamaygandek"
    ko'rinsa, sababi shu raqamda turadi."""
    if camera_id is None:
        return
    stats = _camera_stats(camera_id)
    if skipped > 0:
        stats.static_faces += skipped
    stats.static_boxes = len(heights)
    stats._static_heights = tuple(heights)


def record_zoom_matches(camera_id: str | None, count: int) -> None:
    if camera_id is None or count <= 0:
        return
    _camera_stats(camera_id).zoom_matches += count


def confirm_relaxed(person_id: str, camera_id: str | None = None, *, now: float | None = None) -> bool:
    """True — shu odam oynada allaqachon bir marta ko'ringan (tasdiqlandi).
    False — birinchi ko'rinish, eslab qolindi va keyingisi kutiladi.

    Ikkinchi ko'rinish MUSTAQIL bo'lishi kerak: bir kameraning ketma-ket
    kadrlari bir xil yuz, bir xil burchak — eshik oldida bir soniya turgan
    o'xshash begona o'zini o'zi "tasdiqlab" qo'yardi. Shuning uchun:
      * boshqa kamera — mustaqil burchak, attendance_relaxed_min_gap_seconds yetarli;
      * o'sha kamera (yoki noma'lum) — kamida
        attendance_relaxed_same_camera_gap_seconds (boshqa holat, boshqa burchak)."""
    moment = time.monotonic() if now is None else now
    window = settings.attendance_relaxed_confirm_window_seconds
    for key, seen_at in list(_pending_relaxed.items()):
        if moment - seen_at > window:
            del _pending_relaxed[key]
            _pending_camera.pop(key, None)
    first = _pending_relaxed.get(person_id)
    if first is None:
        _pending_relaxed[person_id] = moment
        _pending_camera[person_id] = camera_id
        return False
    first_camera = _pending_camera.get(person_id)
    other_camera = camera_id is not None and first_camera is not None and camera_id != first_camera
    needed = settings.attendance_relaxed_min_gap_seconds
    if not other_camera:
        needed = max(needed, settings.attendance_relaxed_same_camera_gap_seconds)
    if moment - first >= needed:
        del _pending_relaxed[person_id]
        _pending_camera.pop(person_id, None)
        return True
    return False


def note_strict_sighting(person_id: str) -> None:
    """Qat'iy moslik allaqachon ishonchli — kutilayotgan yumshoq holatni
    tozalaymiz, keyingi yumshoq ko'rinish qaytadan boshlanadi."""
    _pending_relaxed.pop(person_id, None)
    _pending_camera.pop(person_id, None)


def snapshot(camera_id: str) -> CameraRecognitionStats | None:
    stats = _stats.get(camera_id)
    if stats is None or stats.day != business_today():
        return None
    return stats


@dataclass
class RecognitionView:
    """Kamera statistikasining o'qish uchun nusxasi — jarayonlar o'rtasida
    JSON orqali uzatiladi (app/services/runtime_snapshot.py). Maydon nomlari
    CameraRecognitionStats bilan bir xil, shuning uchun o'quvchi kod farqni
    bilmaydi."""

    day: date
    frames: int = 0
    frames_with_faces: int = 0
    faces: int = 0
    small_faces: int = 0
    strict: int = 0
    relaxed_confirmed: int = 0
    relaxed_pending: int = 0
    best_similarity: float = -1.0
    face_px_median: int | None = None
    buckets: dict[str, int] = field(default_factory=dict)
    cycles: int = 0
    last_cycle_seconds: float | None = None
    last_grab_seconds: float | None = None
    stream: str | None = None
    motion_skipped: int = 0
    tracked_faces: int = 0
    idle_waits: int = 0
    idle_seconds: float = 0.0
    zoom_attempts: int = 0
    zoom_faces: int = 0
    zoom_matches: int = 0
    zoom_px_median: int | None = None
    static_faces: int = 0
    static_boxes: int = 0
    static_px_median: int | None = None
    last_frame_at: datetime | None = None
    last_face_at: datetime | None = None
    last_match_at: datetime | None = None


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def export_snapshot() -> dict[str, dict]:
    """Bugungi statistika — JSON'ga yaroqli ko'rinishda."""
    today = business_today()
    return {
        camera_id: {
            "day": s.day.isoformat(),
            "frames": s.frames,
            "frames_with_faces": s.frames_with_faces,
            "faces": s.faces,
            "small_faces": s.small_faces,
            "strict": s.strict,
            "relaxed_confirmed": s.relaxed_confirmed,
            "relaxed_pending": s.relaxed_pending,
            "best_similarity": s.best_similarity,
            "face_px_median": s.face_px_median,
            "buckets": dict(s.buckets),
            "last_frame_at": _iso(s.last_frame_at),
            "last_face_at": _iso(s.last_face_at),
            "last_match_at": _iso(s.last_match_at),
            "cycles": s.cycles,
            "last_cycle_seconds": s.last_cycle_seconds,
            "last_grab_seconds": s.last_grab_seconds,
            "stream": s.stream,
            "motion_skipped": s.motion_skipped,
            "tracked_faces": s.tracked_faces,
            "idle_waits": s.idle_waits,
            "idle_seconds": round(s.idle_seconds, 1),
            "zoom_attempts": s.zoom_attempts,
            "zoom_faces": s.zoom_faces,
            "zoom_matches": s.zoom_matches,
            "zoom_px_median": s.zoom_px_median,
            "static_faces": s.static_faces,
            "static_boxes": s.static_boxes,
            "static_px_median": s.static_px_median,
        }
        for camera_id, s in _stats.items()
        if s.day == today
    }


def view_from_dict(row: dict) -> RecognitionView | None:
    """Boshqa kun (yarim tundan oldingi) surati — None."""
    try:
        day = date.fromisoformat(row["day"])
    except (KeyError, TypeError, ValueError):
        return None
    if day != business_today():
        return None
    return RecognitionView(
        day=day,
        frames=int(row.get("frames", 0)),
        frames_with_faces=int(row.get("frames_with_faces", 0)),
        faces=int(row.get("faces", 0)),
        small_faces=int(row.get("small_faces", 0)),
        strict=int(row.get("strict", 0)),
        relaxed_confirmed=int(row.get("relaxed_confirmed", 0)),
        relaxed_pending=int(row.get("relaxed_pending", 0)),
        best_similarity=float(row.get("best_similarity", -1.0)),
        face_px_median=row.get("face_px_median"),
        buckets={str(k): int(v) for k, v in (row.get("buckets") or {}).items()},
        last_frame_at=_parse(row.get("last_frame_at")),
        last_face_at=_parse(row.get("last_face_at")),
        last_match_at=_parse(row.get("last_match_at")),
        cycles=int(row.get("cycles", 0)),
        last_cycle_seconds=row.get("last_cycle_seconds"),
        last_grab_seconds=row.get("last_grab_seconds"),
        stream=row.get("stream"),
        motion_skipped=int(row.get("motion_skipped", 0)),
        tracked_faces=int(row.get("tracked_faces", 0)),
        idle_waits=int(row.get("idle_waits", 0)),
        idle_seconds=float(row.get("idle_seconds", 0.0)),
        zoom_attempts=int(row.get("zoom_attempts", 0)),
        zoom_faces=int(row.get("zoom_faces", 0)),
        zoom_matches=int(row.get("zoom_matches", 0)),
        zoom_px_median=row.get("zoom_px_median"),
        static_faces=int(row.get("static_faces", 0)),
        static_boxes=int(row.get("static_boxes", 0)),
        static_px_median=row.get("static_px_median"),
    )


def local_views() -> dict[str, RecognitionView]:
    return {
        camera_id: view
        for camera_id, row in export_snapshot().items()
        if (view := view_from_dict(row)) is not None
    }


def reset_for_tests() -> None:
    _stats.clear()
    _pending_relaxed.clear()
    _pending_camera.clear()
