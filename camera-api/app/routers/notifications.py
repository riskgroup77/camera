"""Bildirishnoma qoidalari, jurnal, Telegram bog'lash, sinov xabari."""

import secrets
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.config import settings
from app.database import get_db
from app.dependencies import CurrentUser, get_current_user, require_permission
from app.models import Building, NotificationLog, NotificationRule, StudentStaff, User
from app.pagination import Page, PageParams, build_page, paginate
from app.schemas.notifications import (
    MyNotificationsOut,
    NotificationLogOut,
    NotificationRuleCreateIn,
    NotificationRuleOut,
    NotificationRuleUpdateIn,
    NotificationStatusOut,
    NotificationTestIn,
    NotificationTestOut,
    TelegramLinkOut,
    clean_recipients,
)
from app.services.notifications import dispatcher, sms, telegram
from app.timezone import INSTITUTE_TZ, to_local
from app.timezone import day_start

router = APIRouter(tags=["notifications"])

ManageDep = Annotated[CurrentUser, Depends(require_permission("manageNotifications"))]
DbDep = Annotated[AsyncSession, Depends(get_db)]

AUDIT_MODULE = "Bildirishnomalar"


def _iso(moment: datetime | None) -> str:
    return to_local(moment).isoformat(timespec="seconds") if moment else ""


def _rule_out(rule: NotificationRule) -> NotificationRuleOut:
    return NotificationRuleOut(
        id=str(rule.id),
        name=rule.name,
        enabled=rule.enabled,
        channel=rule.channel,
        recipients=[str(r) for r in rule.recipients or []],
        kinds=list(rule.kinds or []),
        module_codes=[int(c) for c in rule.module_codes] if rule.module_codes else None,
        building_ids=[str(b) for b in rule.building_ids] if rule.building_ids else None,
        min_severity=rule.min_severity,
        created_at=_iso(rule.created_at),
    )


def _log_out(row: NotificationLog) -> NotificationLogOut:
    return NotificationLogOut(
        id=str(row.id),
        created_at=_iso(row.created_at),
        channel=row.channel,
        recipient=row.recipient,
        kind=row.kind,
        status=row.status,
        text=row.text,
        error=row.error,
        ref_id=row.ref_id,
    )


async def _check_buildings(db: AsyncSession, building_ids: list[str] | None) -> list[str] | None:
    if not building_ids:
        return None
    try:
        ids = [uuid.UUID(b) for b in building_ids]
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Bino identifikatori noto'g'ri") from None
    found = set((await db.execute(select(Building.id).where(Building.id.in_(ids)))).scalars().all())
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tanlangan bino topilmadi")
    return [str(i) for i in ids]


async def _load_rule(db: AsyncSession, rule_id: str) -> NotificationRule:
    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Qoida topilmadi") from None
    rule = await db.get(NotificationRule, rule_uuid)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Qoida topilmadi")
    return rule


# ---------------------------------------------------------------------------
# Qoidalar
# ---------------------------------------------------------------------------


@router.get("/api/notifications/rules", response_model=list[NotificationRuleOut])
async def list_rules(db: DbDep, _: ManageDep) -> list[NotificationRuleOut]:
    rows = (await db.execute(select(NotificationRule).order_by(NotificationRule.created_at))).scalars().all()
    return [_rule_out(r) for r in rows]


@router.post("/api/notifications/rules", response_model=NotificationRuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(body: NotificationRuleCreateIn, request: Request, db: DbDep, current_user: ManageDep) -> NotificationRuleOut:
    rule = NotificationRule(
        name=body.name.strip(),
        enabled=body.enabled,
        channel=body.channel,
        recipients=body.recipients,
        kinds=list(body.kinds),
        module_codes=body.module_codes,
        building_ids=await _check_buildings(db, body.building_ids),
        min_severity=body.min_severity,
    )
    db.add(rule)
    await log_action(db, request, current_user.id, f"Bildirishnoma qoidasi qo'shdi: {rule.name}", AUDIT_MODULE)
    await db.commit()
    await db.refresh(rule)
    return _rule_out(rule)


@router.patch("/api/notifications/rules/{rule_id}", response_model=NotificationRuleOut)
async def update_rule(
    rule_id: str, body: NotificationRuleUpdateIn, request: Request, db: DbDep, current_user: ManageDep
) -> NotificationRuleOut:
    rule = await _load_rule(db, rule_id)
    sent = body.model_fields_set

    for field in ("name", "enabled", "channel", "kinds"):
        if field in sent:
            value = getattr(body, field)
            if value is None or (field == "kinds" and not value):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"'{field}' bo'sh bo'lishi mumkin emas")
            setattr(rule, field, value.strip() if field == "name" else list(value) if field == "kinds" else value)

    if "recipients" in sent or "channel" in sent:
        # Kanal almashsa eski qabul qiluvchilar ham yangi kanal qoidasi bilan tekshiriladi.
        raw = body.recipients if "recipients" in sent and body.recipients is not None else list(rule.recipients or [])
        try:
            recipients = clean_recipients(rule.channel, raw)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
        if not recipients:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Kamida bitta qabul qiluvchi kiriting")
        rule.recipients = recipients

    if "module_codes" in sent:
        rule.module_codes = body.module_codes
    if "building_ids" in sent:
        rule.building_ids = await _check_buildings(db, body.building_ids)
    if "min_severity" in sent:
        rule.min_severity = body.min_severity

    await log_action(db, request, current_user.id, f"Bildirishnoma qoidasini tahrirladi: {rule.name}", AUDIT_MODULE)
    await db.commit()
    await db.refresh(rule)
    return _rule_out(rule)


