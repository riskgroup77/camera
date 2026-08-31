"""Public (no-auth) self-service biometric enrollment — lets a student/staff
member whose record was bulk-imported without a photo (see the Excel import
this backs) attach their own face, instead of every person needing an
admin operator to run them through AddStudentStaffModal.tsx by hand.

Identity is proven with passport series+number (StudentStaff.passport_series/
passport_number) since these records have no login/password of their own —
this is NOT a JWT session, just enough to answer "which existing row is
this". Both endpoints are IP rate-limited (see app/rate_limit.py) since
passport series+number is a guessable-in-bulk secret, not a strong one.

/submit re-checks passport_series/passport_number itself (not just
record_id) so a client can't skip /lookup and brute-force record ids
directly, and refuses to overwrite an already-confirmed enrollment —
self-service is for filling in a MISSING photo, not for silently replacing
someone else's already-verified one; an admin has to do that deliberately
via the existing /api/students-staff/{id}/biometrics endpoint.
"""

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import StudentStaff
from app.rate_limit import limiter
from app.schemas.enrollment import EnrollmentLookupIn, EnrollmentLookupOut, EnrollmentSubmitOut
from app.services.face_matching import invalidate_candidate_matrix_cache
from app.services.face_recognition import (
    InconsistentFacesError,
    NoFaceDetectedError,
    extract_enrollment_embedding,
)
from app.storage import upload_file

logger = logging.getLogger("app.enrollment")

router = APIRouter(prefix="/api/public/enrollment", tags=["enrollment"])

MAX_PHOTO_SIZE_BYTES = 10 * 1024 * 1024
MIN_FRAMES = 2
MAX_FRAMES = 6


def _normalize(series: str, number: str) -> tuple[str, str]:
    return series.strip().upper(), number.strip()


async def _find_by_passport(db: AsyncSession, series: str, number: str) -> StudentStaff | None:
    result = await db.execute(
        select(StudentStaff)
        .where(StudentStaff.passport_series == series)
        .where(StudentStaff.passport_number == number)
    )
    return result.scalar_one_or_none()


@router.post("/lookup", response_model=EnrollmentLookupOut)
@limiter.limit("5/minute")
async def lookup_by_passport(
    request: Request,
    body: EnrollmentLookupIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EnrollmentLookupOut:
    series, number = _normalize(body.passport_series, body.passport_number)
    record = await _find_by_passport(db, series, number)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bunday pasport ma'lumotlari bilan yozuv topilmadi")

    return EnrollmentLookupOut(
        record_id=str(record.id),
        full_name=record.full_name,
        type_label="Talaba" if record.type == "talaba" else "Xodim",
        group_or_position=record.group_or_position,
        already_enrolled=record.biometrics_status == "tasdiqlangan",
    )


@router.post("/{record_id}/submit", response_model=EnrollmentSubmitOut)
@limiter.limit("3/minute")
async def submit_enrollment(
    request: Request,
    record_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    passport_series: Annotated[str, Form(alias="passportSeries")],
    passport_number: Annotated[str, Form(alias="passportNumber")],
    photos: Annotated[
        list[UploadFile],
        File(description="Turli burchaklardan olingan yuz kadrlari — birinchisi to'g'ridan qaragan holat"),
    ],
) -> EnrollmentSubmitOut:
    result = await db.execute(
        select(StudentStaff).options(selectinload(StudentStaff.faculty)).where(StudentStaff.id == record_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")

    series, number = _normalize(passport_series, passport_number)
    if record.passport_series != series or record.passport_number != number:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Pasport ma'lumotlari mos kelmadi")

    if record.biometrics_status == "tasdiqlangan":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Siz allaqachon ro'yxatdan o'tgansiz. O'zgartirish uchun administratorga murojaat qiling.",
        )

    if not (MIN_FRAMES <= len(photos) <= MAX_FRAMES):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"{MIN_FRAMES}-{MAX_FRAMES} ta kadr yuborilishi kerak"
        )

    frames: list[bytes] = []
    for photo in photos:
        data = await photo.read()
        if len(data) > MAX_PHOTO_SIZE_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Har bir kadr 10 MB dan oshmasligi kerak")
        frames.append(data)

    try:
        embedding = await extract_enrollment_embedding(frames)
    except (NoFaceDetectedError, InconsistentFacesError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    _file_id, key = upload_file(frames[0], "face.jpg", "image/jpeg", "biometrics")
    record.biometric_photo_key = key
    record.biometric_embedding = json.dumps(embedding)
    record.biometrics_status = "tasdiqlangan"

    await db.commit()
    logger.info("self-service biometric enrollment completed", extra={"record_id": record_id})
    invalidate_candidate_matrix_cache()
    return EnrollmentSubmitOut(full_name=record.full_name, biometrics_status=record.biometrics_status)
