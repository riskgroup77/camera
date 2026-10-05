"""Pulls a JPEG frame from a camera's live stream — the missing link
between "a camera is registered with MediaMTX" and "an AI module can
actually look at what it sees".

When settings.ai_use_direct_rtsp is true, AI modules read the camera's
RTSP substream directly (no MediaMTX/HLS hop). Browser playback still
uses Camera.stream_url (HLS via MediaMTX).

Entrance/perimeter cameras optionally use the main RTSP stream (101)
for face AI — substream is too low-res for corridor-wide shots.
"""

import asyncio
import logging
import random
import time
from urllib.parse import urlsplit

from app.config import settings
from app.crypto import decrypt
from app.models import Camera
from app.rtsp import build_rtsp_url
from app.services import stream_promotion
from app.services.frame_quality import looks_like_decode_damage, measure_frame
from app.services.stream_cache import (
    get_cached_frame_with_seq,
    get_cached_history,
    is_stream_known_broken,
    stop_stream_reader,
)
from app.services.camera_roles import is_door_camera
from app.services.thumbnail_cache import remember_frame
from app.services.video_gateway import public_hls_to_internal

logger = logging.getLogger("app.frame_grabber")

# Kesh qancha tez-tez so'raladi. Kadrlar soniyasiga 1-2 marta yangilanadi,
# shuning uchun bundan siyrak so'rash ikkinchi kadrni kechiktiradi.
_POLL_SECONDS = 0.25


def _is_security_camera(camera: Camera) -> bool:
    """Asosiy oqim o'qiladigan kameralar. ATTENDANCE_ALL_CAMERAS da har
    kamera davomat uchun yuz taniydi — substream'da yuz tanib bo'lmas darajada kichik."""
    if is_door_camera(camera) or (camera.is_perimeter and settings.ai_perimeter_main_stream):
        return True
    if camera.is_perimeter:
        return False
    if not settings.attendance_all_cameras:
        return False
    if settings.ai_room_cameras_main_stream:
        return True
    # Byudjet doirasida tanlangan xona kameralari (app/services/stream_promotion.py).
    camera_id = getattr(camera, "id", None)
    return camera_id is not None and stream_promotion.is_promoted(str(camera_id))


# camera_id -> monotonic payt: shu paytgacha asosiy oqim ishlatilmaydi.
# Faqat shu jarayon xotirasida — AI sweeplari bitta (leader) jarayonda.
_main_stream_failed_until: dict[str, float] = {}


def _main_stream_blocked(camera: Camera) -> bool:
    until = _main_stream_failed_until.get(str(camera.id))
    if until is None:
        return False
    if time.monotonic() >= until:
        # Muddat tugadi — asosiy oqim yana sinab ko'riladi.
        del _main_stream_failed_until[str(camera.id)]
        return False
    return True


def _note_main_stream_result(camera: Camera, ok: bool) -> None:
    key = str(camera.id)
    if ok:
        _main_stream_failed_until.pop(key, None)
        return
    if key not in _main_stream_failed_until:
        logger.warning(
            "main stream gave no frame; using the substream for this camera for a while",
            extra={
                "camera_id": key,
                "camera": getattr(camera, "name", ""),
                "retry_after_seconds": settings.ai_entrance_main_stream_retry_seconds,
            },
        )
    # Kirish eshigi tez qayta urinadi, xona kamerasi uzoq kutadi (config izohi);
    # tasodifiy siljish — hammasi bir lahzada qayta urinib tarmoqni to'ldirmasin.
    base = (
        settings.ai_entrance_main_stream_retry_seconds
        if camera.is_entrance or getattr(camera, "is_exit", False) or camera.is_perimeter
        else settings.ai_room_main_stream_retry_seconds
    )
    _main_stream_failed_until[key] = time.monotonic() + base * random.uniform(0.8, 1.2)


def reset_main_stream_fallbacks_for_tests() -> None:
    _main_stream_failed_until.clear()


def ai_prefers_substream(camera: Camera) -> bool:
    """True → Channels/102; False → main stream (101 or camera.rtsp_path).

    Kirish/perimetr kamerasining asosiy oqimi kadr bermasa, u
    ai_entrance_main_stream_retry_seconds davomida substream'da ishlaydi:
    past sifatli kadr, umuman kadr yo'qligidan yaxshiroq."""
    if settings.ai_entrance_use_main_stream and _is_security_camera(camera):
        return _main_stream_blocked(camera)
    return True


def mediamtx_relay_url(camera: Camera) -> str | None:
    """Kameraning MediaMTX yo'li RTSP orqali (docker ichki tarmog'i)."""
    if not camera.stream_url:
        return None
    parts = urlsplit(public_hls_to_internal(camera.stream_url))
    segments = [s for s in parts.path.split("/") if s]
    if not parts.hostname or not segments or not segments[0].startswith("cam-"):
        return None
    return f"rtsp://{parts.hostname}:{settings.mediamtx_internal_rtsp_port}/{segments[0]}"