@router.delete("/api/notifications/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: str, request: Request, db: DbDep, current_user: ManageDep) -> None:
    rule = await _load_rule(db, rule_id)
    await log_action(db, request, current_user.id, f"Bildirishnoma qoidasini o'chirdi: {rule.name}", AUDIT_MODULE)
    await db.delete(rule)
    await db.commit()


# ---------------------------------------------------------------------------
# Jurnal, holat, sinov
# ---------------------------------------------------------------------------


@router.get("/api/notifications/log", response_model=Page[NotificationLogOut])
async def list_log(
    db: DbDep,
    _: ManageDep,
    page_params: Annotated[PageParams, Depends()],
    status_filter: Annotated[Literal["yuborildi", "xato", "otkazildi"] | None, Query(alias="status")] = None,
    channel: Annotated[Literal["telegram", "sms"] | None, Query()] = None,
    kind: Annotated[str | None, Query(max_length=40)] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    ref_id: Annotated[str | None, Query(alias="refId", max_length=64)] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> Page[NotificationLogOut]:
    stmt = select(NotificationLog)
    if status_filter:
        stmt = stmt.where(NotificationLog.status == status_filter)
    if channel:
        stmt = stmt.where(NotificationLog.channel == channel)
    if kind:
        stmt = stmt.where(NotificationLog.kind == kind)
    if ref_id:
        stmt = stmt.where(NotificationLog.ref_id == ref_id)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(NotificationLog.recipient.ilike(pattern), NotificationLog.text.ilike(pattern), NotificationLog.error.ilike(pattern))
        )
    if date_from:
        stmt = stmt.where(NotificationLog.created_at >= day_start(date_from))
    if date_to:
        stmt = stmt.where(
            NotificationLog.created_at < day_start(date_to + timedelta(days=1))
        )
    stmt = stmt.order_by(NotificationLog.created_at.desc(), NotificationLog.id)
    rows, total = await paginate(db, stmt, page_params)
    return build_page([_log_out(r) for r in rows], total, page_params)


@router.post("/api/notifications/log/{log_id}/qayta")
async def resend_failed(log_id: uuid.UUID, request: Request, db: DbDep, current_user: ManageDep) -> dict:
    """Xato bilan tugagan xabarni o'sha manzilga qayta yuboradi (matn o'zgarmaydi).
    Natija jurnalga yangi qator bo'lib yoziladi — asl yozuv dalil sifatida qoladi."""
    import html as html_lib

    row = await db.get(NotificationLog, log_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")
    if row.status != "xato":
        raise HTTPException(status.HTTP_409_CONFLICT, "Faqat xato bilan tugagan xabar qayta yuboriladi")
    if not row.text.strip():
        raise HTTPException(status.HTTP_409_CONFLICT, "Xabar matni saqlanmagan — qayta yuborib bo'lmaydi")
    if row.resent_at is not None:
        # Bir marta: har bosishda yana pullik SMS ketardi.
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu xabar allaqachon qayta yuborilgan")
    if row.error and "timeout" in row.error.lower():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Javob kelmagan (timeout) — xabar yetib borgan bo'lishi mumkin, qayta yuborilmaydi"
        )
    if row.kind.startswith("parent_"):
        # Ota-ona keyin botdan chiqqan (/stop) yoki xabarlar o'chirilgan bo'lishi mumkin.
        person = None
        try:
            person = await db.get(StudentStaff, uuid.UUID(row.ref_id or ""))
        except ValueError:
            person = None
        current = {person.parent_telegram_chat_id, sms.normalize_phone(person.parent_phone)} if person else set()
        if person is None or not person.parent_notify_enabled or row.recipient not in current:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Ota-ona endi bu manzilga bog'lanmagan yoki xabarlar o'chirilgan"
            )
    row.resent_at = datetime.now(timezone.utc)
    if row.channel == "telegram":
        if not telegram.is_configured():
            raise HTTPException(status.HTTP_409_CONFLICT, "Telegram bot sozlanmagan")
        result = await telegram.send_message(row.recipient, html_lib.escape(row.text))
    elif row.channel == "sms":
        if not sms.is_configured():
            raise HTTPException(status.HTTP_409_CONFLICT, "SMS sozlanmagan")
        result = await sms.send_sms(row.recipient, row.text)
    else:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Noma'lum kanal: {row.channel}")
    retry = NotificationLog(
        channel=row.channel, recipient=row.recipient, kind=row.kind, text=row.text, ref_id=row.ref_id,
        status="yuborildi" if result.ok else "xato", error=None if result.ok else (result.error or "Noma'lum xato")[:2000],
    )
    db.add(retry)
    await log_action(
        db, request, current_user.id,
        f"Bildirishnomani qayta yubordi ({row.channel}): {'yuborildi' if result.ok else 'xato'}", AUDIT_MODULE,
        status="muvaffaqiyatli" if result.ok else "ogohlantirish",
    )
    await db.commit()
    return {"ok": result.ok, "error": None if result.ok else retry.error, "id": str(retry.id)}


