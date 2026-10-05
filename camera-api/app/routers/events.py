import logging
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import case, false, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit import log_action
from app.database import SessionLocal, get_db
from app.dependencies import CurrentUser, has_any_permission, require_permission, user_from_token
from app.models import Camera, Event, EventComment, User
from app.models.user import ROLE_LABELS, role_display_label
from app.pagination import Page, PageParams, build_page, paginate
from app.schemas.event import (
    EventAssigneeOut,
    EventAssignIn,
    EventBulkReviewIn,
    EventBulkReviewOut,
    EventCommentIn,
    EventCommentOut,
    EventCreateIn,
    EventFacetOut,
    EventOut,
    EventReviewIn,
    EventStatusIn,
    EventSummaryOut,
    EventTimelineItemOut,
)
from app.services.event_bus import event_to_out, sla_due_at
from app.services.access_scope import NOT_FOUND_EVENT, allowed_buildings, event_filter, is_restricted
from app.services.sop import load_sops
from app.services.event_scope import NOT_SUPPRESSED, OPERATOR_EVENTS, REGISTERED_MODULE
from app.services.event_status import (
    ACTIVE_STATUSES,
    CONFIRMED_STATUSES,
    OPEN_STATUSES,
    STATUS_LABELS,
    STATUSES,
    can_transition,
)
from app.services.notifications import notify_user
from app.storage import delete_files_quietly
from app.timezone import business_today, INSTITUTE_TZ, local_now, to_local
from app.ws import manager
from app.timezone import day_start

logger = logging.getLogger("app.events")

router = APIRouter(tags=["events"])

SERIOUS = ("o'rta", "yuqori")
REVIEW_STATS_DAYS = 30
MIN_REVIEWS_FOR_PRECISION = 10
FACET_LIMIT = 40
AUDIT_MODULE = "AI Modullari"

# Hodisalarni ko'rish va ko'rib chiqish huquqi (app/seed.py).
REVIEW_PERMISSION = "reviewEvents"
ReviewDep = Annotated[CurrentUser, Depends(require_permission(REVIEW_PERMISSION))]

# WebSocket yopilish kodlari — src/lib/realtime.ts ular kelganda qayta
# ulanmaydi: token yaroqsiz yoki huquq yo'q bo'lsa, har 3 soniyada qayta
# urinish faqat shovqin.
WS_CLOSE_UNAUTHORIZED = 4401
WS_CLOSE_FORBIDDEN = 4403


def _to_out(
    event: Event,
    *,
    assignee_name: str | None = None,
    comments_count: int | None = None,
    sop: list[str] | None = None,
) -> EventOut:
    return event_to_out(event, assignee_name=assignee_name, comments_count=comments_count, sop=sop)


def _local_day_start(day: date) -> datetime:
    return day_start(day)


def _iso(moment: datetime) -> str:
    return to_local(moment).isoformat(timespec="seconds")


def _parse_uuid(raw: str, message: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(code, message) from None


async def _get_event(db: AsyncSession, event_id: str, user: CurrentUser, *, for_update: bool = False) -> Event:
    """Hodisani topadi. Noto'g'ri identifikator ham "topilmadi" — bazaga
    yaroqsiz UUID yuborilsa 500 qaytardi.

    `user` MAJBURIY: bino doirasidan tashqaridagi hodisa ham "topilmadi"
    (app/services/access_scope.py). Ixtiyoriy qilinsa, yangi endpoint
    uni uzatishni unutib, doirani jimgina aylanib o'tardi."""
    parsed = _parse_uuid(event_id, NOT_FOUND_EVENT, status.HTTP_404_NOT_FOUND)
    stmt = select(Event).where(Event.id == parsed).where(event_filter(user))
    if for_update:
        # Ikki operator bir vaqtda holatni o'zgartirsa, o'tish qoidasi
        # eskirgan holatga qarab tekshirilmasin.
        stmt = stmt.with_for_update()
    event = (await db.execute(stmt)).scalar_one_or_none()
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hodisa topilmadi")
    return event


async def _user_names(db: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.full_name).where(User.id.in_(ids)))).all()
    return {user_id: name for user_id, name in rows}


async def _comment_counts(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(EventComment.event_id, func.count())
            .where(EventComment.event_id.in_(ids))
            .group_by(EventComment.event_id)
        )
    ).all()
    return {event_id: count for event_id, count in rows}


async def _outs(db: AsyncSession, events: list[Event]) -> list[EventOut]:
    """Ro'yxat uchun: tayinlanganlar ismlari va izohlar soni ikkita so'rovda."""
    names = await _user_names(db, {e.assigned_to_id for e in events if e.assigned_to_id})
    counts = await _comment_counts(db, [e.id for e in events])
    # Administrator o'zgartirgan ko'rsatmalar — modul kodi bo'yicha bitta so'rov.
    sops = await load_sops(db, {e.module_code for e in events})
    return [
        _to_out(
            e,
            assignee_name=names.get(e.assigned_to_id) if e.assigned_to_id else None,
            comments_count=counts.get(e.id, 0),
            sop=sops.get(e.module_code),
        )
        for e in events
    ]


async def _out(db: AsyncSession, event: Event) -> EventOut:
    return (await _outs(db, [event]))[0]


