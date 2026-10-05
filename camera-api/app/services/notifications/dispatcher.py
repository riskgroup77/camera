"""Bildirishnoma dispatcher: qoidalarni tanlash, matn yig'ish, yuborish,
notification_log'ga yozish.

Imzolar o'zgarmaydi: ularni event_bus, camera_health, attendance_ai,
absence_marker, events router va access_control chaqiradi.

Ish tartibi:
- Ommaviy funksiyalar (notify_*) chaqiruvchini KUTTIRMAYDI: kerakli
  qiymatlarni ORM obyektidan darhol ko'chirib oladi (obyekt keyin
  sessiya bilan birga eskirishi mumkin) va yuborishni fondagi asyncio
  vazifaga beradi. Vazifa o'z sessiyasini ochadi (SessionLocal).
- Hech bir xato chaqiruvchiga chiqmaydi — u logga va notification_log'ga
  yoziladi.
- Hech bir kanal (Telegram ham, SMS ham) sozlanmagan bo'lsa bazaga ham
  murojaat qilinmaydi: yuboradigan narsa yo'q.
- Bir xil signal to'lqini (bitta kamera bir modul bo'yicha ketma-ket
  hodisa bersa) qoida+kamera+modul bo'yicha EVENT_COOLDOWN_SECONDS ichida
  bir marta yuboriladi, qolganlari jurnalga 'otkazildi' bo'lib tushadi.
"""

import asyncio
import html
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Coroutine, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.models import AttendanceRecord, Building, Camera, Event, NotificationLog, NotificationRule, StudentStaff, User
from app.services.notifications import messages, sms, telegram
from app.services.notifications.messages import SEVERITY_ORDER, Message
from app.services.notifications.telegram import SendResult
from app.timezone import local_now
from app.timezone import business_today

logger = logging.getLogger("app.notifications")

# Bitta qoida bir kameraning bir modul signalini shuncha vaqtda bir marta yuboradi.
EVENT_COOLDOWN_SECONDS = 300
# Turniket: bir qurilma + bir karta — shuncha vaqtda bir marta.
ACCESS_DENIED_COOLDOWN_SECONDS = 60
# Ota-onalarga ommaviy yuborishda bir vaqtdagi so'rovlar soni (Telegram
# umumiy cheklovi ~30 xabar/s).
PARENT_SEND_CONCURRENCY = 4
PARENT_BATCH_SIZE = 500
# Hodisa kadri shundan katta bo'lsa rasm emas, faqat matn yuboriladi
# (Telegram sendPhoto cheklovi 10 MB).
MAX_PHOTO_BYTES = 10 * 1024 * 1024

_session_factory: async_sessionmaker[AsyncSession] | Callable[[], Any] = SessionLocal
_pending: set[asyncio.Task] = set()
_last_sent: dict[tuple, float] = {}
_arrival_sent: dict[date, set[str]] = {}


# ---------------------------------------------------------------------------
# Test yordamchilari
# ---------------------------------------------------------------------------


def set_session_factory(factory: Callable[[], Any]) -> None:
    """Testlar fondagi vazifalarni test bazasiga yo'naltiradi."""
    global _session_factory
    _session_factory = factory


def reset_state_for_tests() -> None:
    _last_sent.clear()
    _device_denials.clear()
    _arrival_sent.clear()


async def wait_for_pending(timeout: float = 10.0) -> None:
    """Fondagi barcha yuborishlar tugashini kutadi (testlar va to'xtash uchun)."""
    deadline = time.monotonic() + timeout
    while _pending and time.monotonic() < deadline:
        await asyncio.wait(list(_pending), timeout=max(0.0, deadline - time.monotonic()))


# ---------------------------------------------------------------------------
# Umumiy yordamchilar
# ---------------------------------------------------------------------------


def channel_configured(channel: str) -> bool:
    if channel == "telegram":
        return telegram.is_configured()
    if channel == "sms":
        return sms.is_configured()
    return False


