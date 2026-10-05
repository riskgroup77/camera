"""Yuz tekshiruvi navbati va o'lchangan aniqlik — /api/tekshiruv.

Mantiq app/services/face_review.py da; bu yerda HTTP, huquq, audit va
aniqlik ko'rsatkichlari (faqat bazadagi haqiqiy qarorlardan — taxmin emas).
"""

import uuid
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.models import AttendanceRecord, Camera, Event, FaceReviewItem, StudentStaff
from app.schemas.base import CamelModel
from app.services import face_review as svc
from app.services.access_scope import allowed_camera_ids, camera_column_filter
from app.services.event_status import CONFIRMED_STATUSES, OPEN_STATUSES, REJECTED_STATUSES
from app.timezone import local_now
from app.timezone import business_today

router = APIRouter(prefix="/api/tekshiruv", tags=["tekshiruv"])

ReviewDep = Annotated[CurrentUser, Depends(require_permission("reviewEvents"))]


class ReviewItemOut(CamelModel):
    id: str
    day: str
    camera_id: str | None
    camera_name: str | None
    person_id: str
    person_name: str
    person_type: str
    group: str
    photo_url: str | None
    crop_url: str | None
    similarity: float
    second_similarity: float | None
    hits: int
    face_px: int
    first_seen_at: str
    last_seen_at: str
    status: str


class ReviewListOut(CamelModel):
    items: list[ReviewItemOut]
    pending: int
    day: str


class ResolveOut(CamelModel):
    id: str
    status: str
    message: str
    gallery_added: bool = False
    attendance_status: str | None = None


class ModuleAccuracy(CamelModel):
    code: int
    name: str
    confirmed: int
    rejected: int
    pending: int
    precision: float | None


class QueueAccuracy(CamelModel):
    confirmed: int
    rejected: int
    pending: int
    confirm_rate: float | None


class Coverage(CamelModel):
    enrolled: int
    total: int
    ratio: float | None


class AccuracyOut(CamelModel):
    days: int
    modules: list[ModuleAccuracy]
    queue: QueueAccuracy
    students: Coverage
    staff: Coverage
    recognized_today: int
    enrolled_today_ratio: float | None


def _url(key: str | None) -> str | None:
    if not key:
        return None
    from app.storage import presigned_url

    try:
        return presigned_url(key)
    except Exception:
        return None


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _parse_day(value: str | None) -> date_type:
    if not value:
        return business_today()
    try:
        return date_type.fromisoformat(value)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Sana YYYY-MM-DD ko'rinishida bo'lishi kerak")


def _already_present():
    """Kutilayotgan qator odami shu kuni boshqa yo'l bilan (qat'iy moslik,
    turniket, qo'lda) davomatga tushgan — navbatda ko'rsatishning keragi yo'q."""
    return exists().where(
        and_(
            AttendanceRecord.student_staff_id == FaceReviewItem.person_id,
            AttendanceRecord.date == FaceReviewItem.day,
            AttendanceRecord.status != "kelmadi",
        )
    )