async def _broadcast_update(event: Event, out: EventOut) -> None:
    """Ochiq sahifalar (jurnal, devor, panel) hodisani joyida yangilashi uchun.

    Xabar tekis EventOut + "kind": "event_updated" — AIEvent sifatida ham
    o'qiladi, shuning uchun eski ishlovchilar ham buzilmaydi. Sinov signali
    operator sahifalariga umuman kelmagan — uning o'zgarishi ham yuborilmaydi."""
    if event.is_trial:
        return
    await manager.broadcast({**out.model_dump(by_alias=True), "kind": "event_updated"})


async def _actor_name(db: AsyncSession, current_user: CurrentUser) -> str:
    actor = await db.get(User, current_user.id)
    return actor.full_name if actor else "Noma'lum"


def _apply_status(
    event: Event,
    target: str,
    *,
    actor_id: uuid.UUID,
    actor_name: str,
    note: str | None,
    now: datetime,
) -> str:
    """Holatni o'zgartiradi va unga bog'liq maydonlarni moslaydi. Tarixga
    yoziladigan matnni qaytaradi. O'tish qoidasi chaqiruvchida tekshiriladi.

    - tasdiqlangan / rad_etilgan: ko'rib chiqish qarori (reviewed_by/at —
      aniqlik va "o'rtacha ko'rib chiqish vaqti" shularga tayanadi);
    - hal_qilindi: yechim izohi majburiy; qaror hali qilinmagan bo'lsa,
      hal qilingan hodisa haqiqiy deb ham belgilanadi;
    - jarayonda: yopilgan hodisa qayta ochilsa, avvalgi qaror bekor bo'ladi;
      hech kimga tayinlanmagan bo'lsa — uni olgan operatorga tayinlanadi;
    - yangi: navbatga qaytarish — tayinlov olib tashlanadi."""
    previous = event.status
    event.status = target
    if target in ("tasdiqlangan", "rad_etilgan"):
        event.reviewed_by = actor_name
        event.reviewed_at = now
        event.resolved_at = None
        event.resolved_by = None
        event.resolution_note = None
    elif target == "hal_qilindi":
        event.resolution_note = note
        event.resolved_at = now
        event.resolved_by = actor_name
        if previous in OPEN_STATUSES or event.reviewed_at is None:
            event.reviewed_by = actor_name
            event.reviewed_at = now
    elif target == "jarayonda":
        if previous not in OPEN_STATUSES:
            event.reviewed_by = None
            event.reviewed_at = None
            event.resolved_at = None
            event.resolved_by = None
            event.resolution_note = None
        if event.assigned_to_id is None:
            event.assigned_to_id = actor_id
            event.assigned_at = now
    elif target == "yangi":
        event.assigned_to_id = None
        event.assigned_at = None
        event.reviewed_by = None
        event.reviewed_at = None

    text = f"{STATUS_LABELS.get(previous, previous)} → {STATUS_LABELS.get(target, target)}"
    return f"{text}: {note}" if note else text


def _clean_note(note: str | None) -> str | None:
    return note.strip() if note and note.strip() else None


async def authorize_events_socket(token: str | None, session_factory=SessionLocal) -> int | None:
    """None — ulanish mumkin; aks holda WebSocket yopilish kodi.

    Sessiya faqat tekshiruv uchun ochiladi va darhol yopiladi: ulanish
    soatlab ochiq turadi, butun umri davomida pool'dan bitta bog'lanishni
    band qilib turish mumkin emas."""
    if not token:
        return WS_CLOSE_UNAUTHORIZED
    async with session_factory() as db:
        try:
            user = await user_from_token(token, db)
        except HTTPException:
            return WS_CLOSE_UNAUTHORIZED
        if user.needs_2fa_setup:
            return WS_CLOSE_FORBIDDEN
        # Davomatni ko'radiganlar ham ulanadi (jonli kelishlar), lekin ularga
        # faqat davomat xabarlari boradi — hodisalar reviewEvents egalariga.
        if not await has_any_permission(db, user.role, SOCKET_PERMISSIONS):
            return WS_CLOSE_FORBIDDEN
    return None


#: /ws/events ga ulanish uchun yetarli huquqlardan biri.
SOCKET_PERMISSIONS = (REVIEW_PERMISSION, "manageAttendance", "viewReports")


async def socket_sees_events(token: str | None, session_factory=SessionLocal) -> bool:
    """Ulanish hodisa xabarlarini ham oladimi (reviewEvents) yoki faqat davomatni."""
    async with session_factory() as db:
        try:
            user = await user_from_token(token or "", db)
        except HTTPException:
            return False
        return await has_any_permission(db, user.role, (REVIEW_PERMISSION,))


async def socket_camera_scope(token: str | None, session_factory=SessionLocal) -> frozenset[str] | None:
    """Bino doirasi bor foydalanuvchi uchun — ulanish paytidagi ruxsat
    etilgan kameralar; cheklovsiz bo'lsa None. authorize_events_socket
    allaqachon tokenni tekshirgan, bu yerda faqat doira o'qiladi.

    Ulanish paytidagi surat: keyin qo'shilgan kamera qayta ulanguncha
    ko'rinmaydi (xavfsiz tomonga xato)."""
    async with session_factory() as db:
        try:
            user = await user_from_token(token or "", db)
        except HTTPException:
            return frozenset()
        ids = allowed_buildings(user)
        if ids is None:
            return None
        rows = (await db.execute(select(Camera.id).where(Camera.building_id.in_(ids)))).scalars().all()
    return frozenset(str(camera_id) for camera_id in rows)