def any_channel_configured() -> bool:
    return telegram.is_configured() or sms.is_configured()


def _spawn(coro: Coroutine[Any, Any, None], name: str) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        return
    task = loop.create_task(_guard(coro, name), name=f"notify:{name}")
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def _guard(coro: Awaitable[None], name: str) -> None:
    try:
        await coro
    except Exception:
        logger.exception("notification task failed", extra={"task": name})


def _throttled(key: tuple, cooldown: float) -> bool:
    """True — shu kalit yaqinda yuborilgan. False bo'lsa kalit belgilanadi."""
    now = time.monotonic()
    last = _last_sent.get(key)
    if last is not None and now - last < cooldown:
        return True
    if len(_last_sent) > 5000:
        for stale in [k for k, v in _last_sent.items() if now - v > max(EVENT_COOLDOWN_SECONDS, cooldown)]:
            _last_sent.pop(stale, None)
    _last_sent[key] = now
    return False


def _log(
    channel: str,
    recipient: str,
    kind: str,
    text: str,
    *,
    result: SendResult | None = None,
    skipped: str | None = None,
    ref_id: str | None = None,
) -> NotificationLog:
    if skipped is not None:
        status, error = "otkazildi", skipped
    elif result is not None and result.ok:
        status, error = "yuborildi", None
    else:
        status, error = "xato", (result.error if result else "Noma'lum xato")
    return NotificationLog(
        channel=channel,
        recipient=str(recipient)[:255],
        kind=kind,
        status=status,
        text=text,
        error=(error or None) and error[:2000],
        ref_id=ref_id,
    )


async def _load_snapshot(key: str) -> bytes | None:
    """Hodisa kadri MinIO'dan (bayt ko'rinishida). Topilmasa yoki ombor
    javob bermasa — None: xabar rasmsiz ketadi."""
    from app import storage

    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(storage.read_file, key, MAX_PHOTO_BYTES),
            timeout=settings.notification_timeout_seconds,
        )
    except Exception:
        logger.warning("event snapshot unavailable for notification", extra={"key": key}, exc_info=True)
        return None
    if not data or len(data) > MAX_PHOTO_BYTES:
        return None
    return data


async def deliver(channel: str, recipient: str, message: Message, *, photo: bytes | None = None) -> SendResult:
    """Bitta xabarni bitta manzilga. Telegram'da kadr bo'lsa rasm bilan,
    rasm o'tmasa — matn bilan."""
    if channel == "telegram":
        if photo:
            result = await telegram.send_photo(recipient, photo, message.html())
            if result.ok or result.blocked:
                return result
            logger.info("telegram photo rejected, falling back to text", extra={"error": result.error})
        return await telegram.send_message(recipient, message.html())
    if channel == "sms":
        return await sms.send_sms(recipient, message.sms())
    return SendResult(ok=False, error=f"Noma'lum kanal: {channel}")


def rule_matches(
    rule: NotificationRule,
    kind: str,
    *,
    module_code: int | None = None,
    building_id: uuid.UUID | str | None = None,
    severity: str | None = None,
) -> bool:
    """Qoida shu signalga tegishlimi. Bo'sh filtr (NULL yoki []) — cheklov yo'q.

    - module_codes va min_severity faqat hodisalarga (event, event_overdue) taalluqli;
    - building_ids hodisa va kamera holatiga taalluqli; binosi noma'lum
      signal bino filtri bor qoidaga tushmaydi."""
    if not rule.enabled or kind not in (rule.kinds or []):
        return False
    is_event = kind in ("event", "event_overdue")
    if is_event and rule.module_codes:
        allowed = set()
        for code in rule.module_codes:
            try:
                allowed.add(int(code))
            except (TypeError, ValueError):
                continue
        if module_code is None or int(module_code) not in allowed:
            return False
    if rule.building_ids and kind in ("event", "event_overdue", "camera_offline", "camera_online"):
        if building_id is None or str(building_id) not in {str(b) for b in rule.building_ids}:
            return False
    if is_event and rule.min_severity:
        threshold = SEVERITY_ORDER.get(rule.min_severity, 0)
        if SEVERITY_ORDER.get(severity or "", -1) < threshold:
            return False
    return True


