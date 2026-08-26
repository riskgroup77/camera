"""Bulk CSV import for students/staff — POST /api/students-staff/import.

Expected UTF-8 CSV header (case-insensitive):
  full_name,type,faculty,group_or_position

`type` must be talaba or xodim. Existing rows (same full_name + type) are
skipped, not updated — biometrics are never touched by import.
"""

import csv
import io
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Faculty, StudentStaff
from app.schemas.student_staff_import import StudentStaffImportErrorOut, StudentStaffImportResultOut

logger = logging.getLogger("app.student_import")

_REQUIRED_COLUMNS = {"full_name", "type", "faculty", "group_or_position"}


def _normalize_header(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


async def import_students_staff_csv(db: AsyncSession, raw: bytes) -> StudentStaffImportResultOut:
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return StudentStaffImportResultOut(imported=0, skipped=0, errors=[StudentStaffImportErrorOut(row=0, message="CSV bo'sh")])

    field_map = {_normalize_header(h): h for h in reader.fieldnames}
    missing = _REQUIRED_COLUMNS - set(field_map)
    if missing:
        return StudentStaffImportResultOut(
            imported=0,
            skipped=0,
            errors=[
                StudentStaffImportErrorOut(
                    row=0,
                    message=f"Yetishmayotgan ustunlar: {', '.join(sorted(missing))}",
                )
            ],
        )

    faculty_cache: dict[str, Faculty] = {}
    imported = 0
    skipped = 0
    errors: list[StudentStaffImportErrorOut] = []

    for row_num, row in enumerate(reader, start=2):
        full_name = (row.get(field_map["full_name"]) or "").strip()
        person_type = (row.get(field_map["type"]) or "").strip().lower()
        faculty_name = (row.get(field_map["faculty"]) or "").strip()
        group_or_position = (row.get(field_map["group_or_position"]) or "").strip()

        if len(full_name) < 5:
            errors.append(StudentStaffImportErrorOut(row=row_num, message="full_name kamida 5 belgi"))
            continue
        if person_type not in ("talaba", "xodim"):
            errors.append(StudentStaffImportErrorOut(row=row_num, message="type talaba yoki xodim bo'lishi kerak"))
            continue
        if not faculty_name:
            errors.append(StudentStaffImportErrorOut(row=row_num, message="faculty bo'sh"))
            continue
        if not group_or_position:
            errors.append(StudentStaffImportErrorOut(row=row_num, message="group_or_position bo'sh"))
            continue

        if faculty_name not in faculty_cache:
            result = await db.execute(select(Faculty).where(Faculty.name == faculty_name))
            faculty = result.scalar_one_or_none()
            if faculty is None:
                errors.append(StudentStaffImportErrorOut(row=row_num, message=f"Fakultet topilmadi: {faculty_name}"))
                continue
            faculty_cache[faculty_name] = faculty

        existing = (
            await db.execute(
                select(StudentStaff.id)
                .where(StudentStaff.full_name == full_name)
                .where(StudentStaff.type == person_type)
            )
        ).scalar_one_or_none()
        if existing is not None:
            skipped += 1
            continue

        db.add(
            StudentStaff(
                full_name=full_name,
                type=person_type,
                faculty_id=faculty_cache[faculty_name].id,
                group_or_position=group_or_position,
                biometrics_status="yoq",
            )
        )
        imported += 1

    return StudentStaffImportResultOut(imported=imported, skipped=skipped, errors=errors)
