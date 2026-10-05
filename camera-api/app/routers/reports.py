import asyncio
import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.models import Report, StudentStaff, User
from app.pagination import Page, PageParams, build_page, paginate
from app.schemas.report import (
    KpiOut,
    ReportAnalyticsOut,
    ReportCreateIn,
    ReportDetailOut,
    ReportGenerateIn,
    ReportOut,
)
from app.schemas.report_criteria import (
    ReportCriteriaOut,
    ReportPersonDetailOut,
    ReportPersonRowOut,
)
from app.services.analytics import AnalyticsRangeError, build_analytics, get_analytics_cached, validate_range
from app.services.report_criteria import (
    build_criteria,
    decorate_people,
    people_query,
    person_detail,
    resolve_period,
)
from app.services.report_criteria_export import build_criteria_workbook
from app.services.report_export import build_analytics_workbook
from app.services.report_generator import _date_range, generate_rule_based_report
from app.services.staff_export import XLSX_MIME
from app.timezone import local_now, to_local
from app.timezone import business_today

router = APIRouter(prefix="/api/reports", tags=["reports"])

PermDep = Annotated[CurrentUser, Depends(require_permission("viewReports"))]


def _kpis_from_payload(payload: dict | None) -> list[KpiOut]:
    kpis: list[KpiOut] = []
    for item in (payload or {}).get("kpis", []):
        try:
            kpis.append(KpiOut.model_validate(item))
        except ValidationError:
            continue
    return kpis


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
        sections=r.sections or [],
        range_start=r.range_start.isoformat() if r.range_start else None,
        range_end=r.range_end.isoformat() if r.range_end else None,
        created_by=r.created_by,
        has_analytics=bool(r.payload),
        kpis=_kpis_from_payload(r.payload),
    )


def _to_detail(r: Report) -> ReportDetailOut:
    analytics = None
    if r.payload:
        try:
            analytics = ReportAnalyticsOut.model_validate(r.payload)
        except ValidationError:
            # Eski tuzilmadagi payload — hisobot eski ko'rinishda ochiladi.
            analytics = None
    return ReportDetailOut(**_to_out(r).model_dump(), analytics=analytics)


def _period_for(days: int) -> str:
    """Arxiv filtri (Kunlik/Haftalik/Oylik) oraliq uzunligidan olinadi."""
    if days <= 1:
        return "Kunlik"
    if days <= 7:
        return "Haftalik"
    return "Oylik"


def _summary_text(a: ReportAnalyticsOut) -> str:
    numbers = "; ".join(f"{kpi.label}: {kpi.display}" for kpi in a.kpis[:3])
    lead = a.insights[0].title if a.insights else ""
    return f"{lead}. {numbers}" if lead else numbers


def _body_text(a: ReportAnalyticsOut) -> str:
    return "\n".join(f"• {insight.title}: {insight.text}" for insight in a.insights)


