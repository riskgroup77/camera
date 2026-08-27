"""Bulk CSV import for lesson sessions — POST /api/lesson-sessions/import."""

import csv
import io
import logging
import uuid
from datetime import date as date_type, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Camera, Faculty, LessonSession, StudentStaff
from app.schemas.lesson_session import LessonSessionImportErrorOut, LessonSessionImportResultOut
from app.timezone import INSTITUTE_TZ

logger = logging.getLogger("app.lesson_import")

_REQUIRED = {"date", "group", "faculty", "subject"}
LessonKey = tuple[date_type, str, str]


def parse_scheduled_start_time(value: str | None) -> datetime | None:
    """ISO 8601 schedule time — naive values use institute-local TZ."""
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=INSTITUTE_TZ)
    return parsed


def _normalize_header(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


async def _load_faculty_names(db: AsyncSession) -> set[str]:
    result = await db.execute(select(Faculty.name))
    return set(result.scalars().all())


async def _load_existing_lesson_keys(db: AsyncSession) -> set[LessonKey]:
    result = await db.execute(select(LessonSession.date, LessonSession.group_name, LessonSession.subject))
    return {(lesson_date, group_name, subject) for lesson_date, group_name, subject in result.all()}


async def _load_teachers_by_id(db: AsyncSession, teacher_ids: set[uuid.UUID]) -> dict[uuid.UUID, StudentStaff]:
    if not teacher_ids:
        return {}
    result = await db.execute(select(StudentStaff).where(StudentStaff.id.in_(teacher_ids)))
    return {teacher.id: teacher for teacher in result.scalars().all()}


async def _load_cameras_by_id(db: AsyncSession, camera_ids: set[uuid.UUID]) -> dict[uuid.UUID, Camera]:
    if not camera_ids:
        return {}
    result = await db.execute(select(Camera).where(Camera.id.in_(camera_ids)))
    return {camera.id: camera for camera in result.scalars().all()}


def _parse_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def import_lesson_sessions_csv(db: AsyncSession, raw: bytes) -> LessonSessionImportResultOut:
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return LessonSessionImportResultOut(
            imported=0, skipped=0, errors=[LessonSessionImportErrorOut(row=0, message="CSV bo'sh")]
        )

    field_map = {_normalize_header(h): h for h in reader.fieldnames}
    missing = _REQUIRED - set(field_map)
    if missing:
        return LessonSessionImportResultOut(
            imported=0,
            skipped=0,
            errors=[
                LessonSessionImportErrorOut(
                    row=0, message=f"Yetishmayotgan ustunlar: {', '.join(sorted(missing))}"
                )
            ],
        )

    rows = list(reader)
    faculty_names = await _load_faculty_names(db)
    existing_keys = await _load_existing_lesson_keys(db)
    pending_keys: set[LessonKey] = set()

    teacher_ids: set[uuid.UUID] = set()
    camera_ids: set[uuid.UUID] = set()
    if "teacher_id" in field_map:
        for row in rows:
            parsed = _parse_uuid((row.get(field_map["teacher_id"]) or "").strip() or None)
            if parsed is not None:
                teacher_ids.add(parsed)
    if "camera_id" in field_map:
        for row in rows:
            parsed = _parse_uuid((row.get(field_map["camera_id"]) or "").strip() or None)
            if parsed is not None:
                camera_ids.add(parsed)

    teachers = await _load_teachers_by_id(db, teacher_ids)
    cameras = await _load_cameras_by_id(db, camera_ids)

    imported = 0
    skipped = 0
    errors: list[LessonSessionImportErrorOut] = []

    for row_num, row in enumerate(rows, start=2):
        date_str = (row.get(field_map["date"]) or "").strip()
        group = (row.get(field_map["group"]) or "").strip()
        faculty_name = (row.get(field_map["faculty"]) or "").strip()
        subject = (row.get(field_map["subject"]) or "").strip()
        teacher_id_raw = (row.get(field_map["teacher_id"]) or "").strip() if "teacher_id" in field_map else ""
        camera_id_raw = (row.get(field_map["camera_id"]) or "").strip() if "camera_id" in field_map else ""
        scheduled_raw = (
            (row.get(field_map["scheduled_start_time"]) or "").strip() or None
            if "scheduled_start_time" in field_map
            else None
        )

        if not date_str or not group or not faculty_name or not subject:
            errors.append(LessonSessionImportErrorOut(row=row_num, message="Majburiy maydonlar to'ldirilmagan"))
            continue

        try:
            lesson_date = date_type.fromisoformat(date_str)
        except ValueError:
            errors.append(LessonSessionImportErrorOut(row=row_num, message=f"Noto'g'ri sana: {date_str}"))
            continue

        if faculty_name not in faculty_names:
            errors.append(
                LessonSessionImportErrorOut(row=row_num, message=f"Fakultet topilmadi: {faculty_name}")
            )
            continue

        teacher_name: str | None = None
        teacher_uuid = None
        if teacher_id_raw:
            teacher_uuid = _parse_uuid(teacher_id_raw)
            if teacher_uuid is None:
                errors.append(LessonSessionImportErrorOut(row=row_num, message="O'qituvchi ID noto'g'ri"))
                continue
            teacher = teachers.get(teacher_uuid)
            if teacher is None or teacher.type != "xodim":
                errors.append(LessonSessionImportErrorOut(row=row_num, message="O'qituvchi topilmadi"))
                continue
            teacher_name = teacher.full_name

        camera_uuid = None
        if camera_id_raw:
            camera_uuid = _parse_uuid(camera_id_raw)
            if camera_uuid is None:
                errors.append(LessonSessionImportErrorOut(row=row_num, message="Kamera ID noto'g'ri"))
                continue
            if cameras.get(camera_uuid) is None:
                errors.append(LessonSessionImportErrorOut(row=row_num, message="Kamera topilmadi"))
                continue

        lesson_key: LessonKey = (lesson_date, group, subject)
        if lesson_key in existing_keys or lesson_key in pending_keys:
            skipped += 1
            continue

        scheduled_start = parse_scheduled_start_time(scheduled_raw) if scheduled_raw else None

        db.add(
            LessonSession(
                date=lesson_date,
                group_name=group,
                faculty=faculty_name,
                subject=subject,
                teacher=teacher_name or "—",
                teacher_id=teacher_uuid,
                camera_id=camera_uuid,
                scheduled_start_time=scheduled_start,
                attention_score=50,
                sleep_incidents=0,
                teacher_activity_score=50,
                teacher_on_time=True,
            )
        )
        pending_keys.add(lesson_key)
        imported += 1

    return LessonSessionImportResultOut(imported=imported, skipped=skipped, errors=errors)