@router.get("/api/notifications/ota-ona")
async def parent_coverage(db: DbDep, _: ManageDep) -> dict:
    """Ota-onaga xabar: nechta talabaning ota-onasi bog'langan va so'nggi
    7 kunda xabarlar qanchalik yetib borgan."""
    from sqlalchemy import func

    students = (StudentStaff.type == "talaba", StudentStaff.active.is_(True))
    total, telegram_linked, phone, enabled = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(StudentStaff.parent_telegram_chat_id.is_not(None)),
                func.count().filter(
                    StudentStaff.parent_phone.is_not(None), StudentStaff.parent_telegram_chat_id.is_(None)
                ),
                func.count().filter(StudentStaff.parent_notify_enabled.is_(True)),
            ).where(*students)
        )
    ).one()
    since = datetime.now(INSTITUTE_TZ) - timedelta(days=7)
    rows = (
        await db.execute(
            select(NotificationLog.status, func.count())
            .where(NotificationLog.kind.in_(("parent_arrival", "parent_absence")))
            .where(NotificationLog.created_at >= since)
            .group_by(NotificationLog.status)
        )
    ).all()
    week = {status_: n for status_, n in rows}
    return {
        "students": total,
        "telegramLinked": telegram_linked,
        "phoneOnly": phone,
        "enabled": enabled,
        "arrivalEnabled": settings.parent_notify_arrival_enabled,
        "absenceEnabled": settings.parent_notify_absence_enabled,
        "weekSent": week.get("yuborildi", 0),
        "weekFailed": week.get("xato", 0),
        "weekSkipped": week.get("otkazildi", 0),
    }


@router.get("/api/notifications/status", response_model=NotificationStatusOut)
async def notification_status(_: ManageDep) -> NotificationStatusOut:
    return NotificationStatusOut(
        telegram_configured=telegram.is_configured(),
        telegram_bot_username=await telegram.bot_username() if telegram.is_configured() else None,
        telegram_polling_enabled=settings.telegram_polling_enabled,
        sms_provider=settings.sms_provider,
        sms_configured=sms.is_configured(),
        sms_sender=settings.eskiz_sender if sms.is_configured() else None,
        parent_arrival_enabled=settings.parent_notify_arrival_enabled,
        parent_absence_enabled=settings.parent_notify_absence_enabled,
        org_name=settings.org_name,
    )


@router.post("/api/notifications/test", response_model=NotificationTestOut)
async def send_test(body: NotificationTestIn, request: Request, db: DbDep, current_user: ManageDep) -> NotificationTestOut:
    result = await dispatcher.send_test_message(db, body.channel, body.recipient, body.text)
    await log_action(
        db,
        request,
        current_user.id,
        f"Sinov xabari yubordi ({body.channel}): {'yuborildi' if result.ok else 'xato'}",
        AUDIT_MODULE,
        status="muvaffaqiyatli" if result.ok else "ogohlantirish",
    )
    await db.commit()
    return NotificationTestOut(ok=result.ok, error=result.error)