async def _load(db: AsyncSession, report_id: str) -> Report:
    try:
        report_uuid = uuid.UUID(report_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hisobot topilmadi") from None
    report = await db.get(Report, report_uuid)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hisobot topilmadi")
    return report


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


# /analytics yo'llari /{report_id} dan OLDIN e'lon qilinadi — aks holda
# "analytics" so'zi hisobot identifikatori deb tushunilardi.
@router.get("/analytics", response_model=ReportAnalyticsOut)
async def report_analytics(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: PermDep,
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
) -> ReportAnalyticsOut:
    """Tanlangan davr uchun jonli tahlil: xulosalar, KPI, davomat, xavfsizlik,
    darslar va tizim holati — app/services/analytics.py."""
    try:
        return await get_analytics_cached(db, date_from, date_to)
    except AnalyticsRangeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/analytics.xlsx")
async def report_analytics_xlsx(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: PermDep,
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
) -> Response:
    try:
        analytics = await get_analytics_cached(db, date_from, date_to)
    except AnalyticsRangeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    filename = f"hisobot-{date_from.isoformat()}_{date_to.isoformat()}.xlsx"
    return Response(
        content=await asyncio.to_thread(build_analytics_workbook, analytics),
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("", response_model=ReportDetailOut, status_code=status.HTTP_201_CREATED)
async def save_report(
    body: ReportCreateIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: PermDep,
) -> ReportDetailOut:
    """Joriy tahlilni arxivga saqlaydi. Keshdan emas — saqlangan nusxa aynan
    saqlash paytidagi ma'lumotni aks ettirishi kerak."""
    try:
        validate_range(body.date_from, body.date_to)
    except AnalyticsRangeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    analytics = await build_analytics(db, body.date_from, body.date_to)
    author = await db.get(User, current_user.id)
    report = Report(
        period=_period_for(analytics.period.days),
        period_label=body.title.strip() if body.title and body.title.strip() else analytics.period.label,
        source="rule",
        summary=_summary_text(analytics),
        body=_body_text(analytics),
        stats=[{"label": kpi.label, "value": kpi.display} for kpi in analytics.kpis],
        sections=[],
        payload=analytics.model_dump(mode="json"),
        range_start=body.date_from,
        range_end=body.date_to,
        created_by=author.full_name if author else None,
    )
    db.add(report)
    await log_action(db, request, current_user.id, f"Hisobotni arxivga saqladi: {report.period_label}", "Hisobotlar")
    await db.commit()
    await db.refresh(report)
    return _to_detail(report)


@router.post("/generate", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def generate_report(
    body: ReportGenerateIn, request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: PermDep
) -> ReportOut:
    """Eski "Kunlik/Haftalik/Oylik generatsiya" — moslik uchun qoldirilgan.
    Endi u ham to'liq tahlil ma'lumotini saqlaydi."""
    generated = await generate_rule_based_report(db, body.period)
    start, end, _label = _date_range(body.period, business_today())
    analytics = await build_analytics(db, start, end)
    author = await db.get(User, current_user.id)
    report = Report(
        period=body.period,
        period_label=generated.period_label,
        source="rule",
        summary=generated.summary,
        body=generated.body,
        stats=generated.stats,
        sections=[
            {"title": s.title, "rows": s.rows, "note": s.note} for s in generated.sections
        ],
        payload=analytics.model_dump(mode="json"),
        range_start=start,
        range_end=end,
        created_by=author.full_name if author else None,
    )
    db.add(report)
    await log_action(db, request, current_user.id, f"Hisobot generatsiya qildi: {body.period}", "Hisobotlar")
    await db.commit()
    await db.refresh(report)
    return _to_out(report)


# Kriteriya yo'llari ham /{report_id} dan OLDIN — "criteria" so'zi
# hisobot identifikatori deb tushunilmasligi uchun (yuqoridagi
# /analytics bilan bir xil sabab).
@router.get("/criteria", response_model=ReportCriteriaOut)
async def report_criteria(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: PermDep,
    population: Annotated[Literal["xodim", "talaba"], Query()] = "xodim",
    period: Annotated[Literal["bugun", "kecha", "hafta", "oy"], Query()] = "bugun",
) -> ReportCriteriaOut:
    """Hisobot sahifasining birinchi darajasi: tanlangan populyatsiya va
    davr uchun kriteriya kartalari, har birida raqamlari bilan."""
    return await build_criteria(db, population, resolve_period(period))


@router.get("/criteria.xlsx")
async def report_criteria_xlsx(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: PermDep,
    population: Annotated[Literal["xodim", "talaba"], Query()] = "xodim",
    period: Annotated[Literal["bugun", "kecha", "hafta", "oy"], Query()] = "bugun",
    variant: Annotated[Literal["qisqa", "toliq"], Query()] = "qisqa",
    criterion: Annotated[str | None, Query(max_length=40)] = None,
    bucket: Annotated[str, Query(max_length=40)] = "",
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> Response:
    """Sahifadagi filtr bo'yicha Excel: qisqa — faqat raqamlar, to'liq —
    raqamlar va har raqam ortidagi odamlar ism-familiyasi bilan
    (app/services/report_criteria_export.py)."""
    resolved = resolve_period(period)
    content = await build_criteria_workbook(
        db, population, resolved, variant=variant, criterion_key=criterion, bucket=bucket, search=search
    )
    span = resolved.start.isoformat() if resolved.start == resolved.end else f"{resolved.start}_{resolved.end}"
    filename = f"hisobot-{population}-{span}-{variant}.xlsx"
    return Response(
        content=content,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/criteria/{criterion}/people", response_model=Page[ReportPersonRowOut])
async def report_criterion_people(
    criterion: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: PermDep,
    page_params: Annotated[PageParams, Depends()],
    population: Annotated[Literal["xodim", "talaba"], Query()] = "xodim",
    period: Annotated[Literal["bugun", "kecha", "hafta", "oy"], Query()] = "bugun",
    bucket: Annotated[str, Query(max_length=40)] = "",
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[ReportPersonRowOut]:
    """Ikkinchi daraja: kartadagi raqam ortidagi odamlar ro'yxati.

    Qatorlar davomat va tashrif raqamlari bilan boyitiladi — ya'ni
    "kelgan" ro'yxatidagi odamning yonida qachon kelgani va uni qaysi
    kamera oxirgi ko'rgani ko'rinadi."""
    resolved = resolve_period(period)
    stmt = await people_query(db, population, criterion, bucket, resolved)
    if search and search.strip():
        stmt = stmt.where(StudentStaff.full_name.ilike(f"%{search.strip()}%"))
    rows, total = await paginate(db, stmt, page_params)
    items = await decorate_people(db, rows, resolved)
    return build_page(items, total, page_params)


@router.get("/people/{person_id}", response_model=ReportPersonDetailOut)
async def report_person(
    person_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: PermDep,
    period: Annotated[Literal["bugun", "kecha", "hafta", "oy"], Query()] = "bugun",
) -> ReportPersonDetailOut:
    """Uchinchi daraja: bitta odamning davr kesimi — rasmi, kafedrasi,
    kunlik holati va kameradagi ko'rinishlari soni. Aniq bir kunning
    tashriflari (qaysi kamera, qachon, qancha vaqt) GET
    /api/presence/people/{id}/day dan olinadi."""
    try:
        person_uuid = uuid.UUID(person_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi") from None
    person = (
        await db.execute(
            select(StudentStaff)
            .options(selectinload(StudentStaff.faculty))
            .where(StudentStaff.id == person_uuid)
        )
    ).scalar_one_or_none()
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")
    return await person_detail(db, person, resolve_period(period))


@router.get("/{report_id}", response_model=ReportDetailOut)
async def get_report(report_id: str, db: Annotated[AsyncSession, Depends(get_db)], _: PermDep) -> ReportDetailOut:
    return _to_detail(await _load(db, report_id))


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: str, request: Request, db: Annotated[AsyncSession, Depends(get_db)], current_user: PermDep
) -> None:
    report = await _load(db, report_id)
    # Ko'rish huquqi — o'chirish huquqi emas: faqat muallif yoki Super Admin.
    if current_user.role != "super-admin":
        author = await db.get(User, current_user.id)
        if author is None or not report.created_by or report.created_by != author.full_name:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Faqat hisobot muallifi yoki Super Admin o'chira oladi")
    await log_action(db, request, current_user.id, f"Hisobotni o'chirdi: {report.period_label}", "Hisobotlar")
    await db.delete(report)
    await db.commit()
