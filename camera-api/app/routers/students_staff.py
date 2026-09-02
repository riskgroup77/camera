import asyncio
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.models import Faculty, StudentStaff
from app.pagination import Page, PageParams, build_page, paginate
from app.schemas.student_staff import StudentStaffCreateIn, StudentStaffOut, StudentStaffUpdateIn
from app.schemas.student_staff_import import StudentStaffImportResultOut
from app.services.face_matching import invalidate_candidate_matrix_cache
from app.services.face_recognition import NoFaceDetectedError, extract_embedding
from app.services.student_import import import_students_staff_csv
from app.storage import delete_files_quietly, presigned_url, upload_file
from app.utils import compute_initials

router = APIRouter(prefix="/api/students-staff", tags=["students-staff"])

logger = logging.getLogger("app.students_staff")

MAX_PHOTO_SIZE_BYTES = 10 * 1024 * 1024


async def _resolve_faculty(db: AsyncSession, faculty_name: str) -> Faculty:
    result = await db.execute(select(Faculty).where(Faculty.name == faculty_name))
    faculty = result.scalar_one_or_none()
    if faculty is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"'{faculty_name}' nomli fakultet topilmadi")
    return faculty


def _to_out(record: StudentStaff, faculty_name: str) -> StudentStaffOut:
    return StudentStaffOut(
        id=str(record.id),
        full_name=record.full_name,
        type=record.type,
        faculty=faculty_name,
        group_or_position=record.group_or_position,
        biometrics_status=record.biometrics_status,
        initials=compute_initials(record.full_name),
        biometric_photo_url=presigned_url(record.biometric_photo_key) if record.biometric_photo_key else None,
    )


@router.get("", response_model=Page[StudentStaffOut])
async def list_students_staff(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
    page_params: Annotated[PageParams, Depends()],
    type: Annotated[str | None, Query()] = None,
    faculty: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
) -> Page[StudentStaffOut]:
    stmt = select(StudentStaff).options(selectinload(StudentStaff.faculty)).order_by(StudentStaff.created_at.desc())
    if type:
        stmt = stmt.where(StudentStaff.type == type)
    if faculty:
        stmt = stmt.join(Faculty).where(Faculty.name == faculty)
    if search:
        stmt = stmt.where(StudentStaff.full_name.ilike(f"%{search}%"))

    records, total = await paginate(db, stmt, page_params)
    items = [_to_out(r, r.faculty.name if r.faculty else "") for r in records]
    return build_page(items, total, page_params)


@router.post("", response_model=StudentStaffOut, status_code=status.HTTP_201_CREATED)
async def create_student_staff(
    body: StudentStaffCreateIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
) -> StudentStaffOut:
    faculty = await _resolve_faculty(db, body.faculty)
    record = StudentStaff(
        full_name=body.full_name,
        type=body.type,
        faculty_id=faculty.id,
        group_or_position=body.group_or_position,
        biometrics_status=body.biometrics_status,
    )
    db.add(record)
    label = "Talaba" if body.type == "talaba" else "Xodim"
    await log_action(db, request, current_user.id, f"{label} qo'shdi: {body.full_name}", "Talabalar")
    await db.commit()
    await db.refresh(record)
    return _to_out(record, faculty.name)


@router.post("/import", response_model=StudentStaffImportResultOut)
async def import_students_staff(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
    file: Annotated[UploadFile, File(description="UTF-8 CSV: full_name,type,faculty,group_or_position")],
) -> StudentStaffImportResultOut:
    """Bulk-import talaba/xodim rows from CSV. Biometrics are NOT imported —
    each row starts with biometrics_status=yoq."""
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "CSV hajmi 5 MB dan oshmasligi kerak")
    result = await import_students_staff_csv(db, raw)
    if result.imported:
        invalidate_candidate_matrix_cache()
    await log_action(
        db,
        request,
        current_user.id,
        f"CSV import: {result.imported} qo'shildi, {result.skipped} o'tkazib yuborildi, {len(result.errors)} xato",
        "Talabalar",
    )
    await db.commit()
    if result.imported:
        logger.info("CSV import complete", extra={"imported": result.imported, "skipped": result.skipped})
    return result


@router.patch("/{record_id}", response_model=StudentStaffOut)
async def update_student_staff(
    record_id: str,
    body: StudentStaffUpdateIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
) -> StudentStaffOut:
    result = await db.execute(select(StudentStaff).where(StudentStaff.id == record_id))
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")

    faculty = await _resolve_faculty(db, body.faculty)
    record.full_name = body.full_name
    record.type = body.type
    record.faculty_id = faculty.id
    record.group_or_position = body.group_or_position

    await log_action(db, request, current_user.id, f"Yozuvni tahrirladi: {body.full_name}", "Talabalar")
    await db.commit()
    await db.refresh(record)
    return _to_out(record, faculty.name)


@router.post("/{record_id}/biometrics", response_model=StudentStaffOut)
async def enroll_biometrics(
    record_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
    photo: Annotated[UploadFile, File(description="Kamerada suratga olingan jonli yuz — ro'yxatdan o'tkazish vizardining yakuniy bosqichi")],
) -> StudentStaffOut:
    """Persists what AddStudentStaffModal.tsx's face-match step used to
    throw away: the enrollment photo (to MinIO) and its ArcFace embedding
    (to the DB, JSON-encoded) — see biometric_photo_key/biometric_embedding
    on the model for why. A pure /api/face/compare call never touches this
    endpoint; this only runs once the wizard's match step has passed."""
    result = await db.execute(
        select(StudentStaff).options(selectinload(StudentStaff.faculty)).where(StudentStaff.id == record_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")

    data = await photo.read()
    if len(data) > MAX_PHOTO_SIZE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Fayl hajmi 10 MB dan oshmasligi kerak")

    try:
        embedding = await extract_embedding(data)
    except NoFaceDetectedError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    # upload_file is a blocking boto3 network call — off the event loop,
    # same as app/services/event_bus.py's snapshot upload. On a busy API
    # process a synchronous S3 round trip here stalls every other request.
    previous_key = record.biometric_photo_key
    _file_id, key = await asyncio.to_thread(
        upload_file, data, photo.filename or "face.jpg", photo.content_type or "image/jpeg", "biometrics"
    )
    record.biometric_photo_key = key
    record.biometric_embedding = json.dumps(embedding)
    record.biometrics_status = "tasdiqlangan"

    await log_action(db, request, current_user.id, f"Biometrik ma'lumot saqlandi: {record.full_name}", "Talabalar")
    await db.commit()
    await db.refresh(record)
    # Re-enrollment replaces the key on the row; without this the previous
    # photo stays in object storage with nothing referencing it, forever.
    if previous_key and previous_key != key:
        await delete_files_quietly([previous_key])
    invalidate_candidate_matrix_cache()
    return _to_out(record, record.faculty.name if record.faculty else "")
