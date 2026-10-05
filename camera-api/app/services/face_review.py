"""Yuz tekshiruvi navbati — "kulrang zona" mosliklarini operatorga berish.

Model va nega kerakligi: app/models/face_review.py.

Oqim:
  attendance_ai.process_camera_frame -> queue_grey_matches()  qator yoziladi/yangilanadi
  operator "Ha, u"                   -> confirm()             galereya + davomat
  operator "Yo'q"                    -> reject()
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AttendanceRecord, Camera, FaceGalleryEmbedding, FaceReviewItem, StudentStaff
from app.services import recognition_stats
from app.services.face_matching import CandidateMatrix, anchor_hash
from app.services.face_recognition import face_quality_ok
from app.services.unknown_sightings import crop_face
from app.timezone import INSTITUTE_TZ
from app.timezone import business_date

logger = logging.getLogger("app.face_review")

PENDING = "kutilmoqda"
CONFIRMED = "tasdiqlandi"
REJECTED = "rad_etildi"
STATUSES = (PENDING, CONFIRMED, REJECTED)


class ReviewError(Exception):
    """Operator harakati bajarilmadi — sababi foydalanuvchiga ko'rsatiladi."""


def _unit(vector) -> np.ndarray | None:
    arr = np.asarray(vector, dtype=np.float64)
    norm = float(np.linalg.norm(arr))
    return arr / norm if norm > 0 else None


def _vector_json(vector: np.ndarray) -> str:
    return json.dumps([round(float(v), 6) for v in vector])


async def _upload_crop(data: bytes) -> str | None:
    from app.storage import upload_file

    try:
        _file_id, key = await asyncio.to_thread(upload_file, data, "yuz.jpg", "image/jpeg", "tekshiruv")
    except Exception:
        # Rasmsiz qator ham ko'rsatiladi (ism, vaqt) — saqlash xatosi kadrni yo'qotmasin.
        logger.exception("face review crop upload failed")
        return None
    return key


def grey_candidates(usable: list, graded: list, candidates: CandidateMatrix, credited: set[str]) -> list[tuple]:
    """Navbatga munosib yuzlar: (yuz, odam_id, o'xshashlik, ikkinchi).

    Faqat davomatga YOZILMAGAN, yetarlicha yirik va sifatli yuz; eng yaqin
    nomzod [face_review_min_similarity, qat'iy chegara) oralig'ida va
    ikkinchisidan face_review_min_margin uzoq. Nomzod top_two dan olinadi:
    graded natijada "none" bo'lgan yuzning person_id si bo'sh."""
    if candidates.is_empty:
        return []
    pool = [
        (face, match)
        for face, match in zip(usable, graded, strict=True)
        if (match.person_id is None or match.person_id not in credited)
        and settings.face_review_min_similarity <= match.similarity < settings.attendance_ai_match_threshold
        and recognition_stats.face_height_px(face) >= settings.attendance_min_face_px
        and face_quality_ok(face)
    ]
    if not pool:
        return []
    best_idx, best_sim, second = candidates.top_two(np.stack([face.embedding for face, _ in pool]))
    out: list[tuple] = []
    seen: set[str] = set()
    for (face, match), idx, sim, sim2 in zip(pool, best_idx, best_sim, second, strict=True):
        if int(idx) < 0:
            continue
        sim, sim2 = float(sim), float(sim2)
        if not (settings.face_review_min_similarity <= sim < settings.attendance_ai_match_threshold):
            continue
        if sim - sim2 < settings.face_review_min_margin:
            continue
        # Faqat galereya namunasi orqali topilgan (asl rasmga o'xshamaydi) —
        # graded_matches bunday yuzga nom bermaydi, navbat ham bermaydi.
        if match.anchor_similarity is not None and match.anchor_similarity < settings.face_gallery_anchor_floor:
            continue
        person_id = candidates.ids[int(idx)]
        if person_id in credited or person_id in seen:
            continue
        seen.add(person_id)
        out.append((face, person_id, sim, sim2))
    return out


