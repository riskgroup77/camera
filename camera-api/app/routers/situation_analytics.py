"""Situatsion markaz — tahlil, biometrik ro'yxatga olish tayyorligi va devor
ekrani (`/api/situation/analytics/*`, `/enrollment*`, `/wall`).

Hisob-kitob app/services/situation_analytics.py da. Davr parametrlari
`from`/`to` (standart — bugungacha 30 kun), `type` = xodim | talaba
(standart xodim: talabalarning yuzi hali deyarli tasdiqlanmagan).
Javoblar 30 soniya keshlanadi.
"""

from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import CurrentUser, has_any_permission, require_permission
from app.models import Event
from app.routers.situation import _uuid_or_404
from app.schemas.situation import (
    AnalyticsSummaryOut,
    ArrivalOut,
    ChronicOut,
    EnrollGroupOut,
    EnrollmentOut,
    EnrollMissingOut,
    EnrollMissingPersonOut,
    HeatmapOut,
    PersonRankOut,
    SpotlightOut,
    UnitAnalyticsOut,
    WallEventOut,
    WallOut,
    WallUnitOut,
)
from app.services import situation as svc, situation_analytics as an
from app.services.access_scope import event_filter, is_restricted
from app.services.event_scope import OPERATOR_EVENTS
from app.services.event_status import OPEN_STATUSES
from app.timezone import local_now

from app.routers.report_lock import require_report_unlock

router = APIRouter(prefix="/api/situation", tags=["situation"])

ReadDep = Annotated[CurrentUser, Depends(require_permission("manageAttendance", "viewReports"))]
DbDep = Annotated[AsyncSession, Depends(get_db)]
FromQuery = Annotated[str | None, Query(alias="from", description="YYYY-MM-DD, standart — to − 29 kun")]
ToQuery = Annotated[str | None, Query(alias="to", description="YYYY-MM-DD, standart — bugun")]
TypeQuery = Annotated[Literal["xodim", "talaba"], Query(alias="type")]


def _period(date_from: str | None, date_to: str | None):
    return svc.resolve_range(date_from, date_to)


# ─────────────────────────────────────────── a. KPI va kunlik chiziq

@router.get("/analytics/summary", response_model=AnalyticsSummaryOut, dependencies=[Depends(require_report_unlock)])
async def analytics_summary(
    db: DbDep, _: ReadDep, date_from: FromQuery = None, date_to: ToQuery = None, type_: TypeQuery = "xodim",
) -> AnalyticsSummaryOut:
    """Davr KPI lari va xuddi shu uzunlikdagi oldingi davr bilan farq."""
    start, end = _period(date_from, date_to)
    data = await an.cached(("summary", type_, start, end), lambda: an.summary(db, type_, start, end))
    return AnalyticsSummaryOut(**data)


# ─────────────────────────────────────────── b. hafta kuni × soat

@router.get("/analytics/heatmap", response_model=HeatmapOut, dependencies=[Depends(require_report_unlock)])
async def analytics_heatmap(
    db: DbDep, _: ReadDep, date_from: FromQuery = None, date_to: ToQuery = None, type_: TypeQuery = "xodim",
) -> HeatmapOut:
    """Kelish vaqtlari (Du–Sha × 6..20 soat) va hafta kuni bo'yicha kechikish ulushi."""
    start, end = _period(date_from, date_to)
    data = await an.cached(("heatmap", type_, start, end), lambda: an.heatmap(db, type_, start, end))
    return HeatmapOut(**data)


# ─────────────────────────────────────────── c. bo'linmalar

@router.get("/analytics/units", response_model=list[UnitAnalyticsOut])
async def analytics_units(
    db: DbDep,
    _: ReadDep,
    date_from: FromQuery = None,
    date_to: ToQuery = None,
    type_: TypeQuery = "xodim",
    kind: Annotated[Literal["kafedra", "dekanat", "bolim", "lavozim", "guruh", "all"], Query()] = "all",
    sort: Annotated[
        Literal["rate", "late", "absent", "arrival", "punctual", "trend", "headcount", "name"], Query()
    ] = "rate",
    order: Annotated[Literal["asc", "desc"], Query()] = "desc",
) -> list[UnitAnalyticsOut]:
    """Bo'linma (xodim) yoki guruh (talaba) kesimida davr ko'rsatkichlari va
    oldingi davrga nisbatan trend. Qiymati yo'q (null) qatorlar oxirida."""
    start, end = _period(date_from, date_to)
    rows = await an.cached(("units", type_, start, end, kind), lambda: an.units(db, type_, start, end, kind))
    ordered = an.sort_rows(sorted(rows, key=lambda r: svc.norm_name(r["name"])), an.UNIT_SORTS[sort], order == "desc")
    return [UnitAnalyticsOut(**r) for r in ordered]


# ─────────────────────────────────────────── d. shaxslar reytingi

