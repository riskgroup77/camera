"""Turniket/kirish nazorati qurilmalari, hodisalar jurnali, webhook."""

import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.audit import log_action
from app.config import settings
from app.crypto import decrypt, encrypt
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.models import AccessDevice, AccessEvent, Building, StudentStaff
from app.pagination import Page, PageParams, build_page, paginate
from app.rate_limit import limiter
from app.schemas.integrations import (
    AccessDeviceCreatedOut,
    AccessDeviceCreateIn,
    AccessDeviceOut,
    AccessDeviceUpdateIn,
    AccessEventOut,
    AccessSummaryOut,
    ApiKeyOut,
    DeviceTestOut,
    UnmatchedCredentialOut,
    WebhookResultOut,
)
from app.services.integrations.access_control import (
    NormalizedEvent,
    generate_api_key,
    hash_api_key,
    ingest_many,
    normalize_webhook_event,
    parse_zkteco_attlog,
    verify_api_key,
)
from app.services.integrations.hikvision_acs import DeviceError, fetch_device_info
from app.timezone import INSTITUTE_TZ, to_local
from app.timezone import business_today, day_start

router = APIRouter(tags=["access-control"])

ManageDep = Annotated[CurrentUser, Depends(require_permission("manageIntegrations"))]
DbDep = Annotated[AsyncSession, Depends(get_db)]
MODULE = "Turniketlar"
PUSH_KINDS = ("webhook", "zkteco")
MAX_WEBHOOK_BODY_BYTES = 1_000_000
MAX_WEBHOOK_EVENTS = 1000
# Webhook qurilmasi shuncha vaqt jim tursa "oflayn" ko'rinadi.
PUSH_DEVICE_QUIET_AFTER = timedelta(hours=24)


def _iso(moment: datetime | None) -> str | None:
    return to_local(moment).isoformat(timespec="seconds") if moment else None


def webhook_path(device_id: uuid.UUID | str) -> str:
    return f"/api/access/webhook/{device_id}"