@router.websocket("/ws/events")
async def events_websocket(websocket: WebSocket) -> None:
    """Real-time push for new AI events — replaces the frontend's
    setInterval-based simulation (camera/src/lib/realtime.ts) with an
    actual persistent connection. Auth via ?token=<jwt> since browser
    WebSocket APIs can't set an Authorization header.

    HTTP endpointlar bilan bir xil tekshiruv: chiqib ketilgan token ham,
    hodisalarni ko'rish huquqi bo'lmagan rol ham ulanmaydi."""
    close_code = await authorize_events_socket(websocket.query_params.get("token"))
    if close_code is not None:
        # Avval qabul qilinadi: qabul qilinmagan ulanish yopilsa, brauzer
        # kodni ko'rmaydi (1006) va sababini ajrata olmaydi.
        await websocket.accept()
        await websocket.close(code=close_code)
        return

    token = websocket.query_params.get("token")
    await manager.connect(
        websocket, await socket_camera_scope(token), attendance_only=not await socket_sees_events(token)
    )
    try:
        while True:
            await websocket.receive_text()  # no client->server protocol yet; just detect disconnects
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@router.get("/api/events", response_model=Page[EventOut])
async def list_events(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
    page_params: Annotated[PageParams, Depends()],
    severity: Annotated[str | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    today: Annotated[bool, Query()] = False,
    exclude_modules: Annotated[str | None, Query(alias="excludeModules")] = None,
    hide_rejected: Annotated[bool, Query(alias="hideRejected")] = False,
    module_codes: Annotated[str | None, Query(alias="moduleCodes")] = None,
    building: Annotated[str | None, Query(max_length=200)] = None,
    camera_id: Annotated[str | None, Query(alias="cameraId")] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    sort: Annotated[Literal["newest", "oldest", "severity", "due"], Query()] = "newest",
    trial: Annotated[bool, Query()] = False,
    exclude_suppressed: Annotated[bool, Query(alias="excludeSuppressed")] = False,
    assigned_to: Annotated[str | None, Query(alias="assignedTo", max_length=64)] = None,
    overdue: Annotated[bool, Query()] = False,
) -> Page[EventOut]:
    # trial=true — faqat sinov rejimidagi modullar signallari (baholash uchun).
    stmt = (
        select(Event)
        .where(Event.is_trial == (true() if trial else false()))
        .where(REGISTERED_MODULE)
        .where(event_filter(current_user))
    )
    if exclude_suppressed:
        # Monitoring devoridagi alarm (event_scope.NOT_SUPPRESSED).
        stmt = stmt.where(NOT_SUPPRESSED)
    if severity:
        stmt = stmt.where(Event.severity == severity)
    if status_filter:
        # Bitta holat yoki vergul bilan bir nechtasi ("yangi,jarayonda" —
        # ko'rib chiqish navbati).
        statuses = [s.strip() for s in status_filter.split(",") if s.strip()]
        unknown = [s for s in statuses if s not in STATUSES]
        if unknown:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Noma'lum holat: {', '.join(unknown)}")
        if statuses:
            stmt = stmt.where(Event.status.in_(statuses))
    if assigned_to:
        if assigned_to == "me":
            stmt = stmt.where(Event.assigned_to_id == uuid.UUID(current_user.id))
        elif assigned_to == "none":
            stmt = stmt.where(Event.assigned_to_id.is_(None))
        else:
            stmt = stmt.where(
                Event.assigned_to_id == _parse_uuid(assigned_to, "Noto'g'ri foydalanuvchi identifikatori")
            )
    if overdue:
        stmt = stmt.where(Event.due_at < datetime.now(timezone.utc)).where(Event.status.in_(OPEN_STATUSES))
    if search and search.strip():
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(Event.module_name.ilike(term), Event.camera_name.ilike(term), Event.person_name.ilike(term))
        )
    if exclude_modules:
        # Vergul bilan ajratilgan modul kodlari. Monitoring devoridagi
        # jurnal buni ishlatadi: u operator diqqatini talab qiladigan
        # signallar uchun, ma'lum bir modul esa hozircha faqat shovqin
        # bergani uchun (masalan #25 — u qaysi kamera hovliga qaraganini
        # bilmaydi) uni butun tizimdan o'chirmasdan shu ro'yxatdan
        # olib tashlash kerak bo'ladi.
        codes = [int(c) for c in exclude_modules.split(",") if c.strip().isdigit()]
        if codes:
            stmt = stmt.where(Event.module_code.notin_(codes))
    if module_codes:
        codes = [int(c) for c in module_codes.split(",") if c.strip().isdigit()]
        if codes:
            stmt = stmt.where(Event.module_code.in_(codes))
    if building:
        stmt = stmt.where(Event.building == building)
    if camera_id:
        stmt = stmt.where(Event.camera_id == _parse_uuid(camera_id, "Noto'g'ri kamera identifikatori"))
    if hide_rejected:
        # Operator "yolg'on signal" deb belgilagan hodisa devorga qayta
        # chiqmasligi kerak — aks holda uni har safar qaytadan ko'rib
        # chiqishga to'g'ri keladi.
        stmt = stmt.where(Event.status != "rad_etilgan")
    if today:
        # "Today" means the institute's local calendar day, not UTC's —
        # see app/timezone.py's module docstring for why that distinction
        # is a real bug, not pedantry (near-midnight local time, a plain
        # UTC "today" is off by a day).
        start_of_today = day_start(business_today())
        stmt = stmt.where(Event.occurred_at >= start_of_today)
    # Sana oralig'i institut kunlari bo'yicha: [from 00:00, to+1 00:00).
    if date_from:
        stmt = stmt.where(Event.occurred_at >= _local_day_start(date_from))
    if date_to:
        stmt = stmt.where(Event.occurred_at < _local_day_start(date_to + timedelta(days=1)))

    if sort == "oldest":
        stmt = stmt.order_by(Event.occurred_at.asc())
    elif sort == "severity":
        # Ko'rib chiqish navbati: avval yuqori, keyin o'rta, har biri ichida eng yangisi.
        rank = case((Event.severity == "yuqori", 0), (Event.severity == "o'rta", 1), else_=2)
        stmt = stmt.order_by(rank, Event.occurred_at.desc())
    elif sort == "due":
        # Muddati eng yaqin (yoki eng ko'p o'tgan) birinchi; muddatsizlar oxirida.
        stmt = stmt.order_by(Event.due_at.asc().nulls_last(), Event.occurred_at.desc())
    else:
        stmt = stmt.order_by(Event.occurred_at.desc())

    records, total = await paginate(db, stmt, page_params)
    return build_page(await _outs(db, records), total, page_params)


