"""Bulk CSV import for lesson sessions — POST /api/lesson-sessions/import."""

import csv
import io
import logging
from datetime import date as date_type, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Camera, Faculty, LessonSession, StudentStaff
from app.schemas.lesson_session import LessonSessionImportErrorOut, LessonSessionImportResultOut
from app.timezone import INSTITUTE_TZ

logger = logging.getLogger("app.lesson_import")

_REQUIRED = {"date", "group", "faculty", "subject"}


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

    faculty_cache: dict[str, bool] = {}
    imported = 0
    skipped = 0
    errors: list[LessonSessionImportErrorOut] = []

    for row_num, row in enumerate(reader, start=2):
        date_str = (row.get(field_map["date"]) or "").strip()
        group = (row.get(field_map["group"]) or "").strip()
        faculty_name = (row.get(field_map["faculty"]) or "").strip()
        subject = (row.get(field_map["subject"]) or "").strip()
        teacher_id = (row.get(field_map["teacher_id"]) or "").strip() or None if "teacher_id" in field_map else None
        camera_id = (row.get(field_map["camera_id"]) or "").strip() or None if "camera_id" in field_map else None
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

        if faculty_name not in faculty_cache:
            exists = (
                await db.execute(select(Faculty.id).where(Faculty.name == faculty_name))
            ).scalar_one_or_none()
            if exists is None:
                errors.append(
                    LessonSessionImportErrorOut(row=row_num, message=f"Fakultet topilmadi: {faculty_name}")
                )
                continue
            faculty_cache[faculty_name] = True

        teacher_name: str | None = None
        teacher_uuid = None
        if teacher_id:
            teacher = await db.get(StudentStaff, teacher_id)
            if teacher is None or teacher.type != "xodim":
                errors.append(LessonSessionImportErrorOut(row=row_num, message="O'qituvchi topilmadi"))
                continue
            teacher_name = teacher.full_name
            teacher_uuid = teacher.id

        camera_uuid = None
        if camera_id:
            camera = await db.get(Camera, camera_id)
            if camera is None:
                errors.append(LessonSessionImportErrorOut(row=row_num, message="Kamera topilmadi"))
                continue
            camera_uuid = camera.id

        dup = (
            await db.execute(
                select(LessonSession.id)
                .where(LessonSession.date == lesson_date)
                .where(LessonSession.group_name == group)
                .where(LessonSession.subject == subject)
            )
        ).scalar_one_or_none()
        if dup is not None:
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
        imported += 1

    return LessonSessionImportResultOut(imported=imported, skipped=skipped, errors=errors)