def rtsp_url_for_camera(camera: Camera, *, substream: bool | None = None) -> str:
    use_sub = ai_prefers_substream(camera) if substream is None else substream
    if use_sub and settings.ai_read_via_mediamtx:
        relay = mediamtx_relay_url(camera)
        if relay:
            return relay
    path = settings.rtsp_substream_path if use_sub else (camera.rtsp_path or "/Streaming/Channels/101")
    return build_rtsp_url(
        camera.ip,
        camera.port,
        path,
        decrypt(camera.rtsp_username) if camera.rtsp_username else None,
        decrypt(camera.rtsp_password) if camera.rtsp_password else None,
    )


def camera_video_source(camera: Camera) -> str:
    """URL used by AI frame readers — RTSP substream/main or HLS fallback."""
    if settings.ai_use_direct_rtsp:
        return rtsp_url_for_camera(camera)
    if not camera.stream_url:
        return ""
    return public_hls_to_internal(camera.stream_url)


def frame_wait_seconds_for_camera(camera: Camera) -> float:
    if not ai_prefers_substream(camera):
        return settings.ai_entrance_frame_wait_seconds
    return 8.0


async def _grab_newer(camera: Camera, *, wait_seconds: float, after_seq: int | None) -> tuple[bytes, int] | None:
    """Kesh kadri va uning tartib raqami. `after_seq` berilsa, faqat undan
    KEYIN dekodlangan kadr qabul qilinadi — yangi kadr kelguncha kutiladi.

    Nega kerak: kesh soniyasiga bir-ikki kadr yangilanadi
    (stream_cache_capture_fps), ikki kadrli tasdiq esa ikkinchi kadrni
    ~1 soniyadan keyin so'raydi. Oldin keshda hali o'sha kadr turgan
    bo'lsa, u QAYTA berilardi — "ikki kadrda ham" degan tasdiq aslida bitta
    kadrni ikki marta tekshirardi. Productionda o'lchandi: #13 signallarining
    32/33 tasida, #15 ning 100/126 tasida ikkala kadr o'lchovi aynan bir xil
    edi. Uyqu (#20) ovozida esa bitta yumuq ko'zli kadr to'rt ovoz berardi."""
    source = camera_video_source(camera)
    if not source:
        return None
    on_main_stream = settings.ai_use_direct_rtsp and not ai_prefers_substream(camera)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        latest = await get_cached_frame_with_seq(source)
        if latest is not None and (after_seq is None or latest[1] > after_seq):
            if on_main_stream:
                _note_main_stream_result(camera, ok=True)
            # Monitoring markazining qavat gridi shu kadrdan miniatyura
            # oladi: kameraga qo'shimcha ulanish ham, qo'shimcha ffmpeg
            # ham kerak bo'lmaydi. Chaqiruv kamera bo'yicha oraliqqa
            # bo'ysunadi va xato ko'tarmaydi (thumbnail_cache.py).
            await remember_frame(str(camera.id), latest[0])
            return latest
        if is_stream_known_broken(source):
            break  # reader had its grace period, decoded nothing — don't burn the rest of the slot
        await asyncio.sleep(_POLL_SECONDS)
    # Asosiy oqim UMUMAN kadr bermadi (yangiroq kadr kutish emas — uzun
    # kalit kadr oralig'ida ikkinchi kadr kechikishi tabiiy).
    if on_main_stream and after_seq is None:
        _note_main_stream_result(camera, ok=False)
        # Kadr bermagan asosiy oqim o'quvchisi darhol yopiladi — aks holda u
        # yana stream_cache_idle_timeout_seconds davomida tarmoqni band qilib,
        # substream bilan birga ikki barobar yuklardi (productionda 172 o'quvchi).
        await stop_stream_reader(source)
    return None


async def grab_newer_frame(camera: Camera, *, wait_seconds: float, after_seq: int | None) -> tuple[bytes, int] | None:
    """Kadr va uning tartib raqami — doimiy kuzatuvchilar uchun
    (app/jobs/attendance_ai.py): har kadrni aynan bir marta olish uchun
    oldingisining raqami beriladi."""
    return await _grab_newer(camera, wait_seconds=wait_seconds, after_seq=after_seq)


def stream_label(camera: Camera) -> str:
    """AI hozir shu kameraning qaysi oqimini o'qiyapti — diagnostika uchun."""
    if not settings.ai_use_direct_rtsp:
        return "hls"
    if settings.ai_entrance_use_main_stream and _is_security_camera(camera):
        return "substream (zaxira)" if _main_stream_blocked(camera) else "asosiy"
    return "substream"