async def queue_grey_matches(
    db: AsyncSession,
    camera: Camera,
    frame_bytes: bytes,
    usable: list,
    graded: list,
    candidates: CandidateMatrix,
    credited: set[str],
    *,
    now: datetime | None = None,
) -> int:
    """Kulrang zona mosliklarini navbatga yozadi. Qaytaradi: nechta YANGI qator.

    Bugun davomati allaqachon bor odam o'tkaziladi — uni tasdiqlashdan
    foyda yo'q, navbat esa shovqinga to'lardi. Commit — shu yerda."""
    if not settings.face_review_enabled:
        return 0
    grey = grey_candidates(usable, graded, candidates, credited)
    if not grey:
        return 0
    moment = now or datetime.now(timezone.utc)
    day = business_date(moment)
    person_ids = [uuid.UUID(pid) for _, pid, _, _ in grey]

    present = set(
        (
            await db.execute(
                select(AttendanceRecord.student_staff_id).where(
                    AttendanceRecord.date == day,
                    AttendanceRecord.student_staff_id.in_(person_ids),
                    # "kelmadi" — kamera ko'rsa tuzatiladi, ya'ni tekshiruvga arziydi.
                    AttendanceRecord.status != "kelmadi",
                )
            )
        ).scalars()
    )
    grey = [item for item in grey if uuid.UUID(item[1]) not in present]
    if not grey:
        return 0

    existing = {
        row.person_id: row
        for row in (
            await db.execute(
                select(FaceReviewItem).where(
                    FaceReviewItem.day == day,
                    FaceReviewItem.camera_id == camera.id,
                    FaceReviewItem.person_id.in_([uuid.UUID(item[1]) for item in grey]),
                )
            )
        ).scalars()
    }

    created = 0
    day_total: int | None = None
    for face, person_key, sim, sim2 in grey:
        vector = _unit(face.embedding)
        if vector is None:
            continue
        px = recognition_stats.face_height_px(face)
        row = existing.get(uuid.UUID(person_key))
        if row is not None:
            if row.status != PENDING:
                continue  # operator allaqachon qaror qilgan — qayta ochilmaydi
            row.hits += 1
            row.last_seen_at = moment
            # Yirikroq yoki o'xshashroq yuz — operator uchun aniqroq rasm,
            # galereya uchun ishonchliroq vektor.
            if px > row.face_px or sim > row.similarity:
                crop = await asyncio.to_thread(crop_face, frame_bytes, face.bbox, settings.unknown_crop_margin)
                key = await _upload_crop(crop) if crop else None
                if key:
                    row.crop_key = key
                row.face_px = px
                row.similarity = sim
                row.second_similarity = sim2
                row.embedding = _vector_json(vector)
            continue

        if day_total is None:
            day_total = int(
                (
                    await db.execute(
                        select(func.count()).select_from(FaceReviewItem).where(FaceReviewItem.day == day)
                    )
                ).scalar_one()
            )
        if day_total >= settings.face_review_daily_cap:
            logger.warning("face review daily cap reached", extra={"cap": settings.face_review_daily_cap})
            break
        crop = await asyncio.to_thread(crop_face, frame_bytes, face.bbox, settings.unknown_crop_margin)
        key = await _upload_crop(crop) if crop else None
        db.add(
            FaceReviewItem(
                day=day,
                camera_id=camera.id,
                person_id=uuid.UUID(person_key),
                first_seen_at=moment,
                last_seen_at=moment,
                hits=1,
                similarity=sim,
                second_similarity=sim2,
                embedding=_vector_json(vector),
                crop_key=key,
                face_px=px,
                status=PENDING,
            )
        )
        day_total += 1
        created += 1

    await db.commit()
    return created


async def _add_gallery_sample(db: AsyncSession, item: FaceReviewItem, person: StudentStaff) -> bool:
    """Tasdiqlangan yuzni galereyaga qo'shadi. True — qo'shildi.

    Galereya to'la bo'lsa ENG ESKI namuna almashtiriladi: odam tasdiqlagan
    "qiyin" kadr (past o'xshashlik, CCTV burchagi) avtomatik yig'ilgan
    oson kadrlardan ko'ra ko'proq foyda beradi — aynan u tanishni o'stiradi."""
    if not settings.face_gallery_enabled or not person.biometric_embedding:
        return False
    vector = _unit(json.loads(item.embedding))
    anchor = _unit(json.loads(person.biometric_embedding))
    if vector is None or anchor is None:
        return False
    anchor_sim = float(anchor @ vector)
    if anchor_sim < settings.unknown_assign_min_similarity:
        raise ReviewError(
            f"Bu yuz {person.full_name} ning asl rasmiga o'xshamaydi ({anchor_sim:.2f}) — tasdiqlab bo'lmaydi"
        )
    current_hash = anchor_hash(person.biometric_embedding)
    samples = list(
        (
            await db.execute(
                select(FaceGalleryEmbedding)
                .where(
                    FaceGalleryEmbedding.student_staff_id == person.id,
                    FaceGalleryEmbedding.anchor_hash == current_hash,
                )
                .order_by(FaceGalleryEmbedding.created_at)
            )
        ).scalars()
    )
    for sample in samples:
        stored = _unit(json.loads(sample.embedding))
        if stored is not None and float(stored @ vector) >= settings.face_gallery_dedupe_similarity:
            return False  # deyarli bir xil namuna bor — yangi ma'lumot bermaydi
    if len(samples) >= settings.face_gallery_max_per_person:
        await db.execute(delete(FaceGalleryEmbedding).where(FaceGalleryEmbedding.id == samples[0].id))
    db.add(
        FaceGalleryEmbedding(
            student_staff_id=person.id,
            embedding=_vector_json(vector),
            anchor_hash=current_hash,
            similarity=anchor_sim,
            face_px=item.face_px,
            camera_id=item.camera_id,
        )
    )
    return True


async def confirm(db: AsyncSession, item: FaceReviewItem, user_id: uuid.UUID | None) -> bool:
    """"Ha, u": galereya namunasi + holat. Davomatni chaqiruvchi yozadi
    (upsert_attendance_from_recognition commit qiladi — audit undan oldin
    qo'shilishi kerak). Qaytaradi: galereyaga qo'shildimi."""
    if item.status != PENDING:
        raise ReviewError("Bu yozuv allaqachon ko'rib chiqilgan")
    person = await db.get(StudentStaff, item.person_id)
    if person is None:
        raise ReviewError("Odam topilmadi")
    added = await _add_gallery_sample(db, item, person)
    item.status = CONFIRMED
    item.resolved_by = user_id
    item.resolved_at = datetime.now(timezone.utc)
    return added


def reject(item: FaceReviewItem, user_id: uuid.UUID | None) -> None:
    if item.status != PENDING:
        raise ReviewError("Bu yozuv allaqachon ko'rib chiqilgan")
    item.status = REJECTED
    item.resolved_by = user_id
    item.resolved_at = datetime.now(timezone.utc)