async def _matching_rules(db: AsyncSession, kind: str, **filters: Any) -> list[NotificationRule]:
    rows = (
        await db.execute(
            select(NotificationRule)
            .where(NotificationRule.enabled.is_(True))
            .where(NotificationRule.kinds.contains([kind]))
            .order_by(NotificationRule.created_at)
        )
    ).scalars().all()
    return [rule for rule in rows if rule_matches(rule, kind, **filters)]


async def _dispatch_rules(
    db: AsyncSession,
    kind: str,
    message: Message,
    *,
    ref_id: str | None,
    filters: dict[str, Any],
    throttle: tuple | None = None,
    cooldown: float = 0.0,
    photo_key: str | None = None,
    sent_to: set[tuple[str, str]] | None = None,
) -> list[NotificationLog]:
    rules = await _matching_rules(db, kind, **filters)
    if not rules:
        return []
    sent_to = sent_to if sent_to is not None else set()
    photo: bytes | None = None
    if photo_key and any(r.channel == "telegram" and telegram.is_configured() for r in rules):
        photo = await _load_snapshot(photo_key)
    text = message.plain()
    logs: list[NotificationLog] = []
    for rule in rules:
        recipients = [str(r).strip() for r in (rule.recipients or []) if str(r).strip()]
        if throttle is not None and _throttled((str(rule.id), kind, *throttle), cooldown):
            for recipient in recipients:
                logs.append(
                    _log(
                        rule.channel,
                        recipient,
                        kind,
                        text,
                        skipped=f"Takroriy signal: '{rule.name}' qoidasi bo'yicha {int(cooldown // 60)} daqiqa ichida yuborilgan",
                        ref_id=ref_id,
                    )
                )
            continue
        for recipient in recipients:
            if (rule.channel, recipient) in sent_to:
                continue
            sent_to.add((rule.channel, recipient))
            if not channel_configured(rule.channel):
                label = "Telegram bot" if rule.channel == "telegram" else "SMS xizmati"
                logs.append(_log(rule.channel, recipient, kind, text, skipped=f"{label} sozlanmagan", ref_id=ref_id))
                continue
            result = await deliver(rule.channel, recipient, message, photo=photo)
            logs.append(_log(rule.channel, recipient, kind, text, result=result, ref_id=ref_id))
    return logs


async def _deliver_to_user(
    db: AsyncSession, user: User, message: Message, kind: str, ref_id: str | None, *, html_text: str | None = None
) -> list[NotificationLog]:
    """Telegram bog'langan bo'lsa — Telegram; bot bloklangan bo'lsa bog'lanish
    uziladi va SMS ga o'tiladi; aks holda SMS (user.phone)."""
    text = message.plain()
    logs: list[NotificationLog] = []
    if user.telegram_chat_id and telegram.is_configured():
        result = await telegram.send_message(user.telegram_chat_id, html_text if html_text is not None else message.html())
        logs.append(_log("telegram", user.telegram_chat_id, kind, text, result=result, ref_id=ref_id))
        if result.ok or result.no_fallback:
            return logs
        if result.blocked:
            logger.info("user blocked the telegram bot, unlinking", extra={"user_id": str(user.id)})
            user.telegram_chat_id = None
    phone = sms.normalize_phone(user.phone)
    if phone and sms.is_configured():
        result = await sms.send_sms(phone, message.sms())
        logs.append(_log("sms", phone, kind, text, result=result, ref_id=ref_id))
    elif not logs:
        reason = "Foydalanuvchida Telegram ham, telefon raqami ham yo'q"
        if user.telegram_chat_id or phone:
            reason = "Foydalanuvchi uchun mos kanal sozlanmagan"
        logs.append(_log("telegram", f"user:{user.login}", kind, text, skipped=reason, ref_id=ref_id))
    return logs


