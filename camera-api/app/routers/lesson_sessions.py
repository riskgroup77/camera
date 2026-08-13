"""Dars monitoring (TT 3-E bo'lim) endpoints.

Honest scope note: attention_score / sleep_incidents / teacher_activity_score
are meant to come from AI modules 19-22 (gaze estimation, eye-closure
detection, pose tracking) — none of which have a real model behind them
yet (see app/routers/ai_modules.py). This is the storage/reporting layer;
POST here is a manual/admin entry point until that pipeline exists.
"""

from datetime import date as date_type, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, get_current_user
from app.models import Camera, LessonSession, StudentStaff
from app.pagination import Page, PageParams, build_page, paginate
from app.schemas.lesson_session import LessonSessionCreateIn, LessonSessionOut, LessonSessionScheduleIn
from app.timezone import INSTITUTE_TZ

router = APIRouter(prefix="/api/lesson-sessions", tags=["lesson-sessions"])


def _to_out(s: LessonSession) -> LessonSessionOut:
    return LessonSessionOut(
        id=str(s.id),
        date=s.date.isoformat(),
        group=s.group_name,
        faculty=s.faculty,
        teacher=s.teacher,
        subject=s.subject,
        attention_score=s.attention_score,
        sleep_incidents=s.sleep_incidents,
        teacher_activity_score=s.teacher_activity_score,
        teacher_on_time=s.teacher_on_time,
        teacher_id=str(s.teacher_id) if s.teacher_id else None,
        camera_id=str(s.camera_id) if s.camera_id else None,
        scheduled_start_time=s.scheduled_start_time.isoformat() if s.scheduled_start_time else None,
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
    """Accepts an ISO 8601 string — naive (e.g. from an HTML
    datetime-local input, "2026-08-13T09:00") is interpreted as
    institute-local time (see app/timezone.py), matching every other
    human-facing time setting in this system (attendance cutoffs etc.).
    Already-aware strings are kept as given."""
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=INSTITUTE_TZ)
    return parsed


@router.get("", response_model=Page[LessonSessionOut])
async def list_lesson_sessions(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(get_current_user)],
    page_params: Annotated[PageParams, Depends()],
    group: Annotated[str | None, Query()] = None,
    faculty: Annotated[str | None, Query()] = None,
) -> Page[LessonSessionOut]:
    stmt = select(LessonSession).order_by(LessonSession.date.desc())
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
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
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
        attention_score=body.attention_score,
        sleep_incidents=body.sleep_incidents,
        teacher_activity_score=body.teacher_activity_score,
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
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
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


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson_session(
    session_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    session = await db.get(LessonSession, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dars monitoring yozuvi topilmadi")

    await log_action(
        db, request, current_user.id, f"Dars monitoring yozuvini o'chirdi: {session.group_name} / {session.subject}", "Ta'lim"
    )
    await db.delete(session)
    await db.commit()
