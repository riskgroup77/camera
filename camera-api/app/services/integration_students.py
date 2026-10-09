"""iMentor integratsiyasi: talabani HEMIS ID, JSHSHIR yoki yuz orqali aniqlash.

Faqat "bu kim?" savoliga javob — bazaga hech narsa yozilmaydi (audit
jurnalidan tashqari), yuborilgan rasm diskka saqlanmaydi.

Bazada YO'Q maydonlar (o'ylab topilmaydi, null): specialty, education_form.
first/last/middle_name — F.I.Sh. ("Familiya Ism Otasining_ismi ...") so'zlaridan
ajratiladi; chet ellik talabalardagi "Xxx" to'ldirgichi tashlanadi.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models import StudentStaff
from app.services.face_matching import load_candidate_matrix_cached
from app.services.face_recognition import NoFaceDetectedError, detect_faces
from app.services.inference_gate import PRIORITY_LIVE

PINFL_RE = re.compile(r"^\d{14}$")
_COURSE_RE = re.compile(r"(\d+)\s*-\s*kurs", re.IGNORECASE)
_NOT_IN_HEMIS = "HEMIS'da topilmadi"
# Selfidagi orqa fondagi yuz "ikki yuz" emas: eng katta yuzning shu
# ulushidan kichiklari hisobga olinmaydi.
SECOND_FACE_MIN_RATIO = 0.35


class IdentifyError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def mask_pinfl(pinfl: str | None) -> str:
    """Audit uchun: 12345678901234 -> 1234********34."""
    if not pinfl:
        return "-"
    return pinfl[:4] + "*" * max(0, len(pinfl) - 6) + pinfl[-2:] if len(pinfl) > 6 else "*" * len(pinfl)


def split_name(full_name: str) -> tuple[str | None, str | None, str | None]:
    """(last, first, middle). Bitta so'z bo'lsa — ajratib bo'lmaydi."""
    words = [w for w in (full_name or "").split() if w.lower() != "xxx"]
    if len(words) < 2:
        return None, None, None
    return words[0], words[1], (" ".join(words[2:]) or None)


def split_group(group_or_position: str | None) -> tuple[str | None, int | None]:
    """"3-kurs, TPI-423" -> ("TPI-423", 3)."""
    text = (group_or_position or "").strip()
    if not text or text == _NOT_IN_HEMIS:
        return None, None
    match = _COURSE_RE.search(text)
    course = int(match.group(1)) if match else None
    group = text.split(",", 1)[1].strip() if "," in text else (None if match else text)
    return group or None, course


def student_payload(person: StudentStaff, *, matched_by: str, confidence: float | None = None) -> dict:
    last, first, middle = split_name(person.full_name)
    group, course = split_group(person.group_or_position)
    payload = {
        "student_id": person.hemis_id,
        "pinfl": person.pinfl,
        "full_name": person.full_name,
        "first_name": first,
        "last_name": last,
        "middle_name": middle,
        "group_name": group,
        "course": course,
        "faculty": person.faculty.name if person.faculty else None,
        "specialty": None,  # bazada yo'q
        "education_form": None,  # bazada yo'q
        "status": "active" if person.active else "inactive",
        # HEMIS'dagi rasmiy portret. Biometrik (ro'yxatdan o'tish) rasmlari
        # tashqariga berilmaydi.
        "photo_url": person.hemis_photo_url or None,
        "matched_by": matched_by,
    }
    if confidence is not None:
        payload["confidence"] = round(float(confidence), 3)
    return payload


def _students():
    return select(StudentStaff).options(selectinload(StudentStaff.faculty)).where(StudentStaff.type == "talaba")


async def find_by_student_id(db: AsyncSession, student_id: str) -> StudentStaff | None:
    rows = (await db.execute(_students().where(StudentStaff.hemis_id == student_id))).scalars().all()
    return max(rows, key=lambda p: p.active, default=None)


async def find_by_pinfl(db: AsyncSession, pinfl: str) -> StudentStaff | None:
    return (await db.execute(_students().where(StudentStaff.pinfl == pinfl))).scalars().first()


async def find_by_id(db: AsyncSession, person_id) -> StudentStaff | None:
    return (await db.execute(_students().where(StudentStaff.id == person_id))).scalars().first()


@dataclass
class FaceMatch:
    person: StudentStaff
    confidence: float


def _face_height(face) -> float:
    return float(face.bbox[3] - face.bbox[1])


async def identify_face(db: AsyncSession, image: bytes) -> FaceMatch:
    """Rasmdagi YAGONA yuzni ro'yxatdan o'tgan talabalar bilan solishtiradi."""
    try:
        faces = await detect_faces(image, priority=PRIORITY_LIVE, enrollment=True, landmarks=False)
    except NoFaceDetectedError as exc:
        raise IdentifyError(400, "invalid_image", "Rasmni o'qib bo'lmadi") from exc
    analysed = [f for f in faces if f.embedding is not None]
    if not analysed:
        raise IdentifyError(422, "no_face", "Rasmda yuz topilmadi")
    largest = max(_face_height(f) for f in analysed)
    real = [f for f in analysed if _face_height(f) >= SECOND_FACE_MIN_RATIO * largest]
    if len(real) > 1:
        raise IdentifyError(422, "multiple_faces", "Rasmda bir nechta yuz bor — bitta odam bo'lishi kerak")
    candidates = await load_candidate_matrix_cached(db)
    match = candidates.best_matches(
        np.asarray([real[0].embedding]), settings.integration_face_threshold, margin=settings.integration_face_margin
    )[0]
    if match is None or candidates.person_type(str(match[0])) not in (None, "talaba"):
        raise IdentifyError(404, "not_matched", "Mos talaba topilmadi")
    person = await find_by_id(db, uuid.UUID(str(match[0])))
    if person is None:
        raise IdentifyError(404, "not_matched", "Mos talaba topilmadi")
    return FaceMatch(person=person, confidence=match[1])