async def _deliver_to_parent(person: StudentStaff, text: str, kind: str) -> list[NotificationLog]:
    """Ota-onaga: Telegram (bog'langan bo'lsa), aks holda SMS (parent_phone)."""
    ref_id = str(person.id)
    logs: list[NotificationLog] = []
    if person.parent_telegram_chat_id and telegram.is_configured():
        result = await telegram.send_message(person.parent_telegram_chat_id, html.escape(text))
        logs.append(_log("telegram", person.parent_telegram_chat_id, kind, text, result=result, ref_id=ref_id))
        if result.ok or result.no_fallback:
            return logs
        if result.blocked:
            person.parent_telegram_chat_id = None
    phone = sms.normalize_phone(person.parent_phone)
    if phone and sms.is_configured():
        result = await sms.send_sms(phone, text)
        logs.append(_log("sms", phone, kind, text, result=result, ref_id=ref_id))
    elif not logs:
        reason = "Ota-onaning Telegrami ham, telefon raqami ham yo'q"
        if phone or person.parent_telegram_chat_id:
            reason = "Ota-ona uchun mos kanal sozlanmagan"
        logs.append(_log("sms", person.parent_phone or "-", kind, text, skipped=reason, ref_id=ref_id))
    return logs


async def _save_logs(db: AsyncSession, logs: Iterable[NotificationLog]) -> None:
    logs = list(logs)
    db.add_all(logs)
    await db.commit()


# ---------------------------------------------------------------------------
# Hodisalar
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _EventSnapshot:
    id: str
    camera_id: uuid.UUID | None
    camera_name: str
    building: str
    module_code: int
    module_name: str
    severity: str
    occurred_at: datetime
    person_name: str | None
    confidence: int | None
    snapshot_key: str | None
    is_trial: bool
    due_at: datetime | None
    assigned_to_id: uuid.UUID | None

    @classmethod
    def of(cls, event: Event) -> "_EventSnapshot":
        return cls(
            id=str(event.id),
            camera_id=event.camera_id,
            camera_name=event.camera_name,
            building=event.building,
            module_code=event.module_code,
            module_name=event.module_name,
            severity=event.severity,
            occurred_at=event.occurred_at or datetime.now(timezone.utc),
            person_name=event.person_name,
            confidence=event.confidence,
            snapshot_key=event.snapshot_key,
            is_trial=bool(event.is_trial),
            due_at=event.due_at,
            assigned_to_id=event.assigned_to_id,
        )


async def _event_building_id(db: AsyncSession, snap: _EventSnapshot) -> uuid.UUID | None:
    if snap.camera_id is not None:
        building_id = (await db.execute(select(Camera.building_id).where(Camera.id == snap.camera_id))).scalar_one_or_none()
        if building_id is not None:
            return building_id
    if snap.building:
        return (await db.execute(select(Building.id).where(Building.name == snap.building))).scalar_one_or_none()
    return None


async def _send_event(snap: _EventSnapshot) -> None:
    message = messages.event_message(
        event_id=snap.id,
        module_name=snap.module_name,
        camera_name=snap.camera_name,
        building=snap.building,
        severity=snap.severity,
        occurred_at=snap.occurred_at,
        person_name=snap.person_name,
        confidence=snap.confidence,
    )
    async with _session_factory() as db:
        building_id = await _event_building_id(db, snap)
        logs = await _dispatch_rules(
            db,
            "event",
            message,
            ref_id=snap.id,
            filters={"module_code": snap.module_code, "building_id": building_id, "severity": snap.severity},
            throttle=(str(snap.camera_id or snap.camera_name), snap.module_code),
            cooldown=EVENT_COOLDOWN_SECONDS,
            photo_key=snap.snapshot_key,
        )
        if logs:
            await _save_logs(db, logs)


