"""HEMIS rasmidan tanitish — yuzi bazada yo'q odamlar uchun.

MUAMMO (2026-09-25). Bazada yuzi borlar — 27% (7259 dan 1972): qolganlarni
kamera ko'rsa ham "Notanish" deydi. HEMIS'da esa 7047 talabadan 7028 tasining
rasmi bor (student-list: image_full), xodimlarniki ham.

YECHIM. HEMIS sinxronlashi rasm manzilini StudentStaff.hemis_photo_url ga
yozadi. Bu vazifa ularni kichik to'plamlarda (settings.hemis_photo_batch)
fon navbatida qayta ishlaydi:

  * yuzi YO'Q odam — rasmdagi yagona/eng yirik yuz uning asosiy vektori
    bo'ladi (holati "tasdiqlangan": rasm universitetning rasmiy bazasidan);
  * yuzi BOR odam — rasm galereyaga qo'shimcha namuna, faqat asl rasmiga
    o'xshasa (aks holda xato sifatida belgilanadi — ehtimol noto'g'ri
    birikma, operator ko'radi);
  * boshqa tasdiqlangan odamga juda o'xshasa — yozilmaydi (adash yoki
    HEMIS'dagi xato rasm).

Har odam bir marta tekshiriladi (hemis_photo_checked_at); rasm o'zgarsa
sinxronlash belgini tozalaydi va qayta tekshiriladi. Yuklab olish faqat
HEMIS domenidan (hemis_base_url bilan bir xil asosiy domen).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import cv2
import httpx
import numpy as np
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal
from app.models import FaceGalleryEmbedding, StudentStaff
from app.services.face_matching import anchor_hash, announce_roster_change
from app.services.face_recognition import NoFaceDetectedError, detect_faces
from app.services.inference_gate import PRIORITY_BACKGROUND
from app.services.integrations import hemis
from app.services.unknown_sightings import _other_lookalike, _unit

logger = logging.getLogger("app.jobs.hemis_photos")

MAX_PHOTO_BYTES = 5_000_000


class PhotoTooLarge(ValueError):
    pass


async def fetch_photo(client: httpx.AsyncClient, url: str) -> tuple[int, str, bytes]:
    """(status, content-type, tana). Tana oqim bilan o'qiladi va MAX_PHOTO_BYTES
    dan oshsa to'xtatiladi — noto'g'ri ishlagan server xotirani to'ldira olmasin."""
    async with client.stream("GET", url) as response:
        content_type = response.headers.get("content-type", "")
        if response.status_code != 200 or not content_type.startswith("image/"):
            return response.status_code, content_type, b""
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_PHOTO_BYTES:
            raise PhotoTooLarge("Rasm juda katta")
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > MAX_PHOTO_BYTES:
                raise PhotoTooLarge("Rasm juda katta")
            chunks.append(chunk)
        return response.status_code, content_type, b"".join(chunks)


def allowed_photo_host(url: str) -> bool:
    """Rasm HEMIS bilan bir xil asosiy domendan (student.fjsti.uz -> fjsti.uz)."""
    base = urlsplit(settings.hemis_base_url).hostname or ""
    host = urlsplit(url).hostname or ""
    root = ".".join(base.split(".")[-2:]) if base.count(".") >= 1 else base
    return bool(root) and urlsplit(url).scheme == "https" and (host == root or host.endswith("." + root))


def _largest(faces: list):
    usable = [face for face in faces if getattr(face, "embedding", None) is not None]
    if not usable:
        return None
    return max(usable, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))


# Eski xabar — shu sabab bilan rad etilganlar bir marta qayta tekshiriladi
# (chegara qo'shilishidan oldin).
OLD_NO_FACE = "Rasmda yuz topilmadi"
NO_FACE = "Rasmda yuz topilmadi (chegara bilan ham)"
PAD_RATIO = 0.5
# HEMIS rasm serveri vaqtincha javob bermasa (vaqt tugadi, 5xx, 429) — rasm
# keyinroq qayta yuklanadi (settings.hemis_photo_retry_minutes), ko'pi bilan
# RETRY_LIMIT marta. 404 va boshqa doimiy xatolar qayta urinilmaydi.
TRANSIENT = "Vaqtincha yuklab bo'lmadi"
OLD_DOWNLOAD = "Rasmni yuklab bo'lmadi"
RETRY_LIMIT = 5
_ATTEMPT = re.compile(r"\[(\d+)\]$")


class TransientDownloadError(Exception):
    pass


def transient_message(previous: str | None, reason: str) -> str:
    """"Vaqtincha yuklab bo'lmadi (504) [2]" — oxirgi raqam urinishlar soni."""
    attempts = 1
    if previous and previous.startswith(TRANSIENT):
        match = _ATTEMPT.search(previous)
        attempts = (int(match.group(1)) if match else 1) + 1
    if attempts > RETRY_LIMIT:
        return f"Rasmni yuklab bo'lmadi: {reason} ({RETRY_LIMIT} marta urinildi)"
    return f"{TRANSIENT} ({reason}) [{attempts}]"


# Portret shu o'lchamgacha kichraytirib tahlil qilinadi. Detektor kadrni
# uzun tomoni bo'yicha face_det_max_side (1280) gacha ishlaydi: 993x1275
# rasm (chegara bilan 1986x2550) har safar ~1.7 s olardi, 640 da ~0.4 s.
# Yuz baribir 112x112 ga tekislanadi — vektor sifati o'zgarmaydi.
PHOTO_DET_SIDE = 640


def fit_long_side(image: np.ndarray, side: int = PHOTO_DET_SIDE) -> np.ndarray:
    height, width = image.shape[:2]
    scale = side / max(height, width)
    if scale >= 1.0:
        return image
    return cv2.resize(image, (max(1, round(width * scale)), max(1, round(height * scale))), interpolation=cv2.INTER_AREA)


def _encode(image: np.ndarray) -> bytes | None:
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return buffer.tobytes() if ok else None


def shrink(data: bytes) -> bytes:
    """Tahlil uchun kichraytirilgan nusxa (asl rasm saqlash uchun o'zgarmaydi)."""
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return data
    height, width = image.shape[:2]
    if max(height, width) <= PHOTO_DET_SIDE:
        return data
    return _encode(fit_long_side(image)) or data


def with_border(data: bytes, ratio: float = PAD_RATIO) -> bytes | None:
    """Rasm atrofiga kulrang chegara. HEMIS rasmi pasport uslubida
    (993x1275): yuz kadrni deyarli to'liq egallaydi va SCRFD bunday yirik
    yuzni topmaydi — 2026-09-25 da birinchi 60 ta rasmdan 15 tasi shu sababli
    rad etilgan, 50% chegara bilan 15 tasining hammasida yuz topildi."""
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return None
    height, width = image.shape[:2]
    padded = cv2.copyMakeBorder(
        image, int(height * ratio), int(height * ratio), int(width * ratio), int(width * ratio),
        cv2.BORDER_CONSTANT, value=(128, 128, 128),
    )
    return _encode(fit_long_side(padded))


async def _embed_photo(data: bytes) -> tuple[np.ndarray, int]:
    small = await asyncio.to_thread(shrink, data)
    faces = await detect_faces(small, priority=PRIORITY_BACKGROUND, min_face_px=0, landmarks=False)
    face = _largest(faces)
    if face is None:
        padded = await asyncio.to_thread(with_border, data)
        if padded is not None:
            faces = await detect_faces(padded, priority=PRIORITY_BACKGROUND, min_face_px=0, landmarks=False)
            face = _largest(faces)
    if face is None:
        raise NoFaceDetectedError(NO_FACE)
    height = int(face.bbox[3] - face.bbox[1])
    if height < settings.hemis_photo_min_face_px:
        raise NoFaceDetectedError(f"Yuz juda kichik ({height} px)")
    if face.det_score is not None and face.det_score < 0.6:
        raise NoFaceDetectedError("Yuz aniq emas")
    return face.embedding, height


async def _upload(data: bytes) -> str | None:
    from app.storage import upload_file

    try:
        _file_id, key = await asyncio.to_thread(upload_file, data, "hemis.jpg", "image/jpeg", "biometrika")
    except Exception:
        logger.warning("HEMIS photo upload failed", exc_info=True)
        return None
    return key


async def enroll_person(db: AsyncSession, person: StudentStaff, data: bytes) -> str:
    """Natija: 'asosiy' | 'galereya'. Xato — ValueError/NoFaceDetectedError."""
    vector, height = await _embed_photo(data)
    vector = _unit(vector)
    if vector is None:
        raise ValueError("Yuz vektori buzilgan")
    lookalike = await _other_lookalike(db, vector, person.id)
    if lookalike:
        raise ValueError(f"Boshqa odamga juda o'xshaydi ({lookalike[1]:.2f})")
    encoded = json.dumps([round(float(v), 6) for v in vector])
    if person.biometric_embedding:
        anchor = _unit(json.loads(person.biometric_embedding))
        similarity = float(anchor @ vector) if anchor is not None else 0.0
        if similarity < settings.unknown_assign_min_similarity:
            raise ValueError(f"Mavjud yuz rasmiga o'xshamaydi ({similarity:.2f})")
        db.add(
            FaceGalleryEmbedding(
                student_staff_id=person.id,
                embedding=encoded,
                anchor_hash=anchor_hash(person.biometric_embedding),
                similarity=similarity,
                face_px=height,
                camera_id=None,
            )
        )
        return "galereya"
    if not person.has_all_angles:
        # Bitta HEMIS surati bilan yuz "tasdiqlangan" bo'lmaydi (3 burchak shart).
        raise ValueError("Yuz 3 tomondan olinmagan — ro'yxatdan o'tish havolasi orqali o'tsin")
    person.biometric_embedding = encoded
    person.biometrics_status = "tasdiqlangan"
    person.biometrics_confirmed_at = datetime.now(timezone.utc)
    if not person.biometric_photo_key:
        person.biometric_photo_key = await _upload(data)
    return "asosiy"


async def run_hemis_photos_once(batch: int | None = None) -> dict[str, int]:
    stats = {"asosiy": 0, "galereya": 0, "xato": 0}
    if not settings.hemis_photo_enrollment or not hemis.hemis_configured():
        return stats
    async with SessionLocal() as db:
        people = (
            await db.execute(
                select(StudentStaff)
                .where(
                    StudentStaff.active.is_(True),
                    StudentStaff.hemis_photo_url.is_not(None),
                    # Rozilikni qaytarib olgan (biometrikasi o'chirilgan) odam.
                    StudentStaff.biometrics_opt_out_at.is_(None),
                    or_(
                        StudentStaff.hemis_photo_checked_at.is_(None),
                        StudentStaff.hemis_photo_error == OLD_NO_FACE,
                        and_(
                            or_(
                                StudentStaff.hemis_photo_error.startswith(TRANSIENT),
                                StudentStaff.hemis_photo_error.startswith(OLD_DOWNLOAD + " ("),
                            ),
                            StudentStaff.hemis_photo_checked_at
                            < datetime.now(timezone.utc) - timedelta(minutes=settings.hemis_photo_retry_minutes),
                        ),
                    ),
                )
                # Yuzi yo'qlar birinchi — ular tanishni eng ko'p o'stiradi.
                .order_by(StudentStaff.biometric_embedding.is_not(None), StudentStaff.full_name)
                .limit(batch or settings.hemis_photo_batch)
            )
        ).scalars().all()
        if not people:
            return stats
        # HEMIS rasm serveri ba'zan sekin (portretlar ~300 KB).
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=False) as client:
            for person in people:
                url = person.hemis_photo_url or ""
                person.hemis_photo_checked_at = datetime.now(timezone.utc)
                try:
                    if not allowed_photo_host(url):
                        raise ValueError("Rasm manzili HEMIS domenidan emas")
                    try:
                        code, content_type, body = await fetch_photo(client, url)
                    except httpx.TransportError as error:
                        raise TransientDownloadError(type(error).__name__) from error
                    if code >= 500 or code == 429:
                        raise TransientDownloadError(str(code))
                    if code != 200 or not content_type.startswith("image/"):
                        raise ValueError(f"Rasmni yuklab bo'lmadi ({code})")
                    kind = await enroll_person(db, person, body)
                    person.hemis_photo_error = None
                    stats[kind] += 1
                except TransientDownloadError as error:
                    person.hemis_photo_error = transient_message(person.hemis_photo_error, str(error))[:200]
                    stats["xato"] += 1
                except (ValueError, NoFaceDetectedError, httpx.HTTPError) as error:
                    person.hemis_photo_error = str(error)[:200]
                    stats["xato"] += 1
                await db.commit()
    stats["navbat_toldi"] = int(len(people) >= (batch or settings.hemis_photo_batch))
    if stats["asosiy"] or stats["galereya"]:
        try:
            await announce_roster_change()
        except Exception:
            logger.warning("face roster change announcement failed", exc_info=True)
    logger.info("HEMIS photos processed", extra={"event": "hemis_photos", "stats": stats})
    return stats


async def hemis_photos_loop() -> None:
    """Navbatda rasm ko'p bo'lsa to'plamlar orasida kutilmaydi (faqat qisqa
    tanaffus) — 7000 rasm 5 daqiqalik tanaffuslar bilan bir necha kun
    olardi. Tahlil fon navbatida: jonli kameralar baribir birinchi."""
    while True:
        full = False
        try:
            full = bool((await run_hemis_photos_once()).get("navbat_toldi"))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("HEMIS photo enrollment failed")
        await asyncio.sleep(settings.hemis_photo_busy_pause_seconds if full else settings.hemis_photo_interval_seconds)