# ---------------------------------------------------------------------------
# Telegram bog'lash
# ---------------------------------------------------------------------------


def _new_code() -> str:
    # 16 bayt -> 22 belgi [A-Za-z0-9_-]: Telegram start parametri shartiga mos
    # (64 belgigacha) va taxmin qilib bo'lmaydi.
    return secrets.token_urlsafe(16)


async def _require_bot_username() -> str:
    if not telegram.is_configured():
        raise HTTPException(status.HTTP_409_CONFLICT, "Telegram bot sozlanmagan (TELEGRAM_BOT_TOKEN)")
    username = await telegram.bot_username()
    if not username:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Bot nomini aniqlab bo'lmadi (TELEGRAM_BOT_USERNAME ni kiriting)"
        )
    return username


def _link_out(code: str, username: str) -> TelegramLinkOut:
    return TelegramLinkOut(code=code, deep_link=f"https://t.me/{username}?start={code}", bot_username=username)


@router.get("/api/notifications/me", response_model=MyNotificationsOut)
async def my_notifications(db: DbDep, current_user: Annotated[CurrentUser, Depends(get_current_user)]) -> MyNotificationsOut:
    user = await db.get(User, current_user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Foydalanuvchi topilmadi")
    return MyNotificationsOut(
        telegram_linked=bool(user.telegram_chat_id),
        telegram_bot_configured=telegram.is_configured(),
        phone=user.phone,
    )


@router.post("/api/notifications/me/telegram-link", response_model=TelegramLinkOut)
async def my_telegram_link(db: DbDep, current_user: Annotated[CurrentUser, Depends(get_current_user)]) -> TelegramLinkOut:
    username = await _require_bot_username()
    user = await db.get(User, current_user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Foydalanuvchi topilmadi")
    user.telegram_link_code = _new_code()
    user.telegram_link_expires_at = _link_expiry()
    await db.commit()
    return _link_out(user.telegram_link_code, username)


@router.delete("/api/notifications/me/telegram", status_code=status.HTTP_204_NO_CONTENT)
async def my_telegram_unlink(
    request: Request, db: DbDep, current_user: Annotated[CurrentUser, Depends(get_current_user)]
) -> None:
    user = await db.get(User, current_user.id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Foydalanuvchi topilmadi")
    user.telegram_chat_id = None
    user.telegram_link_code = None
    await log_action(db, request, current_user.id, "Telegram bog'lanishini bekor qildi", AUDIT_MODULE)
    await db.commit()


#: Telegram bog'lash havolasi muddati: uzatilgan yoki chop etilgan eski
#: havola bilan begona odam talaba xabarlarini ololmasin.
LINK_TTL = timedelta(days=7)


def _link_expiry():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc) + LINK_TTL


async def _load_person(db: AsyncSession, record_id: str) -> StudentStaff:
    try:
        record_uuid = uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi") from None
    person = await db.get(StudentStaff, record_uuid)
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")
    return person


@router.post("/api/students-staff/{record_id}/parent-telegram-link", response_model=TelegramLinkOut)
async def parent_telegram_link(
    record_id: str,
    request: Request,
    db: DbDep,
    current_user: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
) -> TelegramLinkOut:
    """Ota-ona uchun bir martalik havola: ota-ona uni ochib botga "/start"
    bosganda chat shu talabaga bog'lanadi."""
    person = await _load_person(db, record_id)
    if person.type != "talaba":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Ota-ona xabarnomasi faqat talabalar uchun")
    username = await _require_bot_username()
    person.telegram_link_code = _new_code()
    person.telegram_link_expires_at = _link_expiry()
    await log_action(db, request, current_user.id, f"Ota-ona Telegram havolasini yaratdi: {person.full_name}", "Talabalar")
    await db.commit()
    return _link_out(person.telegram_link_code, username)


@router.delete("/api/students-staff/{record_id}/parent-telegram", status_code=status.HTTP_204_NO_CONTENT)
async def parent_telegram_unlink(
    record_id: str,
    request: Request,
    db: DbDep,
    current_user: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
) -> None:
    person = await _load_person(db, record_id)
    person.parent_telegram_chat_id = None
    person.telegram_link_code = None
    await log_action(db, request, current_user.id, f"Ota-ona Telegramini uzdi: {person.full_name}", "Talabalar")
    await db.commit()
