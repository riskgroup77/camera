"""Kunduzgi notanish yuzlar — yozish, birlashtirish, hal qilish.

Model va nega kerakligi: app/models/unknown_sighting.py.

Oqim:
  unified_face_sweep (kunduzi) -> record_unknown_faces()   yuz qatorga yoziladi
  operator                      -> assign_to_person()       "talaba"
                                -> mark_stranger()          "begona" (hodisa #1)
                                -> dismiss()                "o'tkazildi"
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Camera, FaceGalleryEmbedding, StudentStaff, UnknownSighting
from app.services.face_matching import anchor_hash
from app.timezone import INSTITUTE_TZ, local_now
from app.timezone import business_date, business_today

logger = logging.getLogger("app.unknown_sightings")

UNKNOWN_MODULE_CODE = 1
UNKNOWN_MODULE_NAME = "Notanish/begona shaxsni aniqlash"


class ResolveError(Exception):
    """Operator harakati bajarilmadi — sababi foydalanuvchiga ko'rsatiladi."""


def _unit(vector) -> np.ndarray | None:
    arr = np.asarray(vector, dtype=np.float64)
    norm = float(np.linalg.norm(arr))
    return arr / norm if norm > 0 else None


def _face_px(face) -> int:
    bbox = getattr(face, "bbox", None)
    if bbox is None:
        return 0
    return int(float(bbox[3]) - float(bbox[1]))


