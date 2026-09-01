from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.models import Report
from app.pagination import Page, PageParams, build_page, paginate
from app.schemas.report import ReportGenerateIn, ReportOut
from app.services.report_generator import generate_rule_based_report
from app.timezone import to_local

router = APIRouter(prefix="/api/reports", tags=["reports"])

PermDep = Annotated[CurrentUser, Depends(require_permission("viewReports"))]


def _to_out(r: Report) -> ReportOut:
    return ReportOut(
        id=str(r.id),
        period=r.period,
        period_label=r.period_label,
        generated_at=to_local(r.generated_at).strftime("%Y-%m-%d %H:%M"),
        source=r.source,
        summary=r.summary,
        body=r.body,
        stats=r.stats,
    )


@router.get("", response_model=Page[ReportOut])
async def list_reports(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: PermDep,
    page_params: Annotated[PageParams, Depends()],
    period: Annotated[str | None, Query()] = None,
) -> Page[ReportOut]:
    stmt = select(Report).order_by(Report.generated_at.desc())
    if period:
        stmt = stmt.where(Report.period == period)
    records, total = await paginate(db, stmt, page_params)
    return build_page([_to_out(r) for r in records], total, page_params)


@router.get("/{report_id}", response_model=ReportOut)
async def get_report(report_id: str, db: Annotated[AsyncSession, Depends(get_db)], _: PermDep) -> ReportOut:
    report = await db.get(Report, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hisobot topilmadi")
    return _to_out(report)


@router.post("/generate", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def generate_report(
    body: ReportGenerateIn, request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: PermDep
) -> ReportOut:
    generated = await generate_rule_based_report(db, body.period)
    report = Report(
        period=body.period,
        period_label=generated.period_label,
        source="rule",
        summary=generated.summary,
        body=generated.body,
        stats=generated.stats,
    )
    db.add(report)
    await log_action(db, request, current_user.id, f"Hisobot generatsiya qildi: {body.period}", "Hisobotlar")
    await db.commit()
    await db.refresh(report)
    return _to_out(report)


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: str, request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: PermDep
) -> None:
    report = await db.get(Report, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hisobot topilmadi")

    await log_action(db, request, current_user.id, f"Hisobotni o'chirdi: {report.period_label}", "Hisobotlar")
    await db.delete(report)
    await db.commit()