async def grab_frame_for_camera(camera: Camera, *, wait_seconds: float | None = None) -> bytes | None:
    latest = await _grab_newer(
        camera,
        wait_seconds=wait_seconds if wait_seconds is not None else frame_wait_seconds_for_camera(camera),
        after_seq=None,
    )
    return latest[0] if latest is not None else None


async def grab_main_stream_frame_once(camera: Camera, *, wait_seconds: float | None = None) -> bytes | None:
    """Asosiy (4K) oqimdan BITTA kadr — o'quvchi darhol yopiladi.

    Yaqinlashtirib tanish uchun (app/services/face_zoom.py). Odatdagi
    grab_frame_for_camera() kadrni keshdan oladi va o'quvchini tirik
    qoldiradi: u yana stream_cache_idle_timeout_seconds davomida 4K
    oqimni dekodlab turardi. Bu yerda esa aksincha — kadr olindimi yoki
    yo'qmi, ffmpeg jarayoni shu yerda o'ldiriladi, ya'ni 4K ulanish
    faqat shu bir necha soniya yashaydi.

    None qaytadi: to'g'ridan-to'g'ri RTSP o'chirilgan, kamera allaqachon
    asosiy oqimda (u holda zoom keraksiz — o'quvchisini yopib bo'lmaydi),
    asosiy oqim yaqinda kadr bermagani uchun hozir "jazo muddati"da yoki
    oqim shu safar ham kadr bermadi.

    ORQAGA CHEKINISH (backoff) zoom uchun ham amal qiladi. Ilgari
    _main_stream_failed_until faqat odatdagi yo'lni to'xtatardi: kadr
    bermayotgan 4K oqimga zoom baribir har face_zoom_interval_seconds da
    urinib, face_zoom_wait_seconds gacha (8 s) kutib turardi — va shu
    davrda kirish/chiqish sweep'ining 6 ta slotidan biri band bo'lardi,
    muddat esa hech qachon uzaymasdi. Endi: bloklangan kamera umuman
    urinmaydi, kadr bermagan urinish esa muddatni uzaytiradi, muvaffaqiyatli
    urinish uni bekor qiladi."""
    if not settings.ai_use_direct_rtsp:
        return None
    if _main_stream_blocked(camera):
        return None
    source = rtsp_url_for_camera(camera, substream=False)
    if not source or source == camera_video_source(camera):
        return None
    deadline = time.monotonic() + (settings.face_zoom_wait_seconds if wait_seconds is None else wait_seconds)
    try:
        while time.monotonic() < deadline:
            latest = await get_cached_frame_with_seq(source)
            if latest is not None:
                _note_main_stream_result(camera, ok=True)
                return latest[0]
            if is_stream_known_broken(source):
                break
            await asyncio.sleep(_POLL_SECONDS)
        _note_main_stream_result(camera, ok=False)
        return None
    finally:
        await stop_stream_reader(source)


def main_stream_source(camera: Camera) -> str | None:
    """Kamerani kichik oqimda o'qiyotgan AI uchun uning asosiy oqimi; None —
    asosiy oqim ishlatib bo'lmaydi yoki kamera allaqachon unda."""
    if not settings.ai_use_direct_rtsp or _main_stream_blocked(camera):
        return None
    source = rtsp_url_for_camera(camera, substream=False)
    if not source or source == camera_video_source(camera):
        return None
    return source


async def grab_newer_main_frame(camera: Camera, *, wait_seconds: float, after_seq: int | None) -> tuple[bytes, int] | None:
    """Operator kuzatayotgan kamera uchun asosiy (4K) oqimdan `after_seq` dan
    keyingi kadr — doimiy kuzatuvchi (app/jobs/attendance_ai.py) uchun
    grab_live_main_frame() ning juftligi. O'quvchi yopilmaydi: kuzatuv
    tugagach kuzatuvchi uni o'zi yopadi (stop_stream_reader)."""
    source = main_stream_source(camera)
    if source is None:
        return None
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        latest = await get_cached_frame_with_seq(source)
        if latest is not None and (after_seq is None or latest[1] > after_seq):
            _note_main_stream_result(camera, ok=True)
            return latest
        if is_stream_known_broken(source):
            break
        await asyncio.sleep(_POLL_SECONDS)
    if after_seq is None:
        _note_main_stream_result(camera, ok=False)
        await stop_stream_reader(source)
    return None