@router.get("/api/events/summary", response_model=EventSummaryOut)
async def events_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
) -> EventSummaryOut:
    """~10 ta agregat — har ochiq Hodisalar varag'i har jonli hodisada so'raydi.

    Bino doirasi yo'q foydalanuvchilar uchun kesh UMUMIY (ilgari har operator
    alohida — N operator N marta to'liq sanardi); faqat shaxsiy "menga
    tayinlangan" soni har so'rovda alohida, kichik so'rov bilan. Doirasi
    borlarga — o'z keshi."""
    from app.services import situation as svc

    if is_restricted(current_user):
        return await svc.cached(("events_summary", current_user.id), lambda: _events_summary(db, current_user))
    shared = await svc.cached(("events_summary", "hammasi"), lambda: _events_summary(db, current_user))
    mine = await db.scalar(
        select(func.count())
        .select_from(Event)
        .where(OPERATOR_EVENTS)
        .where(Event.status.in_(ACTIVE_STATUSES), Event.assigned_to_id == uuid.UUID(current_user.id))
    )
    return shared.model_copy(update={"assigned_to_me": int(mine or 0)})


async def _events_summary(db: AsyncSession, current_user: CurrentUser) -> EventSummaryOut:
    now = datetime.now(timezone.utc)
    # Bino doirasi bor foydalanuvchi sanoqlarda ham faqat o'z binolarini ko'radi.
    scope = event_filter(current_user)
    status_counts = dict(
        (await db.execute(select(Event.status, func.count()).where(OPERATOR_EVENTS, scope).group_by(Event.status))).all()
    )
    # "Qaror kutayotgan" = yangi + jarayonda (ko'rib chiqish navbati).
    unreviewed_by_severity = dict(
        (
            await db.execute(
                select(Event.severity, func.count())
                .where(OPERATOR_EVENTS, scope)
                .where(Event.status.in_(OPEN_STATUSES))
                .group_by(Event.severity)
            )
        ).all()
    )
    start_of_today = day_start(business_today())
    today_row = (
        await db.execute(
            select(func.count(), func.count().filter(Event.severity.in_(SERIOUS)))
            .where(OPERATOR_EVENTS, scope)
            .where(Event.occurred_at >= start_of_today)
        )
    ).one()
    oldest = await db.scalar(
        select(func.min(Event.occurred_at)).where(OPERATOR_EVENTS, scope).where(Event.status.in_(OPEN_STATUSES))
    )
    stale_serious = (
        await db.scalar(
            select(func.count())
            .select_from(Event)
            .where(OPERATOR_EVENTS, scope)
            .where(Event.status.in_(OPEN_STATUSES))
            .where(Event.severity.in_(SERIOUS))
            .where(Event.occurred_at < now - timedelta(hours=24))
        )
        or 0
    )
    me = uuid.UUID(current_user.id)
    workflow_row = (
        await db.execute(
            select(
                func.count().filter(Event.status.in_(OPEN_STATUSES), Event.due_at < now),
                func.count().filter(Event.status.in_(ACTIVE_STATUSES), Event.assigned_to_id == me),
                func.count().filter(Event.status.in_(OPEN_STATUSES), Event.assigned_to_id.is_(None)),
            ).where(OPERATOR_EVENTS, scope)
        )
    ).one()

    since = now - timedelta(days=REVIEW_STATS_DAYS)
    reviewed_recently = Event.reviewed_at >= since
    review_row = (
        await db.execute(
            select(
                func.avg(func.extract("epoch", Event.reviewed_at - Event.occurred_at)),
                # Hal qilingan hodisa avval haqiqiy deb topilgan — tasdiqlangan hisoblanadi.
                func.count().filter(Event.status.in_(CONFIRMED_STATUSES)),
                func.count().filter(Event.status == "rad_etilgan"),
            )
            .where(OPERATOR_EVENTS, scope)
            .where(reviewed_recently)
        )
    ).one()
    avg_seconds, confirmed_recent, rejected_recent = review_row
    reviewed_total = confirmed_recent + rejected_recent

    module_rows = (
        await db.execute(
            select(Event.module_code, Event.module_name, func.count())
            .where(OPERATOR_EVENTS, scope)
            .group_by(Event.module_code, Event.module_name)
            .order_by(func.count().desc())
            .limit(FACET_LIMIT)
        )
    ).all()
    building_rows = (
        await db.execute(
            select(Event.building, func.count())
            .where(OPERATOR_EVENTS, scope)
            .where(Event.building != "")
            .group_by(Event.building)
            .order_by(Event.building)
            .limit(FACET_LIMIT)
        )
    ).all()
    trial_rows = (
        await db.execute(
            select(Event.module_code, Event.module_name, func.count())
            .where(Event.is_trial == true())
            .where(REGISTERED_MODULE)
            .where(scope)
            .where(Event.status == "yangi")
            .group_by(Event.module_code, Event.module_name)
            .order_by(func.count().desc())
            .limit(FACET_LIMIT)
        )
    ).all()

    return EventSummaryOut(
        total=sum(status_counts.values()),
        unreviewed=status_counts.get("yangi", 0),
        in_progress=status_counts.get("jarayonda", 0),
        confirmed=status_counts.get("tasdiqlangan", 0),
        rejected=status_counts.get("rad_etilgan", 0),
        resolved=status_counts.get("hal_qilindi", 0),
        unreviewed_high=unreviewed_by_severity.get("yuqori", 0),
        unreviewed_medium=unreviewed_by_severity.get("o'rta", 0),
        unreviewed_low=unreviewed_by_severity.get("past", 0),
        today=today_row[0],
        today_serious=today_row[1],
        stale_serious_unreviewed=stale_serious,
        oldest_unreviewed_hours=round((now - oldest).total_seconds() / 3600, 1) if oldest else None,
        avg_review_minutes=round(float(avg_seconds) / 60, 1) if avg_seconds is not None else None,
        recent_precision=(
            round(confirmed_recent * 100 / reviewed_total, 1) if reviewed_total >= MIN_REVIEWS_FOR_PRECISION else None
        ),
        overdue=workflow_row[0],
        assigned_to_me=workflow_row[1],
        unassigned=workflow_row[2],
        modules=[EventFacetOut(value=str(code), label=name, count=count) for code, name, count in module_rows],
        buildings=[EventFacetOut(value=name, label=name, count=count) for name, count in building_rows],
        trial_unreviewed=sum(count for _code, _name, count in trial_rows),
        trial_modules=[EventFacetOut(value=str(code), label=name, count=count) for code, name, count in trial_rows],
    )