def crop_face(frame_bytes: bytes, bbox, margin: float) -> bytes | None:
    """Yuzni atrofi bilan kesib JPEG qaytaradi. Kesib bo'lmasa None.

    Hoshiya yuz o'lchamiga nisbatan: operator odamni yuzidan tashqari
    sochi va kiyimidan ham taniydi."""
    import cv2

    image = cv2.imdecode(np.frombuffer(frame_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return None
    height, width = image.shape[:2]
    x1, y1, x2, y2 = (float(v) for v in bbox[:4])
    pad_x = (x2 - x1) * margin
    pad_y = (y2 - y1) * margin
    left = max(0, int(x1 - pad_x))
    top = max(0, int(y1 - pad_y))
    right = min(width, int(x2 + pad_x))
    bottom = min(height, int(y2 + pad_y * 1.4))  # pastga ko'proq — yelka/kiyim
    if right - left < 8 or bottom - top < 8:
        return None
    ok, encoded = cv2.imencode(".jpg", image[top:bottom, left:right], [cv2.IMWRITE_JPEG_QUALITY, 88])
    return encoded.tobytes() if ok else None


async def _upload_crop(data: bytes) -> str | None:
    from app.storage import upload_file

    try:
        _file_id, key = await asyncio.to_thread(upload_file, data, "yuz.jpg", "image/jpeg", "notanishlar")
    except Exception:
        # Rasmsiz yozuv ham foydali (qachon/qayerda) — saqlash xatosi
        # butun kadrni yo'qotmasin.
        logger.exception("unknown sighting crop upload failed")
        return None
    return key


# Bugungi notanish yuzlar vektorlari (jarayon ichida). Ilgari har chaqiriqda
# kunning barcha qatorlari (1500 tagacha) o'qilib, har birining JSON vektori
# qayta ochilardi — har kameraning har aylanishida. Endi faqat yangi qatorlar.
_DAY_CACHE: dict = {"day": None, "ids": [], "matrix": None}
# Kirish kameralari parallel ishlaydi (har biri o'z vazifasida): kesh
# (ids va matritsa) bitta yozuvchi tomonidan o'qilib-yozilishi kerak —
# aks holda ular bir-biriga mos kelmay qolib, yuz boshqa qatorga
# qo'shilardi. Qulf commit'gacha ushlanadi: boshqa vazifa hali ko'rinmas
# (commit qilinmagan) qatorni "o'chirilgan" deb keshni tozalamasin.
_DAY_LOCK = asyncio.Lock()


async def _day_vectors(db: AsyncSession, day) -> tuple[list, "np.ndarray | None"]:
    current = list((await db.execute(select(UnknownSighting.id).where(UnknownSighting.day == day))).scalars().all())
    cache = _DAY_CACHE
    known = set(cache["ids"])
    if cache["day"] != day or not known.issubset(set(current)):
        # Yangi kun yoki qator o'chirilgan/qaytarilgan — boshidan.
        cache.update(day=day, ids=[], matrix=None)
        known = set()
    missing = [row_id for row_id in current if row_id not in known]
    if missing:
        rows = (
            await db.execute(
                select(UnknownSighting.id, UnknownSighting.embedding).where(UnknownSighting.id.in_(missing))
            )
        ).all()
        for row_id, raw in rows:
            try:
                vector = _unit(json.loads(raw))
            except (ValueError, TypeError):
                vector = None
            if vector is None:
                continue
            cache["ids"].append(row_id)
            cache["matrix"] = vector[None, :] if cache["matrix"] is None else np.vstack([cache["matrix"], vector])
    return cache["ids"], cache["matrix"]


def reset_day_cache_for_tests() -> None:
    _DAY_CACHE.update(day=None, ids=[], matrix=None)


async def record_unknown_faces(
    db: AsyncSession,
    camera: Camera,
    frame_bytes: bytes,
    faces: list,
    closest: list[float | None] | None = None,
    *,
    now: datetime | None = None,
) -> int:
    """Notanish yuzlarni bugungi ro'yxatga yozadi. Qaytaradi: nechta YANGI qator.

    O'xshash yuz (settings.unknown_merge_similarity) bugun allaqachon
    yozilgan bo'lsa — yangi qator emas: `hits` oshadi, rasm yirikrog'i
    bilan almashadi. Commit — shu yerda (sweep har kamerada o'z
    sessiyasini ochadi)."""
    if not faces:
        return 0
    async with _DAY_LOCK:
        return await _record_locked(db, camera, frame_bytes, faces, closest, now)


async def _record_locked(db, camera, frame_bytes, faces, closest, now) -> int:
    moment = now or datetime.now(timezone.utc)
    day = business_today() if now is None else business_date(moment)

    ids, matrix = await _day_vectors(db, day)
    replaced: list[str] = []

    created = 0
    for index, face in enumerate(faces):
        vector = _unit(getattr(face, "embedding", None)) if getattr(face, "embedding", None) is not None else None
        if vector is None:
            continue
        px = _face_px(face)

        best_row, best_pos = None, -1
        if matrix is not None and len(ids):
            sims = matrix @ vector
            best_pos = int(np.argmax(sims))
            if float(sims[best_pos]) >= settings.unknown_merge_similarity:
                best_row = await db.get(UnknownSighting, ids[best_pos])

        if best_row is not None:
            best_row.hits += 1
            best_row.last_seen_at = moment
            # Yirikroq yuz — aniqroq rasm va ishonchliroq vektor.
            if px > best_row.face_px:
                crop = await asyncio.to_thread(crop_face, frame_bytes, face.bbox, settings.unknown_crop_margin)
                key = await _upload_crop(crop) if crop else None
                if key:
                    if best_row.crop_key:
                        replaced.append(best_row.crop_key)
                    best_row.crop_key = key
                    best_row.face_px = px
                    best_row.embedding = json.dumps([round(float(v), 6) for v in vector])
                    matrix[best_pos] = vector
            continue

        if len(ids) >= settings.unknown_daily_cap:
            logger.warning("unknown sightings daily cap reached", extra={"cap": settings.unknown_daily_cap})
            break

        crop = await asyncio.to_thread(crop_face, frame_bytes, face.bbox, settings.unknown_crop_margin)
        key = await _upload_crop(crop) if crop else None
        row = UnknownSighting(
            day=day,
            camera_id=camera.id,
            first_seen_at=moment,
            last_seen_at=moment,
            hits=1,
            embedding=json.dumps([round(float(v), 6) for v in vector]),
            crop_key=key,
            face_px=px,
            closest_similarity=(closest[index] if closest and index < len(closest) else None),
            status="kutilmoqda",
        )
        db.add(row)
        await db.flush()  # id kerak — keshga shu bilan qo'shiladi
        ids.append(row.id)
        matrix = vector[None, :] if matrix is None else np.vstack([matrix, vector])
        _DAY_CACHE["matrix"] = matrix
        created += 1

    try:
        await db.commit()
    except Exception:
        # Qatorlar yozilmadi — kesh bazaga mos emas, keyingi chaqiriq qayta quradi.
        reset_day_cache_for_tests()
        raise
    if replaced:
        # Almashtirilgan eski rasmlar omborda yetim qolmasin.
        from app.storage import delete_files_quietly

        await delete_files_quietly(replaced)
    return created


async def _other_lookalike(db: AsyncSession, vector: np.ndarray, exclude: uuid.UUID) -> tuple[str, float] | None:
    """Tanlangan odamdan BOSHQA tasdiqlangan odamga juda o'xshaydimi."""
    rows = (
        await db.execute(
            select(StudentStaff.id, StudentStaff.full_name, StudentStaff.biometric_embedding).where(
                StudentStaff.biometrics_status == "tasdiqlangan",
                StudentStaff.biometric_embedding.is_not(None),
                StudentStaff.id != exclude,
            )
        )
    ).all()
    best: tuple[str, float] | None = None
    for _pid, name, raw in rows:
        try:
            stored = _unit(json.loads(raw))
        except (ValueError, TypeError):
            continue
        if stored is None:
            continue
        sim = float(stored @ vector)
        if sim >= settings.self_enrollment_duplicate_threshold and (best is None or sim > best[1]):
            best = (name, sim)
    return best


#: Yuzi yo'q odamga notanish yuz registrga tekshiruv uchun tushganda.
ASSIGN_REVIEW_REASON = "Notanish yuzlar ro'yxatidan biriktirildi — rasmni tekshirib tasdiqlang"


async def assign_to_person(
    db: AsyncSession,
    sighting: UnknownSighting,
    person: StudentStaff,
    user_id: uuid.UUID | None,
    *,
    can_enroll: bool = False,
) -> str:
    """Yuzni odamga biriktiradi. Qaytaradi: "galereya", "asosiy" yoki
    "tekshiruvda" (yuzi yo'q odam, biriktiruvchida registerPeople yo'q).

    * Odamning yuzi bor — kamera namunasi galereyaga qo'shiladi (asl
      rasmga yetarli o'xshashi sharti bilan: operator xato odamni
      tanlagan bo'lsa, begona yuz o'sha odamning nomidan tanilib qolardi).
    * Odamning yuzi yo'q — shu kamera rasmi uning ASOSIY yuzi bo'ladi
      (boshqa tasdiqlangan odamga juda o'xshamasa). Bu qamrovni o'stiradi:
      ertaga kamera uni o'zi taniydi.
    """
    if sighting.status != "kutilmoqda":
        raise ResolveError("Bu yozuv allaqachon ko'rib chiqilgan")
    if not person.active:
        raise ResolveError(f"{person.full_name} faol emas — yuz biriktirilmaydi")
    vector = _unit(json.loads(sighting.embedding))
    if vector is None:
        raise ResolveError("Yuz ma'lumoti buzilgan")

    hit = await _other_lookalike(db, vector, person.id)
    if hit:
        raise ResolveError(f"Bu yuz {hit[0]} ga juda o'xshaydi ({hit[1]:.2f}) — boshqa odamni tanlagan bo'lishingiz mumkin")

    kind: str
    if person.biometric_embedding:
        anchor = _unit(json.loads(person.biometric_embedding))
        similarity = float(anchor @ vector) if anchor is not None else 0.0
        if similarity < settings.unknown_assign_min_similarity:
            raise ResolveError(
                f"Bu yuz {person.full_name} ning asl rasmiga o'xshamaydi ({similarity:.2f}) — boshqa odam bo'lishi mumkin"
            )
        db.add(
            FaceGalleryEmbedding(
                student_staff_id=person.id,
                embedding=sighting.embedding,
                anchor_hash=anchor_hash(person.biometric_embedding),
                similarity=similarity,
                face_px=sighting.face_px,
                camera_id=sighting.camera_id,
            )
        )
        kind = "galereya"
    else:
        # Yuzi yo'q odamga kamera kadridan bitta burchakli yuz kiritilmaydi:
        # yuz faqat 3 tomondan (ro'yxatdan o'tish havolasi) olinadi.
        raise ResolveError(
            f"{person.full_name}ning yuzi hali kiritilmagan — yuz faqat 3 tomondan (ro'yxatdan o'tish havolasi) olinadi"
        )

    sighting.status = "talaba"
    sighting.person_id = person.id
    sighting.resolved_by = user_id
    sighting.resolved_at = datetime.now(timezone.utc)
    return kind


async def mark_stranger(db: AsyncSession, sighting: UnknownSighting, user_id: uuid.UUID | None):
    """Haqiqiy begona — odatdagi #1 hodisa yaratiladi (rasmi bilan)."""
    from app.services.event_bus import raise_event
    from app.storage import read_file

    if sighting.status != "kutilmoqda":
        raise ResolveError("Bu yozuv allaqachon ko'rib chiqilgan")
    camera = await db.get(Camera, sighting.camera_id) if sighting.camera_id else None
    if camera is None:
        raise ResolveError("Kamera topilmadi — hodisa yaratib bo'lmaydi")
    frame: bytes | None = None
    if sighting.crop_key:
        try:
            frame = await asyncio.to_thread(read_file, sighting.crop_key)
        except Exception:
            logger.exception("unknown sighting crop read failed")
    event = await raise_event(
        db,
        camera=camera,
        module_code=UNKNOWN_MODULE_CODE,
        module_name=UNKNOWN_MODULE_NAME,
        group="A",
        # Operator o'z ko'zi bilan tasdiqlagan — modul chegarasidan o'tishi shart.
        confidence=100,
        severity="yuqori",
        frame_bytes=frame,
        details={
            "reason": f"Operator tasdiqladi: begona shaxs ({sighting.hits} marta ko'ringan)",
            "metrics": {"hits": sighting.hits, "closest": sighting.closest_similarity},
        },
    )
    sighting.status = "begona"
    sighting.event_id = event.id if event is not None else None
    sighting.resolved_by = user_id
    sighting.resolved_at = datetime.now(timezone.utc)
    return event


def dismiss(sighting: UnknownSighting, user_id: uuid.UUID | None) -> None:
    if sighting.status != "kutilmoqda":
        raise ResolveError("Bu yozuv allaqachon ko'rib chiqilgan")
    sighting.status = "otkazildi"
    sighting.resolved_by = user_id
    sighting.resolved_at = datetime.now(timezone.utc)


async def pending_count(db: AsyncSession, day) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(UnknownSighting)
                .where(UnknownSighting.day == day, UnknownSighting.status == "kutilmoqda")
            )
        ).scalar_one()
    )