@router.get("", response_model=ReviewListOut)
async def list_items(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
    sana: Annotated[str | None, Query()] = None,
    holat: Annotated[str, Query()] = svc.PENDING,
    limit: Annotated[int, Query(ge=1, le=300)] = 100,
) -> ReviewListOut:
    """Bir kunlik navbat; eng o'xshashi birinchi — operator tez qaror qiladi."""
    day = _parse_day(sana)
    if holat not in (*svc.STATUSES, "hammasi"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Noma'lum holat")
    query = (
        select(FaceReviewItem, Camera.name, StudentStaff)
        .join(StudentStaff, StudentStaff.id == FaceReviewItem.person_id)
        .outerjoin(Camera, Camera.id == FaceReviewItem.camera_id)
        .where(FaceReviewItem.day == day)
        .where(camera_column_filter(current_user, FaceReviewItem.camera_id))
    )
    if holat != "hammasi":
        query = query.where(FaceReviewItem.status == holat)
    if holat == svc.PENDING:
        query = query.where(~_already_present())
    rows = (
        await db.execute(
            query.order_by(FaceReviewItem.similarity.desc(), FaceReviewItem.last_seen_at.desc()).limit(limit)
        )
    ).all()
    pending = int(
        (
            await db.execute(
                select(func.count())
                .select_from(FaceReviewItem)
                .where(FaceReviewItem.day == day, FaceReviewItem.status == svc.PENDING, ~_already_present())
                .where(camera_column_filter(current_user, FaceReviewItem.camera_id))
            )
        ).scalar_one()
    )
    items = [
        ReviewItemOut(
            id=str(row.id),
            day=row.day.isoformat(),
            camera_id=str(row.camera_id) if row.camera_id else None,
            camera_name=camera_name,
            person_id=str(person.id),
            person_name=person.full_name,
            person_type=person.type,
            group=person.group_or_position,
            photo_url=_url(person.biometric_photo_key),
            crop_url=_url(row.crop_key),
            similarity=round(row.similarity, 4),
            second_similarity=round(row.second_similarity, 4) if row.second_similarity is not None else None,
            hits=row.hits,
            face_px=row.face_px,
            first_seen_at=row.first_seen_at.isoformat(),
            last_seen_at=row.last_seen_at.isoformat(),
            status=row.status,
        )
        for row, camera_name, person in rows
    ]
    return ReviewListOut(items=items, pending=pending, day=day.isoformat())


@router.get("/aniqlik", response_model=AccuracyOut)
async def accuracy(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
    kun: Annotated[int, Query(ge=1, le=365)] = 30,
) -> AccuracyOut:
    """O'lchangan aniqlik: operator qarorlaridan (sinov rejimidagi
    hodisalar kirmaydi) va bazadagi qamrovdan. Hammasi bir nechta
    guruhlangan so'rov — jadval kattalashsa ham arzon."""
    since = datetime.now(timezone.utc) - timedelta(days=kun)
    today = business_today()

    event_rows = (
        await db.execute(
            select(Event.module_code, func.max(Event.module_name), Event.status, func.count())
            .where(Event.occurred_at >= since, Event.is_trial.is_(False))
            .group_by(Event.module_code, Event.status)
        )
    ).all()
    per_module: dict[int, dict] = {}
    for code, name, event_status, count in event_rows:
        entry = per_module.setdefault(code, {"name": name, "confirmed": 0, "rejected": 0, "pending": 0})
        if event_status in CONFIRMED_STATUSES:
            entry["confirmed"] += int(count)
        elif event_status in REJECTED_STATUSES:
            entry["rejected"] += int(count)
        elif event_status in OPEN_STATUSES:
            entry["pending"] += int(count)
    modules = [
        ModuleAccuracy(
            code=code,
            name=entry["name"],
            confirmed=entry["confirmed"],
            rejected=entry["rejected"],
            pending=entry["pending"],
            precision=_ratio(entry["confirmed"], entry["confirmed"] + entry["rejected"]),
        )
        for code, entry in sorted(per_module.items())
    ]

    queue_counts = dict(
        (
            await db.execute(
                select(FaceReviewItem.status, func.count())
                .where(FaceReviewItem.day >= today - timedelta(days=kun))
                .group_by(FaceReviewItem.status)
            )
        ).all()
    )
    q_conf = int(queue_counts.get(svc.CONFIRMED, 0))
    q_rej = int(queue_counts.get(svc.REJECTED, 0))

    coverage_rows = (
        await db.execute(
            select(
                StudentStaff.type,
                func.count(),
                func.count().filter(StudentStaff.biometric_embedding.is_not(None)),
            )
            .where(StudentStaff.active.is_(True))
            .group_by(StudentStaff.type)
        )
    ).all()
    coverage = {person_type: (int(total), int(enrolled)) for person_type, total, enrolled in coverage_rows}
    students_total, students_enrolled = coverage.get("talaba", (0, 0))
    staff_total, staff_enrolled = coverage.get("xodim", (0, 0))

    recognized_today = int(
        (
            await db.execute(
                select(func.count(func.distinct(AttendanceRecord.student_staff_id)))
                .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
                .where(
                    AttendanceRecord.date == today,
                    AttendanceRecord.source == "kamera",
                    AttendanceRecord.status != "kelmadi",
                    StudentStaff.active.is_(True),
                    StudentStaff.biometric_embedding.is_not(None),
                )
            )
        ).scalar_one()
    )

    return AccuracyOut(
        days=kun,
        modules=modules,
        queue=QueueAccuracy(
            confirmed=q_conf,
            rejected=q_rej,
            pending=int(queue_counts.get(svc.PENDING, 0)),
            confirm_rate=_ratio(q_conf, q_conf + q_rej),
        ),
        students=Coverage(enrolled=students_enrolled, total=students_total, ratio=_ratio(students_enrolled, students_total)),
        staff=Coverage(enrolled=staff_enrolled, total=staff_total, ratio=_ratio(staff_enrolled, staff_total)),
        recognized_today=recognized_today,
        enrolled_today_ratio=_ratio(recognized_today, students_enrolled + staff_enrolled),
    )


async def _load(db: AsyncSession, item_id: str, user: CurrentUser) -> FaceReviewItem:
    try:
        key = uuid.UUID(item_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")
    row = await db.get(FaceReviewItem, key)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")
    allowed = await allowed_camera_ids(db, user)
    if allowed is not None and row.camera_id not in allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")
    return row


@router.post("/{item_id}/tasdiqlash", response_model=ResolveOut)
async def confirm_item(
    item_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
) -> ResolveOut:
    """"Ha, u": galereyaga namuna va davomat (birinchi ko'ringan vaqti bilan —
    kelish qoidalari odatdagidek: kechikish, oldinroq kelish tuzatishi)."""
    from app.jobs.attendance_ai import upsert_attendance_from_recognition
    from app.services.presence import record_visit

    row = await _load(db, item_id, current_user)
    try:
        added = await svc.confirm(db, row, current_user.id)
    except svc.ReviewError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error))
    person = await db.get(StudentStaff, row.person_id)
    if person is None or not person.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu odam faol emas — davomat yozilmaydi")
    camera = await db.get(Camera, row.camera_id) if row.camera_id else None
    await log_action(
        db,
        request,
        current_user.id,
        f"Yuz tekshiruvi: {person.full_name} tasdiqlandi ({row.similarity:.2f})",
        "Talabalar",
    )
    if camera is not None:
        await record_visit(db, row.person_id, camera.id, row.first_seen_at, row.similarity)
    # upsert o'zi commit qiladi — holat, galereya va audit bir tranzaksiyada.
    # Ish vaqtidan tashqari hodisasi ko'tarilmaydi: bu jonli kuzatuv emas,
    # soatlar keyin qilingan tasdiq.
    record = await upsert_attendance_from_recognition(
        db, str(row.person_id), row.first_seen_at, camera, off_hours_module_active=False
    )
    return ResolveOut(
        id=str(row.id),
        status=row.status,
        message=f"{person.full_name}: davomat yozildi" + (", namuna qo'shildi" if added else ""),
        gallery_added=added,
        attendance_status=record.status if record is not None else None,
    )


@router.post("/{item_id}/rad", response_model=ResolveOut)
async def reject_item(
    item_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
) -> ResolveOut:
    row = await _load(db, item_id, current_user)
    try:
        svc.reject(row, current_user.id)
    except svc.ReviewError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error))
    person = await db.get(StudentStaff, row.person_id)
    await log_action(
        db,
        request,
        current_user.id,
        f"Yuz tekshiruvi: {person.full_name if person else row.person_id} rad etildi ({row.similarity:.2f})",
        "Talabalar",
    )
    await db.commit()
    return ResolveOut(id=str(row.id), status=row.status, message="Rad etildi")