def device_status(device: AccessDevice, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if not device.enabled:
        return "ochirilgan"
    if device.kind == "hikvision":
        if device.last_error:
            return "xato"
        if device.last_poll_at is None:
            return "kutilmoqda"
        fresh = timedelta(seconds=max(60, settings.access_poll_interval_seconds * 3))
        return "onlayn" if now - device.last_poll_at <= fresh else "oflayn"
    if device.last_event_at is None:
        return "kutilmoqda"
    return "onlayn" if now - device.last_event_at <= PUSH_DEVICE_QUIET_AFTER else "oflayn"


def _username(device: AccessDevice) -> str | None:
    if not device.username:
        return None
    try:
        return decrypt(device.username)
    except ValueError:
        return None


def device_to_out(device: AccessDevice, building_name: str | None = None) -> AccessDeviceOut:
    return AccessDeviceOut(
        id=str(device.id),
        name=device.name,
        kind=device.kind,
        ip=device.ip,
        port=device.port,
        username=_username(device),
        has_password=bool(device.password),
        has_api_key=bool(device.api_key_hash),
        direction=device.direction,
        building_id=str(device.building_id) if device.building_id else None,
        building_name=building_name,
        marks_attendance=device.marks_attendance,
        enabled=device.enabled,
        status=device_status(device),
        last_event_at=_iso(device.last_event_at),
        last_poll_at=_iso(device.last_poll_at),
        last_error=device.last_error,
        webhook_path=webhook_path(device.id) if device.kind in PUSH_KINDS else None,
        created_at=_iso(device.created_at),
    )


async def _building_name(db: AsyncSession, building_id: uuid.UUID | None) -> str | None:
    if building_id is None:
        return None
    building = await db.get(Building, building_id)
    return building.name if building else None


async def _parse_building(db: AsyncSession, value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        building_id = uuid.UUID(value)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Noto'g'ri bino identifikatori") from None
    if await db.get(Building, building_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bino topilmadi")
    return building_id


async def _get_device(db: AsyncSession, device_id: uuid.UUID) -> AccessDevice:
    device = await db.get(AccessDevice, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Qurilma topilmadi")
    return device


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


# ── Qurilmalar ──────────────────────────────────────────────────────────────


@router.get("/api/access/devices", response_model=list[AccessDeviceOut])
async def list_devices(db: DbDep, _: ManageDep) -> list[AccessDeviceOut]:
    rows = (
        await db.execute(
            select(AccessDevice, Building.name)
            .outerjoin(Building, Building.id == AccessDevice.building_id)
            .order_by(AccessDevice.name)
        )
    ).all()
    return [device_to_out(device, building_name) for device, building_name in rows]


@router.post("/api/access/devices", response_model=AccessDeviceCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_device(
    request: Request, body: AccessDeviceCreateIn, db: DbDep, current_user: ManageDep
) -> AccessDeviceCreatedOut:
    ip = _clean(body.ip)
    username = _clean(body.username)
    if body.kind == "hikvision":
        if not ip:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Hikvision qurilmasi uchun IP manzil kerak")
        if not username or not body.password:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Hikvision qurilmasi uchun login va parol kerak")
    device = AccessDevice(
        name=body.name.strip(),
        kind=body.kind,
        ip=ip,
        port=body.port,
        username=encrypt(username) if username else None,
        password=encrypt(body.password) if body.password else None,
        direction=body.direction,
        building_id=await _parse_building(db, body.building_id),
        marks_attendance=body.marks_attendance,
        enabled=body.enabled,
    )
    api_key = None
    if body.kind in PUSH_KINDS:
        api_key = generate_api_key()
        device.api_key_hash = hash_api_key(api_key)
    db.add(device)
    await db.flush()
    await log_action(db, request, current_user.id, f"Turniket qurilmasi qo'shildi: {device.name} ({device.kind})", MODULE)
    await db.commit()
    await db.refresh(device)
    out = device_to_out(device, await _building_name(db, device.building_id))
    return AccessDeviceCreatedOut(**out.model_dump(), api_key=api_key)


@router.patch("/api/access/devices/{device_id}", response_model=AccessDeviceOut)
async def update_device(
    device_id: uuid.UUID, request: Request, body: AccessDeviceUpdateIn, db: DbDep, current_user: ManageDep
) -> AccessDeviceOut:
    device = await _get_device(db, device_id)
    fields = body.model_fields_set
    if "name" in fields and body.name is not None:
        device.name = body.name.strip()
    if "ip" in fields:
        device.ip = _clean(body.ip)
    if "port" in fields:
        device.port = body.port
    if "username" in fields:
        username = _clean(body.username)
        device.username = encrypt(username) if username else None
    if "password" in fields and body.password is not None:
        device.password = encrypt(body.password) if body.password else None
    if "direction" in fields and body.direction is not None:
        device.direction = body.direction
    if "building_id" in fields:
        device.building_id = await _parse_building(db, body.building_id)
    if "marks_attendance" in fields and body.marks_attendance is not None:
        device.marks_attendance = body.marks_attendance
    if "enabled" in fields and body.enabled is not None:
        device.enabled = body.enabled
    if device.kind == "hikvision" and not device.ip:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Hikvision qurilmasi uchun IP manzil kerak")
    if {"ip", "port", "username", "password"} & fields:
        # Yangi ulanish ma'lumoti — eski xato endi tegishli emas.
        device.last_error = None
    await log_action(db, request, current_user.id, f"Turniket qurilmasi tahrirlandi: {device.name}", MODULE)
    await db.commit()
    await db.refresh(device)
    return device_to_out(device, await _building_name(db, device.building_id))


@router.delete("/api/access/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(device_id: uuid.UUID, request: Request, db: DbDep, current_user: ManageDep) -> Response:
    device = await _get_device(db, device_id)
    name = device.name
    # Hodisalar jurnali qoladi (device_id -> NULL): davomatning isboti.
    await db.delete(device)
    await log_action(db, request, current_user.id, f"Turniket qurilmasi o'chirildi: {name}", MODULE)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/access/devices/{device_id}/rotate-key", response_model=ApiKeyOut)
async def rotate_key(device_id: uuid.UUID, request: Request, db: DbDep, current_user: ManageDep) -> ApiKeyOut:
    device = await _get_device(db, device_id)
    if device.kind not in PUSH_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "API kalit faqat webhook/ZKTeco qurilmalari uchun")
    api_key = generate_api_key()
    device.api_key_hash = hash_api_key(api_key)
    await log_action(db, request, current_user.id, f"Turniket API kaliti almashtirildi: {device.name}", MODULE)
    await db.commit()
    return ApiKeyOut(api_key=api_key, webhook_path=webhook_path(device.id))


@router.post("/api/access/devices/{device_id}/test", response_model=DeviceTestOut)
async def test_device(device_id: uuid.UUID, db: DbDep, _: ManageDep) -> DeviceTestOut:
    device = await _get_device(db, device_id)
    if device.kind != "hikvision":
        if device.last_event_at is None:
            return DeviceTestOut(ok=False, message="Qurilmadan hali birorta hodisa kelmagan — webhook sozlamasini tekshiring")
        return DeviceTestOut(
            ok=True,
            message=f"Oxirgi hodisa: {to_local(device.last_event_at).strftime('%Y-%m-%d %H:%M:%S')}",
        )
    try:
        info = await fetch_device_info(device)
    except DeviceError as exc:
        return DeviceTestOut(ok=False, message=str(exc))
    label = " ".join(v for v in (info.get("model"), info.get("serialNumber")) if v)
    return DeviceTestOut(ok=True, message=f"Ulanish muvaffaqiyatli{': ' + label if label else ''}", info=info)


# ── Hodisalar ───────────────────────────────────────────────────────────────


def _local_day_start(day: date) -> datetime:
    return day_start(day)


@router.get("/api/access/events", response_model=Page[AccessEventOut])
async def list_events(
    db: DbDep,
    _: ManageDep,
    page_params: Annotated[PageParams, Depends()],
    device_id: Annotated[uuid.UUID | None, Query(alias="deviceId")] = None,
    person_id: Annotated[uuid.UUID | None, Query(alias="personId")] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    granted: Annotated[bool | None, Query()] = None,
    matched: Annotated[bool | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    direction: Annotated[Literal["kirish", "chiqish"] | None, Query()] = None,
) -> Page[AccessEventOut]:
    stmt = select(AccessEvent)
    if device_id:
        stmt = stmt.where(AccessEvent.device_id == device_id)
    if direction:
        stmt = stmt.where(AccessEvent.direction == direction)
    if person_id:
        stmt = stmt.where(AccessEvent.student_staff_id == person_id)
    if date_from:
        stmt = stmt.where(AccessEvent.occurred_at >= _local_day_start(date_from))
    if date_to:
        stmt = stmt.where(AccessEvent.occurred_at < _local_day_start(date_to + timedelta(days=1)))
    if granted is not None:
        stmt = stmt.where(AccessEvent.granted.is_(granted))
    if matched is not None:
        stmt = stmt.where(
            AccessEvent.student_staff_id.is_not(None) if matched else AccessEvent.student_staff_id.is_(None)
        )
    if search and search.strip():
        term = f"%{search.strip()}%"
        stmt = stmt.outerjoin(StudentStaff, StudentStaff.id == AccessEvent.student_staff_id).where(
            or_(
                AccessEvent.card_number.ilike(term),
                AccessEvent.employee_no.ilike(term),
                StudentStaff.full_name.ilike(term),
            )
        )
    stmt = stmt.order_by(AccessEvent.occurred_at.desc())
    rows, total = await paginate(db, stmt, page_params)

    person_ids = {r.student_staff_id for r in rows if r.student_staff_id}
    device_ids = {r.device_id for r in rows if r.device_id}
    people = (
        {
            p.id: p
            for p in (
                await db.execute(
                    select(StudentStaff)
                    .options(defer(StudentStaff.biometric_embedding))
                    .where(StudentStaff.id.in_(person_ids))
                )
            ).scalars()
        }
        if person_ids
        else {}
    )
    devices = (
        {
            d.id: d.name
            for d in (await db.execute(select(AccessDevice).where(AccessDevice.id.in_(device_ids)))).scalars()
        }
        if device_ids
        else {}
    )
    items = []
    for event in rows:
        person = people.get(event.student_staff_id) if event.student_staff_id else None
        items.append(
            AccessEventOut(
                id=str(event.id),
                device_id=str(event.device_id) if event.device_id else None,
                device_name=devices.get(event.device_id) if event.device_id else None,
                occurred_at=_iso(event.occurred_at) or "",
                card_number=event.card_number,
                employee_no=event.employee_no,
                person_id=str(person.id) if person else None,
                person_name=person.full_name if person else None,
                person_type=person.type if person else None,
                person_unit=person.group_or_position if person else None,
                direction=event.direction,
                granted=event.granted,
            )
        )
    return build_page(items, total, page_params)


@router.get("/api/access/summary", response_model=AccessSummaryOut)
async def events_summary(
    db: DbDep,
    _: ManageDep,
    day: Annotated[date | None, Query(alias="date")] = None,
    device_id: Annotated[uuid.UUID | None, Query(alias="deviceId")] = None,
) -> AccessSummaryOut:
    """Bir kunlik sanoq (turniketlar sahifasining yuqori qatori). Jurnal
    sahifalangan — undan hisoblab bo'lmaydi, shuning uchun alohida."""
    day = day or business_today()
    stmt = select(
        func.count().label("total"),
        func.count().filter(AccessEvent.direction == "kirish").label("entries"),
        func.count().filter(AccessEvent.direction == "chiqish").label("exits"),
        func.count().filter(AccessEvent.granted.is_(False)).label("denied"),
        func.count().filter(AccessEvent.student_staff_id.is_(None)).label("unmatched"),
        func.count(func.distinct(AccessEvent.student_staff_id)).label("people"),
    ).where(
        AccessEvent.occurred_at >= _local_day_start(day),
        AccessEvent.occurred_at < _local_day_start(day + timedelta(days=1)),
    )
    if device_id:
        stmt = stmt.where(AccessEvent.device_id == device_id)
    row = (await db.execute(stmt)).one()
    return AccessSummaryOut(
        date=day.isoformat(),
        total=row.total,
        entries=row.entries,
        exits=row.exits,
        denied=row.denied,
        unmatched=row.unmatched,
        people=row.people,
    )


@router.get("/api/access/unmatched", response_model=list[UnmatchedCredentialOut])
async def list_unmatched(
    db: DbDep,
    _: ManageDep,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[UnmatchedCredentialOut]:
    """Oxirgi kunlarda turniketda ko'ringan, lekin hech kimga tegishli
    bo'lmagan karta/xodim raqamlari — admin ularni odamga biriktiradi.
    Hodisadan keyin biriktirilgan raqamlar ro'yxatdan chiqariladi."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    last_seen = func.max(AccessEvent.occurred_at)
    grouped = (
        await db.execute(
            select(
                AccessEvent.card_number,
                AccessEvent.employee_no,
                func.count().label("count"),
                func.count().filter(AccessEvent.granted.is_(False)).label("denied"),
                func.min(AccessEvent.occurred_at).label("first_seen"),
                last_seen.label("last_seen"),
            )
            .where(AccessEvent.student_staff_id.is_(None))
            .where(AccessEvent.occurred_at >= since)
            .where(or_(AccessEvent.card_number.is_not(None), AccessEvent.employee_no.is_not(None)))
            .group_by(AccessEvent.card_number, AccessEvent.employee_no)
            .order_by(last_seen.desc())
            .limit(limit * 2)
        )
    ).all()
    if not grouped:
        return []

    cards = {row.card_number for row in grouped if row.card_number}
    stripped = {c.lstrip("0") for c in cards if c.lstrip("0")}
    employees = {row.employee_no for row in grouped if row.employee_no}
    known_cards: set[str] = set()
    known_employees: set[str] = set()
    conditions = []
    if cards:
        conditions += [StudentStaff.card_number.in_(cards), func.ltrim(StudentStaff.card_number, "0").in_(stripped or {""})]
    if employees:
        conditions += [StudentStaff.hemis_id.in_(employees), StudentStaff.pinfl.in_(employees)]
    for card, hemis_id, pinfl in (
        await db.execute(select(StudentStaff.card_number, StudentStaff.hemis_id, StudentStaff.pinfl).where(or_(*conditions)))
    ).all():
        if card:
            known_cards.update({card, card.lstrip("0")})
        known_employees.update(v for v in (hemis_id, pinfl) if v)

    # Har guruhning oxirgi qurilmasi — bitta so'rov bilan.
    latest_devices: dict[tuple, str | None] = {}
    device_rows = (
        await db.execute(
            select(AccessEvent.card_number, AccessEvent.employee_no, AccessDevice.name)
            .distinct(AccessEvent.card_number, AccessEvent.employee_no)
            .outerjoin(AccessDevice, AccessDevice.id == AccessEvent.device_id)
            .where(AccessEvent.student_staff_id.is_(None))
            .where(AccessEvent.occurred_at >= since)
            .order_by(AccessEvent.card_number, AccessEvent.employee_no, AccessEvent.occurred_at.desc())
        )
    ).all()
    for card, employee, device_name in device_rows:
        latest_devices[(card, employee)] = device_name

    out: list[UnmatchedCredentialOut] = []
    for row in grouped:
        if row.card_number and (row.card_number in known_cards or row.card_number.lstrip("0") in known_cards):
            continue
        if row.employee_no and row.employee_no in known_employees:
            continue
        out.append(
            UnmatchedCredentialOut(
                card_number=row.card_number,
                employee_no=row.employee_no,
                count=row.count,
                denied_count=row.denied,
                first_seen=_iso(row.first_seen) or "",
                last_seen=_iso(row.last_seen) or "",
                last_device_name=latest_devices.get((row.card_number, row.employee_no)),
            )
        )
        if len(out) >= limit:
            break
    return out


# ── Webhook (ochiq, API kalit bilan) ────────────────────────────────────────


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Qurilma yoki API kalit noto'g'ri")


def parse_webhook_body(raw: bytes, content_type: str) -> tuple[list[NormalizedEvent], list[dict]]:
    """(hodisalar, rad etilganlar). JSON: {"events": [...]}, ro'yxat yoki
    bitta hodisa; ZKTeco oraliq dasturlari "records"/"data"/"logs" ham
    ishlatadi. Matn (text/plain) — ZKTeco ATTLOG qatorlari."""
    text_body = raw.decode("utf-8-sig", errors="replace")
    if "json" not in content_type and not text_body.lstrip().startswith(("{", "[")):
        return parse_zkteco_attlog(text_body), []
    try:
        payload = json.loads(text_body)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "JSON o'qib bo'lmadi") from None
    if isinstance(payload, dict):
        items = None
        for key in ("events", "records", "data", "logs", "AttLog", "attlog"):
            if isinstance(payload.get(key), list):
                items = payload[key]
                break
        if items is None:
            items = [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Hodisalar ro'yxati kutilgan edi")
    if len(items) > MAX_WEBHOOK_EVENTS:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"Bir so'rovda ko'pi bilan {MAX_WEBHOOK_EVENTS} ta hodisa"
        )
    events: list[NormalizedEvent] = []
    rejected: list[dict] = []
    for index, item in enumerate(items):
        try:
            events.append(normalize_webhook_event(item))
        except ValueError as exc:
            rejected.append({"index": index, "error": str(exc)})
    return events, rejected


@router.post("/api/access/webhook/{device_id}", response_model=WebhookResultOut)
@limiter.limit("300/minute")
async def access_webhook(
    request: Request,
    device_id: str,
    db: DbDep,
    x_api_key: Annotated[str | None, Header(alias="X-Api-Key")] = None,
) -> WebhookResultOut:
    """Qurilma yoki oraliq dastur hodisalarni yuboradi. Foydalanuvchi
    tokeni emas — qurilmaning o'z API kaliti (X-Api-Key) bilan."""
    try:
        parsed_id = uuid.UUID(device_id)
    except ValueError:
        raise _unauthorized() from None
    device = await db.get(AccessDevice, parsed_id)
    # Kalit har holda tekshiriladi (qurilma yo'q bo'lsa ham) — javob vaqti
    # qurilma mavjudligini oshkor qilmasin.
    valid = verify_api_key(x_api_key, device.api_key_hash if device else hash_api_key("-"))
    if device is None or not valid or device.kind not in PUSH_KINDS:
        raise _unauthorized()
    if not device.enabled or not settings.access_control_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Qurilma o'chirilgan")

    # Content-Length AVVAL tekshiriladi: `await request.body()` butun tanani
    # xotiraga o'qiydi, ya'ni chegarani o'qishdan KEYIN tekshirish gigabaytli
    # so'rov bilan jarayonni xotiradan tushirishga to'sqinlik qilmasdi.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "So'rov juda katta")
    raw = b""
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_WEBHOOK_BODY_BYTES:
            # Content-Length yo'q (chunked) yoki yolg'on bo'lsa — oqim
            # chegaraga yetganda uziladi.
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "So'rov juda katta")
    events, rejected = parse_webhook_body(raw, request.headers.get("content-type", "").lower())
    counts = await ingest_many(db, device, events)
    return WebhookResultOut(**counts, rejected=rejected)
