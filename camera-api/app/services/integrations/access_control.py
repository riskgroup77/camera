"""Turniket / kirish nazorati hodisalarini qabul qilish va davomatga yozish.

Hodisa qayerdan kelishidan qat'i nazar (Hikvision ISAPI so'rovi —
hikvision_acs.py, yoki qurilma/oraliq dastur webhook'i —
app/routers/access_control.py) bitta funksiyadan o'tadi:
ingest_access_event. U:

  1. access_events jadvaliga IDEMPOTENT yozadi — (device_id, external_id)
     unikal, ya'ni qayta so'ralgan yoki qayta yuborilgan hodisa ikkinchi
     marta hisoblanmaydi;
  2. odamni topadi: avval karta raqami (StudentStaff.card_number), keyin
     qurilmadagi xodim raqami (HEMIS ID yoki JSHSHIR);
  3. ruxsat berilgan kirishni davomatga yozadi (source='turniket') —
     kechikish chegarasi AI davomati bilan AYNAN bir xil
     (app/jobs/attendance_ai.first_sighting_status);
  4. rad etilgan kirish haqida xabar beradi (notify_access_denied).

Davomat qoidalari:
  * kunning birinchi kirishi — check_in va keldi/kech_keldi;
  * yo'nalishi "kirish" bo'lgan keyingi hodisa kunning check_in'idan
    OLDIN bo'lsa (masalan, qurilma kechikib so'ralgan, kamera esa odamni
    ertaroq "kech keldi" deb yozib qo'ygan) — turniket vaqti ustun:
    turniket — kelishning aniq vaqti, kamera esa faqat ko'rgan payti;
  * "chiqish" (yoki yo'nalishi noma'lum qurilmadagi keyingi hodisa) —
    check_out oldinga suriladi;
  * kun "kelmadi" deb belgilangan bo'lsa-yu, odam turniketdan o'tgan
    bo'lsa — belgi tuzatiladi.

ATTENDANCE_ARRIVAL_ONLY (production): yo'nalish ahamiyatsiz — kunning eng
erta hodisasi kelish (talaba/xodim ish boshlanishi, attendance_policy),
eng kechi (track_last_seen) — check_out, kamera yo'li bilan bir xil.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, time as time_type, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer
from sqlalchemy.orm.attributes import set_committed_value

from app.config import settings
from app.jobs.attendance_ai import first_sighting_status
from app.models import AccessDevice, AccessEvent, AttendanceRecord, AuditLog, StudentStaff
from app.services.attendance_policy import current_policy, load_policy
from app.services.notifications import notify_access_denied, notify_attendance
from app.timezone import INSTITUTE_TZ, business_date, business_seconds, local_now, to_local
from app.ws import manager
from app.timezone import business_today

logger = logging.getLogger("app.integrations.access")

DIRECTIONS = ("kirish", "chiqish", "ikkalasi")
# Rad etilgan kirish haqida faqat yangi hodisa uchun xabar beriladi:
# qurilma bir kun oflayn bo'lib, keyin tarixni bir yo'la bersa, o'tgan
# kunning har bir rad etilishi uchun hozir signal yuborish — shovqin.
ACCESS_DENIED_NOTIFY_MAX_AGE = timedelta(minutes=15)
API_KEY_PREFIX = "ak_"
MAX_IDENTIFIER_LENGTH = 64

_IN_WORDS = {"kirish", "in", "entry", "enter", "checkin", "check_in", "check-in", "0", "i"}
_OUT_WORDS = {"chiqish", "out", "exit", "checkout", "check_out", "check-out", "1", "o"}


# ── API kalit ───────────────────────────────────────────────────────────────


def generate_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    """Kalit tasodifiy va uzun (256 bit) — sekin xesh (bcrypt) kerak emas,
    SHA-256 yetarli va har bir webhook so'rovida arzon."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def verify_api_key(key: str | None, stored_hash: str | None) -> bool:
    if not key or not stored_hash:
        return False
    return hmac.compare_digest(hash_api_key(key), stored_hash)


