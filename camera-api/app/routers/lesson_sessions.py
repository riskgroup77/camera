"""Dars monitoring (TT 3-E bo'lim) endpoints.

Honest scope note: attention_score / sleep_incidents / teacher_activity_score
are meant to come from AI modules 19-22 (gaze estimation, eye-closure
detection, pose tracking) — none of which have a real model behind them
yet (see app/routers/ai_modules.py). This is the storage/reporting layer;
POST here is a manual/admin entry point until that pipeline exists.
"""

from datetime import date as date_type, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.models import Camera, LessonAttendance, LessonSession, StudentStaff
from app.pagination import Page, PageParams, build_page, paginate
from app.schemas.lesson_session import (
    LessonAttendanceOut,
    LessonSessionImportErrorOut,
    LessonAttendanceRowOut,
    LessonSessionCreateIn,
    LessonSessionImportResultOut,
    LessonSessionOut,
    LessonSessionScheduleIn,
)
from app.config import settings
from app.models import Faculty, StudentGroup
from app.services.lesson_import import (
    _column_map,
    _read_rows,
    import_lesson_sessions as import_lessons_file,
    parse_scheduled_start_time,
)
from app.services.lesson_weekly import (
    WEEKDAY_COLUMN_ALIASES,
    build_weekly_template,
    expand_weekly,
)

router = APIRouter(prefix="/api/lesson-sessions", tags=["lesson-sessions"])

# Dars jadvali va monitoring natijalarini o'qish hisobotlardan ham kerak;
# jadvalni kiritish, import qilish va o'chirish — faqat manageLessons bilan.
ReadDep = Annotated[CurrentUser, Depends(require_permission("manageLessons", "viewReports"))]
EditDep = Annotated[CurrentUser, Depends(require_permission("manageLessons"))]
# Bitta darsdagi davomat — guruh, kafedra va shaxs sahifalarida ham ochiladi
# (ular manageAttendance bilan), shuning uchun u ham yetarli.
AttendanceReadDep = Annotated[
    CurrentUser, Depends(require_permission("manageLessons", "viewReports", "manageAttendance"))
]


def _to_out(s: LessonSession) -> LessonSessionOut:
    return LessonSessionOut(
        id=str(s.id),
        date=s.date.isoformat(),
        group=s.group_name,
        faculty=s.faculty,
        teacher=s.teacher,
        subject=s.subject,
        attention_score=s.attention_score if s.attention_samples else None,
        sleep_incidents=s.sleep_incidents,
        teacher_activity_score=s.teacher_activity_score if s.activity_samples else None,
        teacher_on_time=s.teacher_on_time,
        teacher_id=str(s.teacher_id) if s.teacher_id else None,
        camera_id=str(s.camera_id) if s.camera_id else None,
        scheduled_start_time=s.scheduled_start_time.isoformat() if s.scheduled_start_time else None,
        scheduled_end_time=s.scheduled_end_time.isoformat() if s.scheduled_end_time else None,
        auditorium=s.auditorium,
        building=s.building,
        from_hemis=s.hemis_id is not None,
    )


async def _resolve_teacher(db: AsyncSession, teacher_id: str | None) -> StudentStaff | None:
    """Raises 404 if teacher_id is given but doesn't resolve to a real,
    staff-type person — a schedule pointing at a nonexistent/wrong-type
    person would silently never fire in
    app/jobs/teacher_punctuality_ai.py / app/jobs/lesson_quality_ai.py,
    with no visible error, which is worse than failing loudly here."""
    if teacher_id is None:
        return None
    teacher = await db.get(StudentStaff, teacher_id)
    if teacher is None or teacher.type != "xodim":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "O'qituvchi (xodim) topilmadi")
    return teacher


async def _resolve_camera(db: AsyncSession, camera_id: str | None) -> Camera | None:
    if camera_id is None:
        return None
    camera = await db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi")
    return camera


def _parse_scheduled_start_time(value: str | None) -> datetime | None:
    return parse_scheduled_start_time(value)


@router.get("", response_model=Page[LessonSessionOut])
async def list_lesson_sessions(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: ReadDep,
    page_params: Annotated[PageParams, Depends()],
    group: Annotated[str | None, Query()] = None,
    faculty: Annotated[str | None, Query()] = None,
) -> Page[LessonSessionOut]:
    # id — barqaror tartib: bir sanada yuzlab dars bor, faqat sana bo'yicha
    # sahifalashda qatorlar sahifalar orasida takrorlanar yoki tushib qolardi.
    stmt = select(LessonSession).order_by(
        LessonSession.date.desc(), LessonSession.scheduled_start_time.desc(), LessonSession.id.desc()
    )
    if group:
        stmt = stmt.where(LessonSession.group_name == group)
    if faculty:
        stmt = stmt.where(LessonSession.faculty == faculty)

    records, total = await paginate(db, stmt, page_params)
    items = [_to_out(s) for s in records]
    return build_page(items, total, page_params)