@router.get("/api/events/export.pdf")
async def export_events_pdf(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
    # Ismlar bilan 2000 tagacha hodisa — eksport huquqi (tugma ham shunga bog'liq).
    _export: Annotated[CurrentUser, Depends(require_permission("exportData"))],
    severity: Annotated[str | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    module_codes: Annotated[str | None, Query(alias="moduleCodes")] = None,
    building: Annotated[str | None, Query(max_length=200)] = None,
    camera_id: Annotated[str | None, Query(alias="cameraId")] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    sort: Annotated[Literal["newest", "oldest", "severity", "due"], Query()] = "newest",
    assigned_to: Annotated[str | None, Query(alias="assignedTo", max_length=64)] = None,
    overdue: Annotated[bool, Query()] = False,
) -> Response:
    """Hodisalar jurnali PDF — ekrandagi filtr bilan (ko'pi bilan 2000 qator)."""
    from app.services import pdf_export

    filters = dict(
        severity=severity, status_filter=status_filter, search=search, today=False, exclude_modules=None,
        hide_rejected=False, module_codes=module_codes, building=building, camera_id=camera_id,
        date_from=date_from, date_to=date_to, sort=sort, trial=False, exclude_suppressed=False,
        assigned_to=assigned_to, overdue=overdue,
    )
    items: list[EventOut] = []
    total = 0
    for page_no in range(1, 5):
        params = PageParams(page=page_no, page_size=500)
        result = await list_events(db=db, current_user=current_user, page_params=params, **filters)
        items.extend(result.items)
        total = result.total
        if page_no >= result.total_pages:
            break
    status_labels = {
        "yangi": "Yangi", "jarayonda": "Jarayonda", "tasdiqlangan": "Tasdiqlangan",
        "hal_qilindi": "Hal qilindi", "rad_etilgan": "Rad etilgan",
    }
    rows = [
        [e.timestamp, e.module_name, e.person_name or "—", e.camera_name or "—", e.building or "—",
         f"{e.confidence}%", e.severity, status_labels.get(e.status, e.status), e.assigned_to_name or "—"]
        for e in items
    ]
    tones = {i: "danger" for i, e in enumerate(items) if e.severity == "yuqori" and e.status in OPEN_STATUSES}
    applied = [
        (label, value) for label, value in (
            ("Muhimlik", severity), ("Holat", status_filter), ("Qidiruv", search), ("Bino", building),
            ("Sanadan", date_from.isoformat() if date_from else None), ("Sanagacha", date_to.isoformat() if date_to else None),
            ("Muddati o'tgan", "ha" if overdue else None),
        ) if value
    ]
    document = pdf_export.PdfDocument(
        title="Hodisalar jurnali",
        columns=[
            pdf_export.PdfColumn("Vaqt", 1.3), pdf_export.PdfColumn("Kriteriya", 2), pdf_export.PdfColumn("Shaxs", 1.6),
            pdf_export.PdfColumn("Kamera", 1.6), pdf_export.PdfColumn("Bino", 1.2), pdf_export.PdfColumn("Ishonch", 0.7, "RIGHT"),
            pdf_export.PdfColumn("Muhimlik", 0.8), pdf_export.PdfColumn("Holat", 1), pdf_export.PdfColumn("Mas'ul", 1.3),
        ],
        rows=rows, row_tones=tones, filters=applied,
        counts=[("Jami", total), ("Faylda", len(rows))],
        note=None if total <= len(rows) else f"Faylga birinchi {len(rows)} ta yozuv tushdi — sana oralig'ini toraytiring.",
    )
    return Response(
        content=await pdf_export.render_async(document), media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="hodisalar.pdf"'},
    )


@router.get("/api/events/assignees", response_model=list[EventAssigneeOut])
async def list_assignees(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: ReviewDep,
) -> list[EventAssigneeOut]:
    """Tayinlash ro'yxati: hodisalarni ko'rib chiqish huquqi bor rollardagi
    foydalanuvchilar (huquq matritsasi o'zgarsa, ro'yxat ham o'zgaradi)."""
    roles = [role for role in ROLE_LABELS if await has_any_permission(db, role, (REVIEW_PERMISSION,))]
    if not roles:
        return []
    users = (await db.execute(select(User).where(User.role.in_(roles)).order_by(User.full_name))).scalars().all()
    return [EventAssigneeOut(id=str(u.id), full_name=u.full_name, role=role_display_label(u.role)) for u in users]


@router.post("/api/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def create_event(
    body: EventCreateIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("configureAi"))],
) -> EventOut:
    result = await db.execute(select(Camera).options(selectinload(Camera.building)).where(Camera.id == body.camera_id))
    camera = result.scalar_one_or_none()
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi")

    event = Event(
        camera_id=camera.id,
        camera_name=camera.name,
        building=camera.building.name if camera.building else "",
        module_code=body.module_code,
        module_name=body.module_name,
        group=body.group,
        confidence=body.confidence,
        severity=body.severity,
        person_name=body.person_name,
        status="yangi",
        due_at=sla_due_at(body.severity, datetime.now(timezone.utc)),
    )
    db.add(event)
    await log_action(db, request, current_user.id, f"Yangi AI hodisa: {body.module_name}", AUDIT_MODULE)
    await db.commit()
    await db.refresh(event)

    out = _to_out(event, comments_count=0)
    await manager.broadcast(out.model_dump(by_alias=True))
    return out