async def grab_live_main_frame(camera: Camera, *, wait_seconds: float) -> bytes | None:
    """Operator KUZATAYOTGAN kamera uchun asosiy (4K) oqimdan kadr.

    grab_main_stream_frame_once() dan farqi: o'quvchi yopilmaydi. Yuz
    belgilari har bir necha soniyada so'raladi — har safar 4K ulanishni
    qaytadan ochish ~5 s kutish degani edi. O'quvchi keshda qoladi va
    operator ketgach stream_cache_idle_timeout_seconds o'tib o'zi
    to'xtaydi, ya'ni narxi faqat kuzatilgan vaqt davomida to'lanadi.

    None — asosiy oqim o'chirilgan, "jazo muddati"da yoki kadr bermadi;
    chaqiruvchi kichik oqimga qaytadi."""
    if not settings.ai_use_direct_rtsp or _main_stream_blocked(camera):
        return None
    source = rtsp_url_for_camera(camera, substream=False)
    if not source:
        return None
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        latest = await get_cached_frame_with_seq(source)
        if latest is not None:
            _note_main_stream_result(camera, ok=True)
            return latest[0]
        if is_stream_known_broken(source):
            break
        await asyncio.sleep(_POLL_SECONDS)
    _note_main_stream_result(camera, ok=False)
    return None


def _spaced(history: list[tuple[bytes, int, float]], count: int, gap_seconds: float) -> list[bytes] | None:
    """Tarixdan (eng yangisidan) kamida `gap_seconds` oraliqli `count` ta kadr,
    eskisidan yangisiga tartibda. Yetmasa None."""
    if not history:
        return None
    chosen = [history[0]]
    for frame, seq, at in history[1:]:
        if len(chosen) == count:
            break
        if chosen[-1][2] - at >= gap_seconds * 0.9:
            chosen.append((frame, seq, at))
    if len(chosen) < count:
        return None
    return [frame for frame, _, _ in reversed(chosen)]


def _all_clean(frames: list[bytes]) -> bool:
    """Tarixdagi kadrlar get_latest() tekshiruvidan o'tmagan bo'lishi mumkin —
    buzilgan (qisman dekodlangan) kadr bo'lsa tarixdan voz kechiladi."""
    return not any(looks_like_decode_damage(measure_frame(frame), None) for frame in frames)


async def _from_history(camera: Camera, count: int, gap_seconds: float) -> list[bytes] | None:
    """Kadr tarixidan darhol — yangi kalit kadr kutilmaydi. Bir vaqtda
    ishlayotgan modullar shu yo'l bilan AYNAN bir xil kadrlarni oladi va
    model natijasini bo'lishadi (app/services/inference_cache.py)."""
    source = camera_video_source(camera)
    if not source or count < 1:
        return None
    frames = _spaced(await get_cached_history(source), count, gap_seconds)
    if frames is None:
        return None
    if not await asyncio.to_thread(_all_clean, frames):
        return None
    await remember_frame(str(camera.id), frames[-1])
    return frames


async def grab_frame_pair_for_camera(camera: Camera, gap_seconds: float = 1.0) -> tuple[bytes, bytes] | None:
    """Ikki HAR XIL kadr, kamida `gap_seconds` oraliqda. Avval kadr
    tarixidan (kutishsiz), bo'lmasa yangi kadr kutiladi. Ikkinchi yangi kadr
    kelmasa None — eski kadrni ikkinchi marta berib, tasdiqni
    soxtalashtirgandan ko'ra shu kamerani bu safar tashlab ketgan yaxshi."""
    recent = await _from_history(camera, 2, gap_seconds)
    if recent is not None:
        return recent[0], recent[1]
    wait = frame_wait_seconds_for_camera(camera)
    first = await _grab_newer(camera, wait_seconds=wait, after_seq=None)
    if first is None:
        return None
    await asyncio.sleep(gap_seconds)
    second = await _grab_newer(camera, wait_seconds=wait, after_seq=first[1])
    if second is None:
        return None
    return first[0], second[0]


async def grab_frame_burst_for_camera(camera: Camera, count: int, gap_seconds: float) -> list[bytes]:
    """`count` tagacha HAR XIL kadr. Oqim yangi kadr bermay qolsa burst
    shu yerda to'xtaydi: qolgan har bir kadr uchun yana kutish sweep
    slotini behuda band qilardi, eski kadrni takrorlash esa ovozni buzardi.
    Avval kadr tarixidan (kutishsiz) olinadi."""
    recent = await _from_history(camera, count, gap_seconds)
    if recent is not None:
        return recent
    wait = frame_wait_seconds_for_camera(camera)
    frames: list[bytes] = []
    last_seq: int | None = None
    for i in range(count):
        if i > 0:
            await asyncio.sleep(gap_seconds)
        latest = await _grab_newer(camera, wait_seconds=wait, after_seq=last_seq)
        if latest is None:
            break
        frames.append(latest[0])
        last_seq = latest[1]
    return frames
