"""Avtomatik hisobot jadvallari (`/api/hisobot-jadval`).

  GET    /api/hisobot-jadval             — ro'yxat (viewReports)
  POST   /api/hisobot-jadval             — yangi (manageNotifications)
  PATCH  /api/hisobot-jadval/{id}        — o'zgartirish (manageNotifications)
  DELETE /api/hisobot-jadval/{id}        — o'chirish (manageNotifications)
  POST   /api/hisobot-jadval/{id}/sinov  — o'tgan davr hisobotini hozir yuborish

Yuborish mantiqi app/services/report_schedule.py da, fondagi sikl
app/jobs/report_schedules.py da. Qabul qiluvchilar — Telegram chat ID
(bildirishnoma qoidalari bilan bir xil tekshiruv).
"""

import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.models import ReportSchedule
from app.schemas.base import CamelModel
from app.schemas.notifications import clean_recipients
from app.services import report_schedule as rs
from app.services.notifications import telegram
from app.timezone import to_local

router = APIRouter(prefix="/api/hisobot-jadval", tags=["hisobot"])

ReadDep = Annotated[CurrentUser, Depends(require_permission("viewReports"))]
ManageDep = Annotated[CurrentUser, Depends(require_permission("manageNotifications"))]
DbDep = Annotated[AsyncSession, Depends(get_db)]

AUDIT_MODULE = "Hisobotlar"
ScheduleKind = Literal["kunlik", "haftalik", "oylik"]
ScheduleReport = Literal["kpi", "davomat_xodim", "davomat_talaba", "tabel_xodim", "tabel_talaba", "jadval_davomat"]


def _chat_ids(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    cleaned = clean_recipients("telegram", value)
    if not cleaned:
        raise ValueError("Kamida bitta Telegram chat ID kerak")
    return cleaned


class ScheduleIn(CamelModel):
    name: str = Field(min_length=1, max_length=120)
    kind: ScheduleKind
    report: ScheduleReport
    telegram_chat_ids: list[str]
    enabled: bool = True

    _chats = field_validator("telegram_chat_ids")(_chat_ids)


class ScheduleUpdateIn(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: ScheduleKind | None = None
    report: ScheduleReport | None = None
    telegram_chat_ids: list[str] | None = None
    enabled: bool | None = None

    _chats = field_validator("telegram_chat_ids")(_chat_ids)


class ScheduleOut(CamelModel):
    id: str
    name: str
    kind: str
    report: str
    telegram_chat_ids: list[str]
    enabled: bool
    last_sent_at: str | None
    created_at: str | None


class SendOut(CamelModel):
    sent: int
    failed: int
    errors: list[str]
    period_from: str
    period_to: str


def _out(row: ReportSchedule) -> ScheduleOut:
    return ScheduleOut(
        id=str(row.id), name=row.name, kind=row.kind, report=row.report,
        telegram_chat_ids=[str(c) for c in row.telegram_chat_ids or []], enabled=row.enabled,
        last_sent_at=to_local(row.last_sent_at).isoformat(timespec="seconds") if row.last_sent_at else None,
        created_at=to_local(row.created_at).isoformat(timespec="seconds") if row.created_at else None,
    )


async def _load(db: AsyncSession, schedule_id: str) -> ReportSchedule:
    try:
        key = uuid.UUID(schedule_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Jadval topilmadi") from None
    row = await db.get(ReportSchedule, key)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Jadval topilmadi")
    return row


@router.get("", response_model=list[ScheduleOut])
async def list_schedules(db: DbDep, _: ReadDep) -> list[ScheduleOut]:
    rows = (await db.execute(select(ReportSchedule).order_by(ReportSchedule.created_at))).scalars().all()
    return [_out(r) for r in rows]


@router.post("", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
async def create_schedule(body: ScheduleIn, request: Request, db: DbDep, user: ManageDep) -> ScheduleOut:
    row = ReportSchedule(
        name=body.name.strip(), kind=body.kind, report=body.report, telegram_chat_ids=body.telegram_chat_ids,
        enabled=body.enabled, created_by=uuid.UUID(str(user.id)),
    )
    db.add(row)
    await log_action(db, request, user.id, f"Avtomatik hisobot qo'shdi: {row.name}", AUDIT_MODULE)
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.patch("/{schedule_id}", response_model=ScheduleOut)
async def update_schedule(schedule_id: str, body: ScheduleUpdateIn, request: Request, db: DbDep,
                          user: ManageDep) -> ScheduleOut:
    row = await _load(db, schedule_id)
    for field in body.model_fields_set:
        value = getattr(body, field)
        if value is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'{field}' bo'sh bo'lishi mumkin emas")
        setattr(row, field, value.strip() if field == "name" else value)
    await log_action(db, request, user.id, f"Avtomatik hisobotni o'zgartirdi: {row.name}", AUDIT_MODULE)
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(schedule_id: str, request: Request, db: DbDep, user: ManageDep) -> None:
    row = await _load(db, schedule_id)
    await db.delete(row)
    await log_action(db, request, user.id, f"Avtomatik hisobotni o'chirdi: {row.name}", AUDIT_MODULE)
    await db.commit()


@router.post("/{schedule_id}/sinov", response_model=SendOut)
async def send_now(schedule_id: str, request: Request, db: DbDep, user: ManageDep) -> SendOut:
    """O'tgan davr hisobotini hozir yuboradi. last_sent_at o'zgarmaydi —
    sinov navbatdagi avtomatik yuborishni bekor qilmasin."""
    row = await _load(db, schedule_id)
    if not telegram.is_configured():
        raise HTTPException(status.HTTP_409_CONFLICT, "Telegram bot sozlanmagan")
    start, end = rs.period_for(row.kind, rs.last_boundary(row.kind, datetime.now(timezone.utc)))
    outcome = await rs.send(db, row, start, end)
    await log_action(db, request, user.id, f"Avtomatik hisobot sinovi: {row.name}", AUDIT_MODULE)
    await db.commit()
    return SendOut(sent=outcome.sent, failed=outcome.failed, errors=outcome.errors,
                   period_from=start.isoformat(), period_to=end.isoformat())
