import asyncio
import csv
import io
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.models import Faculty, StudentStaff
from app.pagination import Page, PageParams, build_page, paginate
from app.schemas.student_staff import (
    BiometricsCoverageOut,
    BiometricsFacultyRowOut,
    StudentStaffCreateIn,
    StudentStaffOut,
    StudentStaffUpdateIn,
)
from app.schemas.student_staff_import import StudentStaffImportResultOut
from app.services.face_matching import invalidate_candidate_matrix_cache
from app.services.face_recognition import NoFaceDetectedError, extract_embedding
from app.services.student_import import import_students_staff_csv
from app.storage import delete_files_quietly, presigned_url, upload_file
from app.timezone import local_now
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


# "Fakultetsiz" — bu qiymat emas, qiymatning YO'QLIGI. Rektorat, texnik
# va xo'jalik bo'limlari xodimlarining fakulteti bo'lmaydi, lekin ular
# ham ro'yxatga kiradi va qamrov hisobiga qo'shiladi. Filtrda ularni
# tanlash uchun alohida kalit kerak, chunki bo'sh satr "filtr yo'q"
# degani.
NO_FACULTY_KEY = "__none__"
NO_FACULTY_LABEL = "Fakultetsiz"


def _filtered_query(
    type: str | None, faculty: str | None, search: str | None, biometrics: str | None
):
    """Ro'yxat va eksport AYNAN bir xil filtrdan foydalanadi.

    Alohida yozilsa, ikkalasi vaqt o'tib bir-biridan farq qila boshlardi
    va yuklab olingan fayl ekranda ko'rinayotgan ro'yxatga mos
    kelmasdi — bu hisobot uchun jiddiy nuqson."""
    stmt = (
        select(StudentStaff)
        .options(selectinload(StudentStaff.faculty))
        .order_by(StudentStaff.full_name)
    )
    if type:
        stmt = stmt.where(StudentStaff.type == type)
    if faculty == NO_FACULTY_KEY:
        stmt = stmt.where(StudentStaff.faculty_id.is_(None))
    elif faculty:
        stmt = stmt.join(Faculty).where(Faculty.name == faculty)
    if search:
        # JSHSHIR bo'yicha ham qidiriladi: kadrlar bo'limi odamni
        # ko'pincha aynan raqami bilan izlaydi.
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(StudentStaff.full_name.ilike(term), StudentStaff.pinfl.ilike(term))
        )
    if biometrics:
        stmt = stmt.where(StudentStaff.biometrics_status == biometrics)
    return stmt


@router.get("", response_model=Page[StudentStaffOut])
async def list_students_staff(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
    page_params: Annotated[PageParams, Depends()],
    type: Annotated[str | None, Query()] = None,
    faculty: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    biometrics: Annotated[str | None, Query(alias="biometricsStatus")] = None,
) -> Page[StudentStaffOut]:
    stmt = _filtered_query(type, faculty, search, biometrics)

    records, total = await paginate(db, stmt, page_params)
    items = [_to_out(r, r.faculty.name if r.faculty else "") for r in records]
    return build_page(items, total, page_params)


@router.get("/biometrics-coverage", response_model=BiometricsCoverageOut)
async def biometrics_coverage(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
    type: Annotated[str | None, Query()] = None,
) -> BiometricsCoverageOut:
    """Yuzni kim tasdiqlagani va kim tasdiqlamagani — fakultetlar kesimida.

    Bu savol tizim ishga tushgandan keyin eng ko'p beriladigan savol:
    ro'yxatdagi 688 xodimdan nechtasi haqiqatan yuzini yuklagan. Uni
    ro'yxatni varaqlab sanab bo'lmaydi, shuning uchun alohida
    hisoblanadi."""
    stmt = select(
        Faculty.name,
        StudentStaff.biometrics_status,
        func.count(StudentStaff.id),
    ).select_from(StudentStaff).outerjoin(Faculty, StudentStaff.faculty_id == Faculty.id)
    if type:
        stmt = stmt.where(StudentStaff.type == type)
    stmt = stmt.group_by(Faculty.name, StudentStaff.biometrics_status)

    buckets: dict[str, dict[str, int]] = {}
    for faculty_name, bio_status, count in (await db.execute(stmt)).all():
        key = faculty_name or NO_FACULTY_LABEL
        buckets.setdefault(key, {}).update({bio_status: count})

    rows: list[BiometricsFacultyRowOut] = []
    totals = {"tasdiqlangan": 0, "kutilmoqda": 0, "yoq": 0}
    for name in sorted(buckets, key=lambda n: (n == NO_FACULTY_LABEL, n)):
        counts = buckets[name]
        confirmed = counts.get("tasdiqlangan", 0)
        pending = counts.get("kutilmoqda", 0)
        missing = counts.get("yoq", 0)
        total = confirmed + pending + missing
        for k, v in (("tasdiqlangan", confirmed), ("kutilmoqda", pending), ("yoq", missing)):
            totals[k] += v
        rows.append(
            BiometricsFacultyRowOut(
                faculty=name,
                total=total,
                confirmed=confirmed,
                pending=pending,
                missing=missing,
                percent=round(confirmed * 100 / total, 1) if total else None,
            )
        )

    grand = sum(totals.values())
    return BiometricsCoverageOut(
        total=grand,
        confirmed=totals["tasdiqlangan"],
        pending=totals["kutilmoqda"],
        missing=totals["yoq"],
        percent=round(totals["tasdiqlangan"] * 100 / grand, 1) if grand else None,
        by_faculty=rows,
    )


@router.get("/export")
async def export_students_staff(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
    type: Annotated[str | None, Query()] = None,
    faculty: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    biometrics: Annotated[str | None, Query(alias="biometricsStatus")] = None,
) -> StreamingResponse:
    """Ro'yxatni ismlari bilan CSV qilib yuklab olish.

    Ekrandagi filtr AYNAN saqlanadi: "Pediatriya fakulteti, yuzi
    tasdiqlanmaganlar" tanlangan bo'lsa, faylga ham aynan o'shalar
    tushadi. Bu hisobot uchun printsipial — yuklab olingan fayl
    ekranda ko'rilgan narsaning nusxasi bo'lishi kerak.

    Excel uchun BOM qo'shiladi: usiz o'zbek harflari (o', g', sh)
    Excel da buzilib ochiladi va fayl yaroqsiz bo'lib qoladi."""
    records = (await db.execute(_filtered_query(type, faculty, search, biometrics))).scalars().all()

    status_labels = {
        "tasdiqlangan": "Tasdiqlangan",
        "kutilmoqda": "Kutilmoqda",
        "yoq": "Tasdiqlanmagan",
    }

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["№", "F.I.SH.", "JSHSHIR", "Turi", "Fakultet", "Kafedra / Bo'lim", "Yuz holati"])
    for i, r in enumerate(records, 1):
        writer.writerow([
            i,
            r.full_name,
            r.pinfl or "",
            "Talaba" if r.type == "talaba" else "Xodim",
            r.faculty.name if r.faculty else NO_FACULTY_LABEL,
            r.group_or_position,
            status_labels.get(r.biometrics_status, r.biometrics_status),
        ])

    payload = "\ufeff" + buffer.getvalue()
    filename = f"xodimlar-{local_now().strftime('%Y-%m-%d')}.csv"
    return StreamingResponse(
        iter([payload.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