@router.get("/analytics/people", response_model=list[PersonRankOut], dependencies=[Depends(require_report_unlock)])
async def analytics_people(
    db: DbDep,
    _: ReadDep,
    date_from: FromQuery = None,
    date_to: ToQuery = None,
    type_: TypeQuery = "xodim",
    sort: Annotated[Literal["late", "absent", "arrival", "rate"], Query()] = "late",
    order: Annotated[Literal["asc", "desc"] | None, Query()] = None,
    unit_id: Annotated[str | None, Query(alias="unitId", max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[PersonRankOut]:
    """Eng muammolilar birinchi: late/absent — kunlar soni kamayish,
    arrival — o'rtacha kelish eng kechi, rate — foiz eng pasti. Davrda
    kamida bitta kelgan/kelmagan yozuvi borlar kiradi.

    `order` teskari reytinglar uchun ("eng erta keladigan", "eng yuqori
    davomat"): ro'yxat kesilishidan OLDIN tartiblanadi."""
    start, end = _period(date_from, date_to)
    rows = await an.cached(
        ("people", type_, start, end, sort, unit_id, limit, order),
        lambda: an.people(db, type_, start, end, sort, unit_id, limit, order),
    )
    return [PersonRankOut(**r) for r in rows]


# ─────────────────────────────────────────── e. surunkali ro'yxat

@router.get("/analytics/chronic", response_model=list[ChronicOut])
async def analytics_chronic(
    db: DbDep,
    _: ReadDep,
    date_from: FromQuery = None,
    date_to: ToQuery = None,
    type_: TypeQuery = "xodim",
    min_absent: Annotated[int, Query(alias="minAbsent", ge=1, le=366)] = 3,
    min_late: Annotated[int, Query(alias="minLate", ge=1, le=366)] = 3,
) -> list[ChronicOut]:
    """Davrda kamida minAbsent marta kelmagan YOKI minLate marta kech
    kelganlar, sanalari bilan (ko'p muammolisi birinchi)."""
    start, end = _period(date_from, date_to)
    rows = await an.cached(
        ("chronic", type_, start, end, min_absent, min_late),
        lambda: an.chronic(db, type_, start, end, min_absent, min_late),
    )
    return [ChronicOut(**r) for r in rows]


# ─────────────────────────────────────────── f. biometrik ro'yxatga olish

@router.get("/enrollment", response_model=EnrollmentOut)
async def enrollment(db: DbDep, _: ReadDep) -> EnrollmentOut:
    """Yuzi tasdiqlanganlar ulushi: institut, fakultetlar (talabalar)."""
    return EnrollmentOut(**await an.cached(("enrollment",), lambda: an.enrollment(db)))


@router.get("/enrollment/groups", response_model=list[EnrollGroupOut])
async def enrollment_groups(
    db: DbDep,
    _: ReadDep,
    faculty_id: Annotated[str | None, Query(alias="facultyId")] = None,
    course: Annotated[int | None, Query(ge=1, le=12)] = None,
) -> list[EnrollGroupOut]:
    """Guruhlar ro'yxatga olish foizi bo'yicha o'sib borish tartibida (eng orqadagisi birinchi)."""
    fid = None
    if faculty_id:
        fid = _uuid_or_404(faculty_id, "Fakultet topilmadi")
    rows = await an.cached(("enroll_groups", fid, course), lambda: an.enrollment_groups(db, fid, course))
    return [EnrollGroupOut(**r) for r in rows]


@router.get("/enrollment/groups/{group_name:path}/missing", response_model=EnrollMissingOut)
async def enrollment_missing(group_name: str, db: DbDep, _: ReadDep) -> EnrollMissingOut:
    """Guruhning yuzi tasdiqlanmagan faol talabalari va chop etiladigan QR
    uchun ro'yxatdan o'tish havolasi."""
    missing, total = await an.enrollment_missing(db, group_name)
    if not total and group_name not in {name for name, _f, _c in await svc.student_group_rows(db)}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Guruh topilmadi")
    base = settings.frontend_base_url.rstrip("/")
    return EnrollMissingOut(
        group=group_name, total=total, missing=[EnrollMissingPersonOut(**m) for m in missing],
        enroll_url=f"{base}/royxatdan-otish?guruh={quote(group_name, safe='')}",
        enroll_code="",
    )


# ─────────────────────────────────────────── g. devor ekrani

@router.get("/wall", response_model=WallOut)
async def wall(db: DbDep, current_user: ReadDep) -> WallOut:
    """Devor ekrani uchun bitta ixcham javob (15–30 soniyada bir so'rov).

    Kesh umumiy (davomat hamma uchun bir xil), lekin yuqori xavfli
    hodisalar — faqat reviewEvents egasiga va uning bino doirasida."""
    out = await an.cached(("wall", svc.today()), lambda: _build_wall(db))
    if not await has_any_permission(db, current_user.role, ("reviewEvents",)):
        return out.model_copy(update={"high_events": [], "high_open": 0})
    if is_restricted(current_user):
        events, high_open = await _high_events(db, current_user)
        return out.model_copy(update={"high_events": events, "high_open": high_open})
    return out


async def _high_events(db: AsyncSession, user: CurrentUser | None) -> tuple[list[WallEventOut], int]:
    scope = event_filter(user)
    base = (
        select(Event.id, Event.module_name, Event.camera_name, Event.building, Event.occurred_at, Event.status)
        .where(OPERATOR_EVENTS)
        .where(Event.status.in_(OPEN_STATUSES))
        .where(Event.severity == "yuqori")
        .where(scope)
    )
    rows = (await db.execute(base.order_by(Event.occurred_at.desc()).limit(5))).all()
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    return [
        WallEventOut(id=str(eid), module_name=module, camera_name=camera, building=building,
                     time=svc.hm(occurred) or "", status=event_status)
        for eid, module, camera, building, occurred, event_status in rows
    ], int(total)


# Devor ekranidagi reyting/"diqqat markazida" uchun eng kam o'lchangan
# odam soni (keldi + kelmadi + hali kelmagan).
WALL_MIN_MEASURED = 3


def _wall_unit(u: an.UnitToday) -> WallUnitOut:
    return WallUnitOut(id=u.ref.id, name=u.ref.name, kind=u.ref.kind, total=u.counts.total,
                       present=u.counts.present, rate=u.counts.rate)


async def _build_wall(db: AsyncSession) -> WallOut:
    day = svc.today()
    pending = True
    rows = await svc.unit_rows(db, day)
    students = svc.type_counts(rows, "talaba", pending)
    staff = svc.type_counts(rows, "xodim", pending)
    students_ok = svc.students_data_available(students)

    # "Lavozim bo'yicha" soxta bo'linmasi reytingga kirmaydi. Bir-ikki
    # kishisi o'lchanadigan bo'linma ham kirmaydi: 0% yoki 100% o'sha
    # bir kishidan chiqadi — devor ekranida bu "reyting" emas, shovqin.
    # Mezon "Institut holati" sahifasidagi bilan bir xil (rankUnits).
    units = [u for u in await an.staff_units_today(db, day)
             if u.ref.id != svc.UNASSIGNED_KAFEDRA_ID and u.counts.rate is not None
             and u.counts.present + u.counts.absent + u.counts.not_yet >= WALL_MIN_MEASURED]
    ranked = sorted(units, key=lambda u: (-u.counts.rate, svc.norm_name(u.ref.name)))
    top = ranked[:5]
    bottom = sorted(units, key=lambda u: (u.counts.rate, svc.norm_name(u.ref.name)))[:5]

    events = (
        await db.execute(
            select(Event.id, Event.module_name, Event.camera_name, Event.building, Event.occurred_at, Event.status)
            .where(OPERATOR_EVENTS)
            .where(Event.status.in_(OPEN_STATUSES))
            .where(Event.severity == "yuqori")
            .order_by(Event.occurred_at.desc())
            .limit(5)
        )
    ).all()
    cameras = await svc.camera_summary(db)
    events_summary = await svc.event_summary(db, day)

    spotlight = [SpotlightOut(kind="unit", id=u.ref.id, name=u.ref.name, rate=u.counts.rate)
                 for u in sorted(units, key=lambda u: svc.norm_name(u.ref.name))
                 if u.counts.present + u.counts.absent]
    # Talabalar yuzi yetarli bo'lmaguncha guruh foizi o'lchov emas —
    # 30 kishilik guruhdan 2 tasi tanilsa, ekranda "6%" chiqib qolardi.
    if students_ok:
        for name, agg in sorted(svc.aggregate_groups(rows, pending).items()):
            measured = agg.counts.present + agg.counts.absent + agg.counts.not_yet
            if name and agg.counts.present + agg.counts.absent and measured >= WALL_MIN_MEASURED:
                spotlight.append(SpotlightOut(kind="group", id=name, name=name, rate=agg.counts.rate))

    return WallOut(
        date=day.isoformat(),
        generated_at=local_now().isoformat(timespec="seconds"),
        students=students.out(),
        staff=staff.out(),
        students_data_available=students_ok,
        top_units=[_wall_unit(u) for u in top],
        bottom_units=[_wall_unit(u) for u in bottom],
        last_arrivals=[ArrivalOut(**r) for r in await svc.last_arrivals(db, day, limit=12)],
        high_events=[
            WallEventOut(id=str(eid), module_name=module, camera_name=camera, building=building,
                         time=svc.hm(occurred) or "", status=event_status)
            for eid, module, camera, building, occurred, event_status in events
        ],
        cameras_online=cameras["online"],
        # Ataylab o'chirilgan ("nofaol") kamera "javob bermayapti" emas:
        # maxraj — ishlashi kerak bo'lgan kameralar, "Institut holati"
        # sahifasidagi kabi (cameras.active).
        cameras_total=cameras["active"],
        # Ro'yxat eng so'nggi 5 tasi bilan cheklangan — ochiq yuqori
        # xavfli hodisalar soni alohida keladi, aks holda ekranda
        # "5" turib qolardi.
        high_open=events_summary["high_open"],
        enrollment=EnrollmentOut(**await an.cached(("enrollment",), lambda: an.enrollment(db))),
        spotlight=spotlight,
    )