async def notify_event(event: Event) -> None:
    """Yangi (sinov bo'lmagan) AI hodisasi — 'event' qoidalari bo'yicha."""
    if not any_channel_configured():
        return
    try:
        snap = _EventSnapshot.of(event)
    except Exception:
        logger.warning("notify_event: event not readable", exc_info=True)
        return
    if snap.is_trial:
        return
    _spawn(_send_event(snap), "event")


async def _send_event_overdue(snap: _EventSnapshot) -> None:
    async with _session_factory() as db:
        assignee = await db.get(User, snap.assigned_to_id) if snap.assigned_to_id else None
        message = messages.event_overdue_message(
            event_id=snap.id,
            module_name=snap.module_name,
            camera_name=snap.camera_name,
            building=snap.building,
            severity=snap.severity,
            occurred_at=snap.occurred_at,
            due_at=snap.due_at,
            assignee_name=assignee.full_name if assignee else None,
        )
        sent_to: set[tuple[str, str]] = set()
        logs: list[NotificationLog] = []
        if assignee is not None:
            logs += await _deliver_to_user(db, assignee, message, "event_overdue", snap.id)
            if assignee.telegram_chat_id:
                sent_to.add(("telegram", assignee.telegram_chat_id))
            if phone := sms.normalize_phone(assignee.phone):
                sent_to.add(("sms", phone))
        building_id = await _event_building_id(db, snap)
        logs += await _dispatch_rules(
            db,
            "event_overdue",
            message,
            ref_id=snap.id,
            filters={"module_code": snap.module_code, "building_id": building_id, "severity": snap.severity},
            sent_to=sent_to,
        )
        if logs:
            await _save_logs(db, logs)


async def notify_event_overdue(event: Event) -> None:
    """Hal qilish muddati (due_at) o'tgan hodisa — 'event_overdue' qoidalari
    va tayinlangan foydalanuvchi."""
    if not any_channel_configured():
        return
    try:
        snap = _EventSnapshot.of(event)
    except Exception:
        logger.warning("notify_event_overdue: event not readable", exc_info=True)
        return
    _spawn(_send_event_overdue(snap), "event_overdue")


# ---------------------------------------------------------------------------
# Kameralar
# ---------------------------------------------------------------------------


async def _send_camera_status(
    camera_id: str, name: str, ip: str | None, building_id: uuid.UUID | None, online: bool, offline_since: datetime | None
) -> None:
    async with _session_factory() as db:
        building_name = ""
        if building_id is not None:
            building_name = (
                await db.execute(select(Building.name).where(Building.id == building_id))
            ).scalar_one_or_none() or ""
        message = messages.camera_status_message(
            camera_name=name,
            building=building_name,
            ip=ip,
            online=online,
            offline_since=offline_since,
            now=datetime.now(timezone.utc),
        )
        kind = "camera_online" if online else "camera_offline"
        logs = await _dispatch_rules(db, kind, message, ref_id=camera_id, filters={"building_id": building_id})
        if logs:
            await _save_logs(db, logs)


async def notify_camera_status(camera: Camera, *, online: bool, offline_since: datetime | None = None) -> None:
    """Kamera o'chdi ('camera_offline') yoki qayta tiklandi ('camera_online')."""
    if not any_channel_configured():
        return
    try:
        args = (str(camera.id), camera.name, camera.ip, camera.building_id)
    except Exception:
        logger.warning("notify_camera_status: camera not readable", exc_info=True)
        return
    _spawn(_send_camera_status(*args, online, offline_since), "camera_status")


# ---------------------------------------------------------------------------
# Ota-onalar (davomat)
# ---------------------------------------------------------------------------