@router.post("/api/events/review-bulk", response_model=EventBulkReviewOut)
async def review_events_bulk(
    body: EventBulkReviewIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
) -> EventBulkReviewOut:
    """Bir nechta hodisani bitta tranzaksiyada tasdiqlash, rad etish yoki
    hal qilingan deb yopish (umumiy yechim izohi bilan).

    Holat o'tish qoidasiga to'g'ri kelmaydigan (masalan yolg'on signalni
    "hal qilindi" qilish) yoki allaqachon shu holatdagi hodisalar
    o'tkazib yuboriladi va "skipped" ga qo'shiladi.

    WebSocket'ga bitta yig'ma xabar ketadi ({"kind": "events_reviewed"}),
    har hodisa uchun alohida emas: 200 ta xabar har bir ochiq sahifani
    200 marta qayta yuklatardi."""
    try:
        ids = [uuid.UUID(raw) for raw in dict.fromkeys(body.ids)]
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Noto'g'ri hodisa identifikatori") from None
    note = _clean_note(body.note)
    if body.status == "hal_qilindi" and note is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Hal qilish uchun yechim izohi majburiy")

    actor_id = uuid.UUID(current_user.id)
    reviewer_name = await _actor_name(db, current_user)
    now = datetime.now(timezone.utc)
    events = (
        (
            await db.execute(
                select(Event)
                .where(Event.id.in_(ids))
                .where(event_filter(current_user))
                .order_by(Event.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    updated_ids: list[str] = []
    for event in events:
        if event.status == body.status or not can_transition(event.status, body.status):
            continue
        if body.status == "hal_qilindi" and event.is_trial:
            continue
        text = _apply_status(
            event,
            body.status,
            actor_id=actor_id,
            actor_name=reviewer_name,
            note=note if body.status == "hal_qilindi" else None,
            now=now,
        )
        db.add(EventComment(event_id=event.id, author_id=actor_id, author_name=reviewer_name, kind="holat", body=text))
        updated_ids.append(str(event.id))

    await log_action(
        db,
        request,
        current_user.id,
        f"Hodisalarni ommaviy ko'rib chiqdi: {len(updated_ids)} ta — {body.status}",
        AUDIT_MODULE,
    )
    await db.commit()

    if updated_ids:
        await manager.broadcast(
            {"kind": "events_reviewed", "ids": updated_ids, "status": body.status, "reviewedBy": reviewer_name}
        )
    return EventBulkReviewOut(updated=len(updated_ids), skipped=len(ids) - len(updated_ids), status=body.status)


@router.get("/api/events/{event_id}", response_model=EventOut)
async def get_event(
    event_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
) -> EventOut:
    return await _out(db, await _get_event(db, event_id, current_user))


@router.delete("/api/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("deleteEvents"))],
) -> None:
    event = await _get_event(db, event_id, current_user)
    snapshot_key = event.snapshot_key
    await log_action(db, request, current_user.id, f"Hodisani o'chirdi: {event.module_name}", AUDIT_MODULE)
    await db.delete(event)
    await db.commit()
    # The row is the source of truth; its snapshot in object storage is
    # derived data that nothing can reach once the row is gone. Deleting
    # it here (best-effort, after the commit) is what keeps MinIO from
    # accumulating unreachable JPEGs forever — see delete_files_quietly.
    await delete_files_quietly([snapshot_key])


@router.patch("/api/events/{event_id}/review", response_model=EventOut)
async def review_event(
    event_id: str,
    body: EventReviewIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
) -> EventOut:
    """Tezkor qaror: tasdiqlash yoki rad etish (navbat kartalari, devor,
    sinov namunalari). Har qanday holatdan ruxsat — qarorni o'zgartirish
    ham shu yerdan; holat o'zgarsa tarixga yoziladi."""
    event = await _get_event(db, event_id, current_user, for_update=True)
    actor_id = uuid.UUID(current_user.id)
    actor_name = await _actor_name(db, current_user)
    previous = event.status
    text = _apply_status(event, body.status, actor_id=actor_id, actor_name=actor_name, note=None, now=datetime.now(timezone.utc))
    if previous != body.status:
        db.add(EventComment(event_id=event.id, author_id=actor_id, author_name=actor_name, kind="holat", body=text))

    await log_action(db, request, current_user.id, f"Hodisani ko'rib chiqdi: {body.status}", AUDIT_MODULE)
    await db.commit()
    await db.refresh(event)

    out = await _out(db, event)
    await _broadcast_update(event, out)
    return out


@router.post("/api/events/{event_id}/status", response_model=EventOut)
async def change_event_status(
    event_id: str,
    body: EventStatusIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
) -> EventOut:
    """Ish jarayoni bo'yicha holat o'zgarishi (app/services/event_status.py
    TRANSITIONS). "hal_qilindi" uchun yechim izohi majburiy."""
    event = await _get_event(db, event_id, current_user, for_update=True)
    if event.is_trial:
        raise HTTPException(status.HTTP_409_CONFLICT, "Sinov signali ish jarayoniga kirmaydi — faqat baholanadi")
    note = _clean_note(body.note)
    if body.status == event.status:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Hodisa allaqachon \"{STATUS_LABELS[event.status]}\" holatida")
    if not can_transition(event.status, body.status):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"\"{STATUS_LABELS[event.status]}\" holatidan \"{STATUS_LABELS[body.status]}\" ga o'tib bo'lmaydi",
        )
    if body.status == "hal_qilindi" and note is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Hal qilish uchun yechim izohi majburiy")

    actor_id = uuid.UUID(current_user.id)
    actor_name = await _actor_name(db, current_user)
    previous = event.status
    text = _apply_status(event, body.status, actor_id=actor_id, actor_name=actor_name, note=note, now=datetime.now(timezone.utc))
    db.add(EventComment(event_id=event.id, author_id=actor_id, author_name=actor_name, kind="holat", body=text))
    await log_action(
        db,
        request,
        current_user.id,
        f"Hodisa holati: {STATUS_LABELS[previous]} → {STATUS_LABELS[body.status]} ({event.module_name})",
        AUDIT_MODULE,
    )
    await db.commit()
    await db.refresh(event)

    out = await _out(db, event)
    await _broadcast_update(event, out)
    return out


@router.post("/api/events/{event_id}/assign", response_model=EventOut)
async def assign_event(
    event_id: str,
    body: EventAssignIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
) -> EventOut:
    """Hodisani operatorga tayinlash (userId: null — tayinlovni olib
    tashlash). Yangi hodisa tayinlanganda "jarayonda" ga o'tadi va
    tayinlangan foydalanuvchiga shaxsiy bildirishnoma yuboriladi."""
    event = await _get_event(db, event_id, current_user, for_update=True)
    if event.is_trial:
        raise HTTPException(status.HTTP_409_CONFLICT, "Sinov signali ish jarayoniga kirmaydi — faqat baholanadi")
    if event.status in ("rad_etilgan", "hal_qilindi"):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"\"{STATUS_LABELS[event.status]}\" hodisani tayinlab bo'lmaydi — avval qayta oching"
        )

    assignee: User | None = None
    if body.user_id is not None:
        # "me" — o'zimga olish (frontend joriy foydalanuvchi identifikatorini bilmaydi).
        raw_id = current_user.id if body.user_id == "me" else body.user_id
        assignee = await db.get(User, _parse_uuid(raw_id, "Noto'g'ri foydalanuvchi identifikatori"))
        if assignee is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Foydalanuvchi topilmadi")
        if not await has_any_permission(db, assignee.role, (REVIEW_PERMISSION,)):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Bu foydalanuvchida hodisalarni ko'rib chiqish huquqi yo'q"
            )

    new_id = assignee.id if assignee else None
    if new_id == event.assigned_to_id:
        return await _out(db, event)

    actor_id = uuid.UUID(current_user.id)
    actor_name = await _actor_name(db, current_user)
    now = datetime.now(timezone.utc)
    previous_names = await _user_names(db, {event.assigned_to_id} if event.assigned_to_id else set())
    previous_name = previous_names.get(event.assigned_to_id) if event.assigned_to_id else None

    event.assigned_to_id = new_id
    event.assigned_at = now if new_id else None
    moved_to_progress = assignee is not None and event.status == "yangi"
    if moved_to_progress:
        event.status = "jarayonda"

    if assignee is not None:
        text = f"Tayinlandi: {assignee.full_name}"
        if previous_name:
            text += f" (avval: {previous_name})"
        if moved_to_progress:
            text += f". Holat: {STATUS_LABELS['yangi']} → {STATUS_LABELS['jarayonda']}"
    else:
        text = f"Tayinlov olib tashlandi (avval: {previous_name})" if previous_name else "Tayinlov olib tashlandi"
    db.add(EventComment(event_id=event.id, author_id=actor_id, author_name=actor_name, kind="tayinlash", body=text))
    await log_action(
        db,
        request,
        current_user.id,
        f"Hodisani tayinladi: {event.module_name} — {assignee.full_name if assignee else 'hech kim'}",
        AUDIT_MODULE,
    )
    await db.commit()
    await db.refresh(event)

    if assignee is not None and str(assignee.id) != current_user.id:
        due = f" Muddat: {to_local(event.due_at).strftime('%H:%M')}." if event.due_at else ""
        message = (
            f"Sizga hodisa tayinlandi: {event.module_name} — {event.camera_name}"
            f"{', ' + event.building if event.building else ''} "
            f"(muhimlik: {event.severity}).{due} Tayinladi: {actor_name}."
        )
        try:
            await notify_user(assignee.id, message, kind="system", ref_id=str(event.id))
        except Exception:
            # Bildirishnoma yetib bormagani tayinlovni bekor qilmaydi.
            logger.exception("event assignment notification failed")

    out = await _out(db, event)
    await _broadcast_update(event, out)
    return out