# ── Sof normallashtirish funksiyalari ───────────────────────────────────────


def normalize_direction(value: Any) -> str | None:
    """'kirish' | 'chiqish' | None (noma'lum)."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().lower()
    if text in _IN_WORDS or text.startswith(("checkin", "breakin", "overtimein")):
        return "kirish"
    if text in _OUT_WORDS or text.startswith(("checkout", "breakout", "overtimeout")):
        return "chiqish"
    return None


def effective_direction(event_direction: str | None, device_direction: str | None) -> str | None:
    """Hodisaning o'z yo'nalishi ustun; bo'lmasa qurilmaniki
    ('ikkalasi' — noma'lum)."""
    if event_direction in ("kirish", "chiqish"):
        return event_direction
    if device_direction in ("kirish", "chiqish"):
        return device_direction
    return None


def clean_identifier(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if not text or text.lower() in ("none", "null", "0"):
        return None
    return text[:MAX_IDENTIFIER_LENGTH]


def parse_event_time(value: Any) -> datetime:
    """ISO-8601 (mintaqa bilan yoki mintaqasiz — institut vaqti deb
    olinadi), "YYYY-MM-DD HH:MM:SS" yoki Unix vaqti (soniya/millisoniya)."""
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if seconds > 1e11:  # millisoniya
            seconds /= 1000.0
        moment = datetime.fromtimestamp(seconds, tz=timezone.utc)
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if re.fullmatch(r"\d{9,13}", text):
            return parse_event_time(int(text))
        text = text.replace("Z", "+00:00")
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            try:
                moment = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise ValueError(f"Vaqtni o'qib bo'lmadi: {value!r}") from None
    else:
        raise ValueError("Hodisa vaqti ko'rsatilmagan")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=INSTITUTE_TZ)
    return moment


def _parse_granted(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    return text not in ("false", "0", "no", "denied", "rad", "rad_etildi", "fail", "failed")


@dataclass
class NormalizedEvent:
    external_id: str
    occurred_at: datetime
    card_number: str | None
    employee_no: str | None
    direction: str | None
    granted: bool
    raw: dict


def normalize_webhook_event(item: Any) -> NormalizedEvent:
    """Umumiy JSON: {id, time, cardNo?, employeeNo?, direction?, granted?}.
    ZKTeco/oraliq dasturlarining nomlari ham qabul qilinadi (pin, user_id,
    checktime, punch/status, ...). Noto'g'ri yozuv — ValueError."""
    if not isinstance(item, dict):
        raise ValueError("Hodisa obyekt bo'lishi kerak")

    def first(*keys: str) -> Any:
        for key in keys:
            if key in item and item[key] not in (None, ""):
                return item[key]
        return None

    occurred_at = parse_event_time(first("time", "occurredAt", "occurred_at", "timestamp", "checktime", "check_time", "datetime", "punch_time"))
    card = clean_identifier(first("cardNo", "card_no", "cardNumber", "card_number", "card"))
    employee = clean_identifier(
        first("employeeNo", "employee_no", "employeeNoString", "pin", "user_id", "userId", "emp_code", "personId")
    )
    if card is None and employee is None:
        raise ValueError("cardNo yoki employeeNo kerak")
    direction_value = first("direction", "punch", "punch_state", "checktype", "check_type", "attendanceStatus", "status", "state")
    direction = normalize_direction(direction_value)
    granted = _parse_granted(first("granted", "authorized", "allowed", "result"))
    external = clean_identifier(first("id", "eventId", "event_id", "serialNo", "serial_no", "logId"))
    if external is None:
        # Identifikatorsiz tizimlar (ZKTeco ATTLOG) — odam + vaqt yetarlicha unikal.
        external = f"{employee or card}@{occurred_at.astimezone(timezone.utc).isoformat()}"
    return NormalizedEvent(
        external_id=external[:200],
        occurred_at=occurred_at,
        card_number=card,
        employee_no=employee,
        direction=direction,
        granted=granted,
        raw={k: v for k, v in item.items() if isinstance(v, (str, int, float, bool)) or v is None},
    )


def parse_zkteco_attlog(body: str) -> list[NormalizedEvent]:
    """ZKTeco ADMS "ATTLOG" matni: har qatorda tab bilan ajratilgan
    PIN, "YYYY-MM-DD HH:MM:SS", holat (0 — kirish, 1 — chiqish, ...),
    tekshiruv usuli, ... Buzuq qatorlar tashlab ketiladi."""
    events: list[NormalizedEvent] = []
    for line in body.splitlines():
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 2 or not parts[0]:
            continue
        try:
            occurred_at = parse_event_time(parts[1])
        except ValueError:
            continue
        pin = clean_identifier(parts[0])
        if pin is None:
            continue
        state = parts[2] if len(parts) > 2 else None
        direction = {"0": "kirish", "1": "chiqish", "4": "kirish", "5": "chiqish"}.get(state or "")
        events.append(
            NormalizedEvent(
                external_id=f"{pin}@{occurred_at.astimezone(timezone.utc).isoformat()}",
                occurred_at=occurred_at,
                card_number=None,
                employee_no=pin,
                direction=direction,
                granted=True,
                raw={"line": line[:300]},
            )
        )
    return events


# ── Odamni topish ───────────────────────────────────────────────────────────


async def resolve_person(db: AsyncSession, card_number: str | None, employee_no: str | None) -> StudentStaff | None:
    """Karta raqami (aniq, keyin boshidagi nollarsiz — ba'zi o'quvchilar
    "0012345" ni "12345" deb beradi), so'ng xodim raqami — HEMIS ID yoki
    JSHSHIR. Bir nechta nomzod bo'lsa — hech kim (taxmin qilinmaydi)."""
    base = select(StudentStaff).options(defer(StudentStaff.biometric_embedding))
    if card_number:
        exact = (await db.execute(base.where(StudentStaff.card_number == card_number))).scalars().first()
        if exact is not None:
            return exact
        stripped = card_number.lstrip("0")
        if stripped:
            rows = (
                await db.execute(base.where(func.ltrim(StudentStaff.card_number, "0") == stripped).limit(2))
            ).scalars().all()
            if len(rows) == 1:
                return rows[0]
    if employee_no:
        rows = (
            await db.execute(
                base.where(or_(StudentStaff.hemis_id == employee_no, StudentStaff.pinfl == employee_no)).limit(2)
            )
        ).scalars().all()
        if len(rows) == 1:
            return rows[0]
    return None


# ── Qabul qilish ────────────────────────────────────────────────────────────


@dataclass
class IngestResult:
    duplicate: bool
    event_id: uuid.UUID | None = None
    person: StudentStaff | None = None
    attendance: AttendanceRecord | None = None
    attendance_created: bool = False


def _reader(direction: str | None) -> SimpleNamespace:
    """first_sighting_status kamera obyektini kutadi — turniket kirish
    eshigidagi "kamera"ning o'zi: yo'nalishi aniq bo'lsa, u haqiqiy kelish."""
    return SimpleNamespace(face_direction="kirish" if direction == "kirish" else None, is_entrance=True)


async def ingest_access_event(
    db: AsyncSession,
    device: AccessDevice,
    external_id: str,
    occurred_at: datetime,
    card_number: str | None,
    employee_no: str | None,
    direction: str | None,
    granted: bool,
    raw: dict | None,
) -> IngestResult:
    """Bitta hodisa. Tranzaksiyani o'zi commit qiladi; bildirishnoma va
    WebSocket xabari commit'dan keyin."""
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=INSTITUTE_TZ)
    card_number = clean_identifier(card_number)
    employee_no = clean_identifier(employee_no)
    event_direction = effective_direction(normalize_direction(direction) or direction, device.direction)

    person = await resolve_person(db, card_number, employee_no)
    event_id = (
        await db.execute(
            insert(AccessEvent)
            .values(
                device_id=device.id,
                external_id=str(external_id)[:200],
                occurred_at=occurred_at,
                card_number=card_number,
                employee_no=employee_no,
                student_staff_id=person.id if person else None,
                direction=event_direction,
                granted=bool(granted),
                raw=raw,
            )
            .on_conflict_do_nothing(constraint="uq_access_events_device_external")
            .returning(AccessEvent.id)
        )
    ).scalar_one_or_none()
    if event_id is None:
        # Allaqachon qabul qilingan — hech narsa yozilmadi.
        return IngestResult(duplicate=True, person=person)

    await db.execute(
        update(AccessDevice)
        .where(AccessDevice.id == device.id)
        .where(or_(AccessDevice.last_event_at.is_(None), AccessDevice.last_event_at < occurred_at))
        .values(last_event_at=occurred_at)
    )
    if device.last_event_at is None or device.last_event_at < occurred_at:
        # Faqat xotiradagi nusxa: bazaga yuqoridagi shartli UPDATE yozdi,
        # ORM flush esa boshqa jarayon yozgan yangiroq qiymatni bosmasin.
        set_committed_value(device, "last_event_at", occurred_at)

    result = IngestResult(duplicate=False, event_id=event_id, person=person)
    if granted and device.marks_attendance and person is not None and person.active:
        record, created = await _apply_attendance(db, person, occurred_at, event_direction)
        result.attendance = record
        result.attendance_created = created
        if created:
            db.add(
                AuditLog(
                    user_id=None,
                    user_name="Turniket tizimi",
                    action=f"Turniket orqali davomat qayd etildi: {person.full_name} ({device.name})",
                    module="Talabalar",
                    status="muvaffaqiyatli",
                    ip="internal",
                )
            )
    await db.commit()

    if result.attendance_created and result.attendance is not None:
        await _announce(result.attendance, person, device)
    if not granted and local_now() - occurred_at <= ACCESS_DENIED_NOTIFY_MAX_AGE:
        await notify_access_denied(device.name, person.full_name if person else None, card_number, occurred_at)
    return result


async def _apply_attendance(
    db: AsyncSession, person: StudentStaff, occurred_at: datetime, direction: str | None
) -> tuple[AttendanceRecord | None, bool]:
    local = to_local(occurred_at)
    # Ish kuni 06:00 da almashadi — kamera yo'li bilan bir xil sana.
    record_date = business_date(occurred_at)
    moment = local.time().replace(microsecond=0)
    arrival_only = settings.attendance_arrival_only
    await load_policy(db)  # first_sighting_status va track_last_seen keshdan o'qiydi

    def _select():
        return (
            select(AttendanceRecord)
            .where(AttendanceRecord.student_staff_id == person.id)
            .where(AttendanceRecord.date == record_date)
        )

    def _arrival(event_direction: str | None) -> tuple[str, time_type | None]:
        # Talaba/xodim ish boshlanishi va dam olish kuni — attendance_policy.
        return first_sighting_status(moment, _reader(event_direction), person.type, record_date)

    existing = (await db.execute(_select())).scalar_one_or_none()
    if existing is None:
        if direction == "chiqish" and not arrival_only:
            # Chiqish — odam binoda bo'lgan, lekin qachon kelgani noma'lum.
            status, check_in, check_out = "keldi", None, moment
        else:
            # ATTENDANCE_ARRIVAL_ONLY: kelish — kunning birinchi ko'rinishi,
            # yo'nalishidan qat'i nazar (kamera yo'li bilan bir xil).
            status, check_in = _arrival(direction)
            check_out = None
        inserted = (
            await db.execute(
                insert(AttendanceRecord)
                .values(
                    student_staff_id=person.id,
                    date=record_date,
                    status=status,
                    check_in=check_in,
                    check_out=check_out,
                    source="turniket",
                )
                .on_conflict_do_nothing(index_elements=[AttendanceRecord.student_staff_id, AttendanceRecord.date])
                .returning(AttendanceRecord)
            )
        ).scalar_one_or_none()
        if inserted is not None:
            return inserted, True
        existing = (await db.execute(_select())).scalar_one()

    values = _attendance_changes(existing, moment, direction, arrival_only, _arrival)
    if not values:
        return existing, False
    record = (
        await db.execute(
            update(AttendanceRecord)
            .where(AttendanceRecord.id == existing.id)
            .where(AttendanceRecord.source.is_distinct_from("qolda"))
            .values(**values)
            .returning(AttendanceRecord)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return record or existing, False


def _attendance_changes(
    existing: AttendanceRecord,
    moment: time_type,
    direction: str | None,
    arrival_only: bool,
    arrival=None,
) -> dict[str, Any]:
    """Mavjud kunlik yozuvga keyingi turniket hodisasi nimani o'zgartiradi."""
    if arrival is None:
        def arrival(event_direction):
            return first_sighting_status(moment, _reader(event_direction))

    if existing.status == "dam_olish" or existing.source == "qolda":
        # Qo'lda tuzatilgan yozuv (operator qarori) turniketdan ustun.
        return {}
    key = business_seconds
    if arrival_only:
        # Kelish — birinchi ko'rinish (istalgan yo'nalish), ketish — oxirgi
        # ko'rinish (track_last_seen), kamera yo'li bilan bir xil.
        if existing.status == "kelmadi" or existing.check_in is None or key(moment) < key(existing.check_in):
            status, check_in = arrival(direction)
            return {"status": status, "check_in": check_in, "source": "turniket"}
        if not current_policy().track_last_seen:
            return {}
        if key(moment) <= key(existing.check_in) or (
            existing.check_out is not None and key(moment) <= key(existing.check_out)
        ):
            return {}
        return {"check_out": moment}
    if existing.status == "kelmadi":
        if direction == "chiqish":
            return {"status": "keldi", "check_in": None, "check_out": moment, "source": "turniket"}
        status, check_in = arrival(direction)
        return {"status": status, "check_in": check_in, "source": "turniket"}
    if direction == "kirish":
        if existing.check_in is None or key(moment) < key(existing.check_in):
            status, check_in = arrival(direction)
            return {"status": status, "check_in": check_in, "source": "turniket"}
        return {}
    # "chiqish" yoki yo'nalishi noma'lum qurilmadagi keyingi hodisa.
    if existing.check_in is not None and key(moment) <= key(existing.check_in):
        return {}
    if existing.check_out is not None and key(moment) <= key(existing.check_out):
        return {}
    return {"check_out": moment}


async def _announce(record: AttendanceRecord, person: StudentStaff, device: AccessDevice) -> None:
    """attendance_ai._announce_attendance bilan bir xil xabar — davomat
    sahifasi manbasidan qat'i nazar yangilanadi."""
    try:
        await manager.broadcast(
            {
                "kind": "attendance_recorded",
                "personId": str(record.student_staff_id),
                "fullName": person.full_name,
                "personType": person.type,
                "group": person.group_or_position,
                "status": record.status,
                "checkIn": record.check_in.strftime("%H:%M") if record.check_in else None,
                "date": record.date.isoformat(),
                "camera": device.name,
                "source": "turniket",
            }
        )
    except Exception:
        logger.warning("attendance announcement failed", exc_info=True)
    # Ota-onaga "keldi" xabari faqat bugungi kun uchun: kechikib so'ralgan
    # kechagi hodisa uchun hozir xabar yuborish chalg'itadi.
    if record.date == business_today():
        await notify_attendance(record, person, None)


async def ingest_many(db: AsyncSession, device: AccessDevice, events: list[NormalizedEvent]) -> dict[str, int]:
    """Bir nechta hodisa — vaqt tartibida (birinchi kirish check_in bo'lsin)."""
    counts = {"accepted": 0, "duplicates": 0, "matched": 0, "attendance": 0}
    for event in sorted(events, key=lambda e: e.occurred_at):
        result = await ingest_access_event(
            db,
            device,
            event.external_id,
            event.occurred_at,
            event.card_number,
            event.employee_no,
            event.direction,
            event.granted,
            event.raw,
        )
        if result.duplicate:
            counts["duplicates"] += 1
            continue
        counts["accepted"] += 1
        if result.person is not None:
            counts["matched"] += 1
        if result.attendance_created:
            counts["attendance"] += 1
    return counts
