"""Kamera-domen yuz galereyasi — ishonchli tanilgan kadrlardan odamning
qo'shimcha namunalarini yig'ish (app/models/face_gallery.py izohiga qarang).

Namuna qo'shish shartlari (hammasi bir vaqtda):
  * moslik ASL rasm bilan (galereya namunasi orqali emas) o'xshashlik
    >= face_gallery_min_similarity va ikkinchi nomzoddan
    >= face_gallery_min_margin uzoq;
  * yuz katta (>= face_gallery_min_face_px) va sifatli
    (face_recognition.face_quality_ok);
  * odamda hali face_gallery_max_per_person dan kam namuna bor, oxirgisi
    face_gallery_min_interval_seconds dan oldin qo'shilgan va yangi vektor
    mavjud namunalarning hech biriga face_gallery_dedupe_similarity dan
    yaqin emas (xilma-xillik: bir xil kadrlar galereyani to'ldirmasin).

Yangi namuna keyingi ro'yxat keshi yangilanishida (sweep keshi TTL)
matritsaga kiradi — har qo'shishda butun ro'yxatni qayta yuklash shart emas.
"""

import json
import logging
import time
import uuid

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import FaceGalleryEmbedding, StudentStaff
from app.services.face_matching import GradedMatch, anchor_hash
from app.services.face_recognition import face_quality_ok

logger = logging.getLogger("app.face_gallery")

# odam_id -> oxirgi urinish (monotonic) — bazaga har kadrda so'rov yubormaslik uchun.
_last_attempt: dict[str, float] = {}


def reset_for_tests() -> None:
    _last_attempt.clear()


def _face_px(face) -> int:
    bbox = getattr(face, "bbox", None)
    if bbox is None:
        return 0
    return int(float(bbox[3]) - float(bbox[1]))


def qualifies(face, match: GradedMatch) -> bool:
    """Kadr darajasidagi shartlar (bazaga murojaatsiz)."""
    if not (settings.face_gallery_enabled and settings.face_gallery_auto_add):
        return False
    if match.person_id is None or match.grade != "strict":
        return False
    anchor = match.anchor_similarity if match.anchor_similarity is not None else match.similarity
    if anchor < settings.face_gallery_min_similarity:
        return False
    if match.similarity - match.second_similarity < settings.face_gallery_min_margin:
        return False
    if _face_px(face) < settings.face_gallery_min_face_px:
        return False
    if getattr(face, "embedding", None) is None:
        return False
    return face_quality_ok(face)


async def maybe_add(
    db: AsyncSession,
    face,
    match: GradedMatch,
    camera_id: uuid.UUID | str | None = None,
    *,
    now: float | None = None,
) -> bool:
    """Shartlar bajarilsa namunani qo'shadi (commit — chaqiruvchida). True — qo'shildi."""
    if not qualifies(face, match):
        return False
    person_key = str(match.person_id)
    moment = time.monotonic() if now is None else now
    last = _last_attempt.get(person_key)
    if last is not None and moment - last < settings.face_gallery_min_interval_seconds:
        return False
    _last_attempt[person_key] = moment

    person_id = uuid.UUID(person_key)
    anchor_json = (
        await db.execute(select(StudentStaff.biometric_embedding).where(StudentStaff.id == person_id))
    ).scalar_one_or_none()
    if not anchor_json:
        return False
    current_hash = anchor_hash(anchor_json)
    existing = (
        await db.execute(
            select(FaceGalleryEmbedding.embedding).where(
                FaceGalleryEmbedding.student_staff_id == person_id,
                FaceGalleryEmbedding.anchor_hash == current_hash,
            )
        )
    ).scalars().all()
    if len(existing) >= settings.face_gallery_max_per_person:
        return False
    embedding = np.asarray(face.embedding, dtype=np.float64)
    norm = np.linalg.norm(embedding)
    if norm <= 0:
        return False
    embedding = embedding / norm
    # Moslik keshdagi (eski bo'lishi mumkin) rasmga nisbatan topilgan: rasm
    # hozirgina almashtirilgan bo'lsa, namuna yangi rasmga ham o'xshashi
    # shart — aks holda eski yuz yangi rasm kaliti ostida qolib ketardi.
    anchor = np.asarray(json.loads(anchor_json), dtype=np.float64)
    anchor_norm = np.linalg.norm(anchor)
    if anchor_norm <= 0 or anchor.shape != embedding.shape:
        return False
    if float(anchor @ embedding) / anchor_norm < settings.face_gallery_min_similarity:
        return False
    if existing:
        stored = np.array([json.loads(item) for item in existing], dtype=np.float64)
        stored /= np.maximum(np.linalg.norm(stored, axis=1, keepdims=True), 1e-12)
        if float((stored @ embedding).max()) >= settings.face_gallery_dedupe_similarity:
            return False

    camera_uuid = None
    if camera_id is not None:
        camera_uuid = camera_id if isinstance(camera_id, uuid.UUID) else uuid.UUID(str(camera_id))
    db.add(
        FaceGalleryEmbedding(
            student_staff_id=person_id,
            embedding=json.dumps([round(float(v), 6) for v in embedding]),
            anchor_hash=current_hash,
            similarity=float(match.anchor_similarity if match.anchor_similarity is not None else match.similarity),
            face_px=_face_px(face),
            camera_id=camera_uuid,
        )
    )
    logger.info(
        "face gallery sample added",
        extra={"student_staff_id": person_key, "face_px": _face_px(face), "samples": len(existing) + 1},
    )
    return True


async def gallery_counts(db: AsyncSession) -> dict[str, int]:
    rows = (
        await db.execute(
            select(FaceGalleryEmbedding.student_staff_id, func.count()).group_by(FaceGalleryEmbedding.student_staff_id)
        )
    ).all()
    return {str(person_id): int(count) for person_id, count in rows}