@router.post("", response_model=LessonSessionOut, status_code=201)
async def create_lesson_session(
    body: LessonSessionCreateIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: EditDep,
) -> LessonSessionOut:
    teacher = await _resolve_teacher(db, body.teacher_id)
    camera = await _resolve_camera(db, body.camera_id)
    if teacher is None and body.teacher is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "teacher yoki teacherId ko'rsatilishi shart")

    session = LessonSession(
        date=date_type.fromisoformat(body.date),
        group_name=body.group,
        faculty=body.faculty,
        teacher=teacher.full_name if teacher else body.teacher,
        subject=body.subject,
        attention_score=body.attention_score or 0,
        attention_samples=0 if body.attention_score is None else 1,
        sleep_incidents=body.sleep_incidents,
        teacher_activity_score=body.teacher_activity_score or 0,
        activity_samples=0 if body.teacher_activity_score is None else 1,
        teacher_on_time=body.teacher_on_time,
        teacher_id=teacher.id if teacher else None,
        camera_id=camera.id if camera else None,
        scheduled_start_time=_parse_scheduled_start_time(body.scheduled_start_time),
    )
    db.add(session)
    await log_action(
        db, request, current_user.id, f"Dars monitoring yozuvi qo'shdi: {body.group} / {body.subject}", "Ta'lim"
    )
    await db.commit()
    await db.refresh(session)
    return _to_out(session)


@router.patch("/{session_id}/schedule", response_model=LessonSessionOut)
async def schedule_lesson_session(
    session_id: str,
    body: LessonSessionScheduleIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: EditDep,
) -> LessonSessionOut:
    session = await db.get(LessonSession, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dars monitoring yozuvi topilmadi")

    teacher = await _resolve_teacher(db, body.teacher_id)
    camera = await _resolve_camera(db, body.camera_id)

    if teacher is not None:
        session.teacher_id = teacher.id
        session.teacher = teacher.full_name
    if camera is not None:
        session.camera_id = camera.id
    session.scheduled_start_time = _parse_scheduled_start_time(body.scheduled_start_time)

    await log_action(
        db, request, current_user.id,
        f"Dars jadvalini belgiladi: {session.group_name} / {session.subject}", "Ta'lim",
    )
    await db.commit()
    await db.refresh(session)
    return _to_out(session)


@router.post("/import", response_model=LessonSessionImportResultOut)
async def import_lesson_sessions(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: EditDep,
    file: Annotated[UploadFile, File(description="CSV yoki Excel: sana, guruh, fan, xona, o'qituvchi, boshlanish")],
    apply: Annotated[bool, Query()] = True,
) -> LessonSessionImportResultOut:
    """Dars jadvalini import qilish — app/services/lesson_import.py.

    `apply=false` — faqat oldindan ko'rish (qaysi xona/o'qituvchi
    topilmadi), hech narsa yozilmaydi."""
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Fayl hajmi 5 MB dan oshmasligi kerak")
    result = await import_lessons_file(db, raw, filename=file.filename or "", apply=apply)
    if apply and result.imported:
        await log_action(
            db,
            request,
            current_user.id,
            f"Dars jadvali CSV import: {result.imported} qo'shildi, {result.skipped} o'tkazib yuborildi",
            "Ta'lim",
        )
        await db.commit()
    return result



MAX_UPLOAD_BYTES = 5 * 1024 * 1024


async def _template_lists(db: AsyncSession) -> tuple[list[str], list[tuple[str, str]]]:
    """Namunaga qo'yiladigan ro'yxatlar: guruhlar va KAMERASI BOR xonalar."""
    groups = list((await db.execute(select(StudentGroup.name).order_by(StudentGroup.name))).scalars().all())
    rows = (
        await db.execute(
            select(Camera.room_code, Camera.name)
            .where(Camera.room_code.isnot(None))
            .where(Camera.room_code != "")
            .order_by(Camera.room_code, Camera.name)
        )
    ).all()
    seen: set[str] = set()
    rooms: list[tuple[str, str]] = []
    for code, camera_name in rows:
        if code in seen:
            continue
        seen.add(code)
        rooms.append((code, camera_name))
    return groups, rooms


@router.get("/namuna.xlsx")
async def weekly_template(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReadDep,
) -> Response:
    """Kafedraga yuboriladigan haftalik jadval namunasi (.xlsx)."""
    groups, rooms = await _template_lists(db)
    content = build_weekly_template(groups, rooms, lesson_minutes=settings.lesson_duration_minutes)
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''dars-jadvali-namuna.xlsx"},
    )