@router.get("/api/events/{event_id}/comments", response_model=list[EventCommentOut])
async def list_comments(
    event_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
) -> list[EventCommentOut]:
    event = await _get_event(db, event_id, current_user)
    comments = (
        (
            await db.execute(
                select(EventComment)
                .where(EventComment.event_id == event.id)
                .order_by(EventComment.created_at, EventComment.id)
            )
        )
        .scalars()
        .all()
    )
    return [_comment_out(c) for c in comments]


def _comment_out(comment: EventComment) -> EventCommentOut:
    return EventCommentOut(
        id=str(comment.id),
        kind=comment.kind,
        body=comment.body,
        author_id=str(comment.author_id) if comment.author_id else None,
        author_name=comment.author_name,
        created_at=_iso(comment.created_at),
    )


@router.post("/api/events/{event_id}/comments", response_model=EventCommentOut, status_code=status.HTTP_201_CREATED)
async def add_comment(
    event_id: str,
    body: EventCommentIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
) -> EventCommentOut:
    text = body.body.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Izoh bo'sh bo'lmasligi kerak")
    event = await _get_event(db, event_id, current_user)
    comment = EventComment(
        event_id=event.id,
        author_id=uuid.UUID(current_user.id),
        author_name=await _actor_name(db, current_user),
        kind="izoh",
        body=text,
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    # Boshqa operatorlar panelidagi izohlar soni va tarix yangilanadi.
    await _broadcast_update(event, await _out(db, event))
    return _comment_out(comment)


@router.get("/api/events/{event_id}/timeline", response_model=list[EventTimelineItemOut])
async def event_timeline(
    event_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReviewDep,
) -> list[EventTimelineItemOut]:
    """Hodisa tarixi vaqt bo'yicha: yaratilish, izohlar, holat va tayinlash
    o'zgarishlari, muddat o'tgani haqidagi ogohlantirish.

    Ish jarayonidan oldin ko'rib chiqilgan hodisalarda holat yozuvi yo'q —
    ular uchun qaror reviewed_by/reviewed_at dan tiklanadi."""
    event = await _get_event(db, event_id, current_user)
    comments = (
        (await db.execute(select(EventComment).where(EventComment.event_id == event.id))).scalars().all()
    )
    items: list[tuple[datetime, EventTimelineItemOut]] = [
        (
            event.occurred_at,
            EventTimelineItemOut(
                id=f"created-{event.id}",
                kind="yaratildi",
                at=_iso(event.occurred_at),
                author_name=None,
                body=f"{event.module_name} signali — {event.camera_name}, ishonch {event.confidence}%",
            ),
        )
    ]
    for c in comments:
        items.append(
            (
                c.created_at,
                EventTimelineItemOut(
                    id=str(c.id), kind=c.kind, at=_iso(c.created_at), author_name=c.author_name, body=c.body
                ),
            )
        )
    if event.reviewed_at and not any(c.kind == "holat" for c in comments):
        items.append(
            (
                event.reviewed_at,
                EventTimelineItemOut(
                    id=f"reviewed-{event.id}",
                    kind="holat",
                    at=_iso(event.reviewed_at),
                    author_name=event.reviewed_by,
                    body=f"{STATUS_LABELS['yangi']} → {STATUS_LABELS.get(event.status, event.status)}",
                ),
            )
        )
    if event.escalated_at:
        items.append(
            (
                event.escalated_at,
                EventTimelineItemOut(
                    id=f"escalated-{event.id}",
                    kind="muddat",
                    at=_iso(event.escalated_at),
                    author_name=None,
                    body="Hal qilish muddati o'tdi — mas'ullarga ogohlantirish yuborildi",
                ),
            )
        )
    items.sort(key=lambda pair: pair[0])
    return [item for _at, item in items]