def _parent_reachable(person: StudentStaff) -> bool:
    return bool(
        (person.parent_telegram_chat_id and telegram.is_configured())
        or (person.parent_phone and sms.is_configured())
    )


async def _send_arrival(person_id: uuid.UUID, check_in: Any) -> None:
    async with _session_factory() as db:
        person = await db.get(StudentStaff, person_id)
        if person is None or person.type != "talaba" or not person.parent_notify_enabled or not person.active:
            return
        text = messages.parent_arrival_text(person.full_name, check_in, fallback_moment=datetime.now(timezone.utc))
        logs = await _deliver_to_parent(person, text, "parent_arrival")
        await _save_logs(db, logs)


async def notify_attendance(record: AttendanceRecord, person: StudentStaff | None, camera: Camera | None) -> None:
    """Kunning birinchi qaydi — ota-onaga (parent_notify_enabled bo'lsa)."""
    if not settings.parent_notify_arrival_enabled or not any_channel_configured():
        return
    try:
        if record.status not in ("keldi", "kech_keldi"):
            return
        person_id = record.student_staff_id
        day = record.date
        check_in = record.check_in
    except Exception:
        logger.warning("notify_attendance: record not readable", exc_info=True)
        return
    try:
        # Tez filtr: xodim yoki xabarnoma o'chiq bo'lsa fondagi vazifa ham
        # ochilmaydi. Obyektni o'qib bo'lmasa — fondagi vazifa bazadan tekshiradi.
        if person is not None and (person.type != "talaba" or not person.parent_notify_enabled):
            return
    except Exception:
        pass
    today = business_today()
    if day != today:
        # Kechagi yozuvni tuzatish yoki qayta ishlash — ota-onaga "keldi"
        # xabari endi kerak emas.
        return
    # Bir kunda bir marta: kamera ham, turniket ham birinchi qaydni berishi mumkin.
    for stale in [d for d in _arrival_sent if d != today]:
        _arrival_sent.pop(stale, None)
    seen = _arrival_sent.setdefault(today, set())
    if str(person_id) in seen:
        return
    seen.add(str(person_id))
    _spawn(_send_arrival(person_id, check_in), "parent_arrival")


async def _send_absences(person_ids: list[uuid.UUID], day: date) -> None:
    semaphore = asyncio.Semaphore(PARENT_SEND_CONCURRENCY)

    async def _one(person: StudentStaff) -> list[NotificationLog]:
        async with semaphore:
            try:
                return await _deliver_to_parent(person, messages.parent_absence_text(person.full_name, day), "parent_absence")
            except Exception as exc:
                logger.warning("parent absence notification failed", extra={"person_id": str(person.id)}, exc_info=True)
                return [_log("sms", person.parent_phone or "-", "parent_absence", "", result=SendResult(ok=False, error=str(exc)), ref_id=str(person.id))]

    for start in range(0, len(person_ids), PARENT_BATCH_SIZE):
        chunk = person_ids[start : start + PARENT_BATCH_SIZE]
        async with _session_factory() as db:
            people = (
                await db.execute(
                    select(StudentStaff).where(
                        StudentStaff.id.in_(chunk),
                        StudentStaff.type == "talaba",
                        StudentStaff.parent_notify_enabled.is_(True),
                        StudentStaff.active.is_(True),
                    )
                )
            ).scalars().all()
            targets = [p for p in people if p.parent_telegram_chat_id or p.parent_phone]
            if not targets:
                continue
            results = await asyncio.gather(*(_one(p) for p in targets))
            await _save_logs(db, [log for group in results for log in group])


async def notify_absences(person_ids: list[uuid.UUID], day: date) -> None:
    """Kun oxirida 'kelmadi' deb belgilanganlar — ota-onaga."""
    if not settings.parent_notify_absence_enabled or not person_ids or not any_channel_configured():
        return
    ids = [pid if isinstance(pid, uuid.UUID) else uuid.UUID(str(pid)) for pid in person_ids]
    _spawn(_send_absences(ids, day), "parent_absence")