@router.post("/import-haftalik", response_model=LessonSessionImportResultOut)
async def import_weekly_schedule(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: EditDep,
    file: Annotated[UploadFile, File(description="Haftalik jadval: guruh, hafta kuni, boshlanish, xona, fan")],
    dan: Annotated[str, Query(description="Semestr boshlanishi, YYYY-MM-DD")],
    gacha: Annotated[str, Query(description="Semestr tugashi, YYYY-MM-DD")],
    apply: Annotated[bool, Query()] = False,
) -> LessonSessionImportResultOut:
    """Haftalik jadvalni oraliqqa yoyib import qiladi.

    `apply=false` (standart) — faqat ko'rish: nechta dars chiqadi, qaysi
    xona yoki o'qituvchi topilmadi. Hech narsa yozilmaydi."""
    try:
        start = date_type.fromisoformat(dan)
        end = date_type.fromisoformat(gacha)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Sana YYYY-MM-DD ko'rinishida bo'lishi kerak")
    if start > end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Boshlanish sanasi tugash sanasidan keyin")
    if (end - start).days > 400:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Oraliq bir yildan oshmasligi kerak")

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Fayl hajmi 5 MB dan oshmasligi kerak")

    try:
        header, rows = _read_rows(raw, file.filename or "")
    except Exception:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Faylni o'qib bo'lmadi")
    if not header:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Fayl bo'sh")

    columns = _column_map(header)
    weekday_column = next((name for name in WEEKDAY_COLUMN_ALIASES if name in header), None)
    if weekday_column is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "\"Hafta kuni\" ustuni topilmadi — namunadagi ustun nomlarini o'zgartirmang",
        )
    if "group" not in columns:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "\"Guruh\" ustuni topilmadi")

    expanded = expand_weekly(header, rows, start, end, weekday_column=weekday_column)
    if not expanded.rows:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Bitta ham dars chiqmadi — hafta kunlari yoki sana oralig'ini tekshiring",
        )

    result = await import_lessons_file(db, b"", apply=apply, prepared=(expanded.header, expanded.rows))
    result.weeks = expanded.weeks
    if expanded.bad_weekday:
        shown = ", ".join(str(num) for num in expanded.bad_weekday[:10])
        result.errors.append(
            LessonSessionImportErrorOut(row=expanded.bad_weekday[0], message=f"Hafta kuni tushunilmadi (qatorlar: {shown})")
        )
    if expanded.truncated:
        result.errors.append(
            LessonSessionImportErrorOut(row=0, message="Juda ko'p dars chiqdi — oraliqni qisqartiring")
        )
    if apply and result.imported:
        await log_action(
            db,
            request,
            current_user.id,
            f"Haftalik dars jadvali import: {result.imported} dars ({dan} — {gacha})",
            "Ta'lim",
        )
        await db.commit()
    return result

@router.get("/{session_id}/attendance", response_model=LessonAttendanceOut)
async def lesson_attendance(
    session_id: str, db: Annotated[AsyncSession, Depends(get_db)], _: AttendanceReadDep
) -> LessonAttendanceOut:
    """Bitta darsning davomat ro'yxati — TT kriteriya 7/8 ning dars
    darajasidagi javobi (app/jobs/lesson_attendance.py to'ldiradi).

    `finalized` alohida maydon sifatida qaytariladi, chunki bo'sh ro'yxat
    ikki xil ma'noga ega bo'lishi mumkin: dars hali tugamagan, yoki dars
    tugagan-u kamera hech kimni ko'rmagan. Ikkinchisi hisobotda "0%"
    emas, "ma'lumot yo'q" bo'lib ko'rinishi kerak."""
    lesson = await db.get(LessonSession, session_id)
    if lesson is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dars topilmadi")

    result = await db.execute(
        select(LessonAttendance, StudentStaff)
        .join(StudentStaff, StudentStaff.id == LessonAttendance.student_staff_id)
        .where(LessonAttendance.lesson_session_id == lesson.id)
        .order_by(StudentStaff.full_name)
    )
    pairs = result.all()

    rows = [
        LessonAttendanceRowOut(
            student_id=str(student.id),
            full_name=student.full_name,
            status=row.status,
            first_seen_at=row.first_seen_at.isoformat() if row.first_seen_at else None,
            sightings=row.sightings,
        )
        for row, student in pairs
    ]
    statuses = [r.status for r in rows]
    return LessonAttendanceOut(
        lesson_session_id=str(lesson.id),
        group=lesson.group_name,
        subject=lesson.subject,
        scheduled_start_time=lesson.scheduled_start_time.isoformat() if lesson.scheduled_start_time else None,
        finalized=any(st is not None for st in statuses),
        present=statuses.count("keldi"),
        late=statuses.count("kech_keldi"),
        absent=statuses.count("kelmadi"),
        rows=rows,
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson_session(
    session_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: EditDep,
) -> None:
    session = await db.get(LessonSession, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dars monitoring yozuvi topilmadi")

    await log_action(
        db, request, current_user.id, f"Dars monitoring yozuvini o'chirdi: {session.group_name} / {session.subject}", "Ta'lim"
    )
    await db.delete(session)
    await db.commit()
