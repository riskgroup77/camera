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

import asyncio
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Faculty, StudentStaff
from app.rate_limit import limiter
from app.schemas.enrollment import (
    EnrollmentFacultyOut,
    EnrollmentLookupIn,
    EnrollmentLookupOut,
    EnrollmentRegisterIn,
    EnrollmentSubmitOut,
)
from app.services.face_matching import invalidate_candidate_matrix_cache
from app.services.face_recognition import (
    InconsistentFacesError,
    NoFaceDetectedError,
    extract_enrollment_embedding,
)
from app.storage import delete_files_quietly, upload_file

logger = logging.getLogger("app.enrollment")

router = APIRouter(prefix="/api/public/enrollment", tags=["enrollment"])

MAX_PHOTO_SIZE_BYTES = 10 * 1024 * 1024
MIN_FRAMES = 1
"""Bitta rasm ham yetarli.

Avval 2 ta talab qilinardi, chunki oqim faqat kameradan ko'p burchakli
suratga olishni bilardi va bir nechta kadr o'rtachasi bitta kadrdan
ishonchliroq. Endi odam tayyor rasmini yuklashi mumkin, va u yerda
"ikkinchi burchak" degan tushuncha yo'q.

E'tiborga loyiq narsa: yuklangan rasm jonli suratga olishdan ZAIFROQ
dalil — uni boshqa odamning rasmi bilan almashtirib bo'ladi. Bu mahsulot
qarori, xavfsizlik jihatidan emas: jarayonni oddiylashtirish uchun
qabul qilingan."""
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


@router.get("/faculties", response_model=list[EnrollmentFacultyOut])
async def list_faculties(db: Annotated[AsyncSession, Depends(get_db)]) -> list[EnrollmentFacultyOut]:
    """Ro'yxatdan o'tish formasidagi fakultet ro'yxati.

    Ochiq, chunki forma ham ochiq — hisobi yo'q odam aynan shu yerda
    ro'yxatdan o'tadi. Faqat id va nom qaytariladi: talabalar soni kabi
    ichki ko'rsatkichlar bu yerga kerak emas."""
    result = await db.execute(select(Faculty).order_by(Faculty.name))
    return [EnrollmentFacultyOut(id=str(f.id), name=f.name) for f in result.scalars().all()]


@router.post("/register", response_model=EnrollmentLookupOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
async def register_self(
    request: Request,
    body: EnrollmentRegisterIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EnrollmentLookupOut:
    """Tizimda yozuvi yo'q odam o'zini o'zi ro'yxatdan o'tkazadi.

    Ilgari bunday odam uchun yo'l yo'q edi: pasport topilmasa 404 qaytardi
    va jarayon shu yerda tugardi — administrator qo'lda kiritishi kerak
    edi.

    Yaratilgan yozuv biometrics_status='yoq' bilan boshlanadi: bu faqat
    shaxs ma'lumoti, hali yuz emas. Yuz keyingi qadamda qo'shiladi va
    aynan o'sha yerda 'tasdiqlangan' bo'ladi.

    Cheklov (3/minute) va pasport takrorlanmasligi tekshiruvi ataylab:
    endpoint ochiq, ya'ni uni bazani to'ldirish uchun ishlatib bo'lmasligi
    kerak."""
    series, number = _normalize(body.passport_series, body.passport_number)

    existing = await _find_by_passport(db, series, number)
    if existing is not None:
        # Yozuv allaqachon bor — yangisini yaratmaymiz, borini qaytaramiz.
        # Aks holda bitta odam uchun ikkita yozuv paydo bo'lardi va
        # davomat ikkiga bo'linib ketardi.
        return EnrollmentLookupOut(
            record_id=str(existing.id),
            full_name=existing.full_name,
            type_label="Talaba" if existing.type == "talaba" else "Xodim",
            group_or_position=existing.group_or_position,
            already_enrolled=existing.biometrics_status == "tasdiqlangan",
        )

    faculty_id = None
    if body.faculty_id:
        faculty = await db.get(Faculty, body.faculty_id)
        if faculty is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Bunday fakultet topilmadi")
        faculty_id = faculty.id

    record = StudentStaff(
        full_name=body.full_name.strip(),
        type=body.type,
        group_or_position=body.group_or_position.strip(),
        faculty_id=faculty_id,
        passport_series=series,
        passport_number=number,
        biometrics_status="yoq",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    logger.info("self-service registration created", extra={"record_id": str(record.id)})

    return EnrollmentLookupOut(
        record_id=str(record.id),
        full_name=record.full_name,
        type_label="Talaba" if record.type == "talaba" else "Xodim",
        group_or_position=record.group_or_position,
        already_enrolled=False,
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

    # Blocking boto3 call kept off the event loop, and the photo this
    # replaces (a re-enrollment) removed afterwards so it doesn't sit in
    # object storage unreferenced — see app/storage.py's
    # delete_files_quietly for why both matter.
    previous_key = record.biometric_photo_key
    _file_id, key = await asyncio.to_thread(upload_file, frames[0], "face.jpg", "image/jpeg", "biometrics")
    record.biometric_photo_key = key
    record.biometric_embedding = json.dumps(embedding)
    record.biometrics_status = "tasdiqlangan"

    await db.commit()
    if previous_key and previous_key != key:
        await delete_files_quietly([previous_key])
    logger.info("self-service biometric enrollment completed", extra={"record_id": record_id})
    invalidate_candidate_matrix_cache()
    return EnrollmentSubmitOut(full_name=record.full_name, biometrics_status=record.biometrics_status)