# ---------------------------------------------------------------------------
# Turniket va foydalanuvchilar
# ---------------------------------------------------------------------------


#: Bitta turniketdan 10 daqiqada ko'pi bilan shuncha "rad etildi" xabari:
#: har xil kartani ketma-ket bosib, har biriga qoidadagi hamma odamga pullik
#: SMS yubortirish mumkin edi (karta bo'yicha cheklov bunga to'sqinlik qilmasdi).
ACCESS_DENIED_DEVICE_LIMIT = 5
ACCESS_DENIED_DEVICE_WINDOW = 600.0
_device_denials: dict[str, list[float]] = {}


def _device_flooding(device_name: str) -> bool:
    now = time.monotonic()
    recent = [t for t in _device_denials.get(device_name, []) if now - t < ACCESS_DENIED_DEVICE_WINDOW]
    if len(recent) >= ACCESS_DENIED_DEVICE_LIMIT:
        _device_denials[device_name] = recent
        return True
    recent.append(now)
    _device_denials[device_name] = recent
    return False


async def _send_access_denied(device_name: str, person_name: str | None, card_number: str | None, occurred_at: datetime) -> None:
    if _device_flooding(device_name):
        logger.warning("access denied notices suppressed — device flood", extra={"device": device_name})
        return
    message = messages.access_denied_message(
        device_name=device_name, person_name=person_name, card_number=card_number, occurred_at=occurred_at
    )
    async with _session_factory() as db:
        logs = await _dispatch_rules(
            db,
            "access_denied",
            message,
            ref_id=card_number,
            filters={},
            throttle=(device_name, card_number or person_name or ""),
            cooldown=ACCESS_DENIED_COOLDOWN_SECONDS,
        )
        if logs:
            await _save_logs(db, logs)


async def notify_access_denied(device_name: str, person_name: str | None, card_number: str | None, occurred_at: datetime) -> None:
    """Turniketda rad etilgan kirish — 'access_denied' qoidalari."""
    if not any_channel_configured():
        return
    _spawn(_send_access_denied(device_name, person_name, card_number, occurred_at), "access_denied")


async def _send_user(user_id: uuid.UUID, text: str, kind: str, ref_id: str | None) -> None:
    async with _session_factory() as db:
        user = await db.get(User, user_id)
        if user is None:
            return
        message = Message(title=text)
        logs = await _deliver_to_user(db, user, message, kind, ref_id, html_text=html.escape(text))
        await _save_logs(db, logs)


async def notify_user(user_id: uuid.UUID | str, text: str, *, kind: str = "system", ref_id: str | None = None) -> None:
    """Bitta foydalanuvchiga (Telegram bog'langan bo'lsa, aks holda SMS)."""
    if not any_channel_configured():
        return
    try:
        uid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
    except ValueError:
        logger.warning("notify_user: bad user id", extra={"user_id": str(user_id)})
        return
    _spawn(_send_user(uid, text, kind, ref_id), "user")


# ---------------------------------------------------------------------------
# Sinov xabari (router: POST /api/notifications/test)
# ---------------------------------------------------------------------------


async def send_test_message(db: AsyncSession, channel: str, recipient: str, text: str | None) -> SendResult:
    """Sinov xabari — KUTILADI (administrator natijani darhol ko'rishi kerak)
    va jurnalga 'system' turi bilan yoziladi. Commit chaqiruvchida."""
    message = messages.sample_message(text)
    if not channel_configured(channel):
        label = "Telegram bot" if channel == "telegram" else "SMS xizmati"
        result = SendResult(ok=False, error=f"{label} sozlanmagan")
    else:
        result = await deliver(channel, recipient, message)
    db.add(_log(channel, recipient, "system", message.plain(), result=result, ref_id="test"))
    return result
