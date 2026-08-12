"""Dars monitoring (TT 3-E bo'lim) endpoints.

Honest scope note: attention_score / sleep_incidents / teacher_activity_score
are meant to come from AI modules 19-22 (gaze estimation, eye-closure
detection, pose tracking) — none of which have a real model behind them
yet (see app/routers/ai_modules.py). This is the storage/reporting layer;
POST here is a manual/admin entry point until that pipeline exists.
"""

from datetime import date as date_type
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, get_current_user
from app.models import LessonSession
from app.pagination import Page, PageParams, build_page, paginate
from app.schemas.lesson_session import LessonSessionCreateIn, LessonSessionOut

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
    )


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
    session = LessonSession(
        date=date_type.fromisoformat(body.date),
        group_name=body.group,
        faculty=body.faculty,
        teacher=body.teacher,
        subject=body.subject,
        attention_score=body.attention_score,
        sleep_incidents=body.sleep_incidents,
        teacher_activity_score=body.teacher_activity_score,
        teacher_on_time=body.teacher_on_time,
    )
    db.add(session)
    await log_action(
        db, request, current_user.id, f"Dars monitoring yozuvi qo'shdi: {body.group} / {body.subject}", "Ta'lim"
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
