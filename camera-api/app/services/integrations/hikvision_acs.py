"""Hikvision kirish nazorati qurilmalaridan (DS-K1T yuz terminallari,
DS-K2 kontrollerlar, turniketlar) hodisalarni ISAPI orqali so'rab olish.

    POST http://<ip>:<port>/ISAPI/AccessControl/AcsEvent?format=json
    {"AcsEventCond": {"searchID", "searchResultPosition", "maxResults",
                      "major": 5, "minor": 0, "startTime", "endTime"}}

Javob: {"AcsEvent": {"responseStatusStrg": "OK"|"MORE"|"NO MATCH",
"numOfMatches", "InfoList": [{"serialNo", "time", "minor", "cardNo",
"employeeNoString", "attendanceStatus", ...}]}} — "MORE" bo'lsa keyingi
sahifa (searchResultPosition += numOfMatches).

Autentifikatsiya — HTTP Digest (qurilma login/paroli, Fernet bilan
shifrlangan holda saqlanadi). Har so'rov oxirgi o'qilgan vaqtdan (poll
cursor) biroz orqadan boshlanadi: bir soniyada kelgan hodisa chegarada
qolib ketmasin. Takror hodisalar (device_id, external_id) unikalligi
bilan tashlanadi.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from xml.etree import ElementTree

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt
from app.models import AccessDevice
from app.services.integrations.access_control import (
    NormalizedEvent,
    clean_identifier,
    ingest_many,
    normalize_direction,
    parse_event_time,
)
from app.services.integrations.http import make_client
from app.timezone import INSTITUTE_TZ, local_now

logger = logging.getLogger("app.integrations.hikvision")

REQUEST_TIMEOUT_SECONDS = 10.0
PAGE_SIZE = 30  # ko'p qurilmalar 30 dan ko'pini bir so'rovda bermaydi
MAX_PAGES_PER_POLL = 200
# Oxirgi o'qilgan hodisadan shuncha orqadan qayta so'raladi.
CURSOR_OVERLAP = timedelta(seconds=60)
# Birinchi so'rov (yoki uzoq uzilishdan keyin) — ko'pi bilan shuncha orqaga.
MAX_BACKFILL = timedelta(days=3)

MAJOR_EVENT = 5

# Hikvision "minor" kodlari (major=5, hodisa). Faqat odam bilan bog'liq
# autentifikatsiya natijalari olinadi; eshik holati, signal, tugma va
# boshqa texnik hodisalar e'tiborsiz (ular davomat emas).
GRANTED_MINORS: dict[int, str] = {
    0x01: "Karta",  # MINOR_LEGAL_CARD_PASS
    0x02: "Karta + parol",  # MINOR_CARD_AND_PSW_PASS
    0x10: "Ko'p bosqichli tekshiruv",  # MINOR_MULTI_VERIFY_SUCCESS
    0x26: "Barmoq izi",  # MINOR_FINGERPRINT_COMPARE_PASS
    0x28: "Karta + barmoq izi",  # MINOR_CARD_FINGERPRINT_VERIFY_PASS
    0x2B: "Karta + barmoq izi + parol",
    0x2E: "Barmoq izi + parol",
    0x36: "Yuz + barmoq izi",
    0x39: "Yuz + parol",
    0x3C: "Yuz + karta",
    0x3F: "Yuz + parol + barmoq izi",
    0x42: "Yuz + karta + barmoq izi",
    0x45: "Xodim raqami + barmoq izi",
    0x48: "Xodim raqami + barmoq izi + parol",
    0x4B: "Yuz",  # MINOR_FACE_VERIFY_PASS (75) — yuz terminallarining asosiy hodisasi
    0x4D: "Xodim raqami + yuz",
    0x66: "Xodim raqami + parol",
    0x6A: "Shaxs va ID karta mos",
}
DENIED_MINORS: dict[int, str] = {
    0x03: "Karta + parol xato",
    0x04: "Karta + parol vaqti tugadi",
    0x06: "Kartaga ruxsat yo'q",  # MINOR_CARD_NO_RIGHT
    0x07: "Karta ruxsat vaqtidan tashqari",
    0x08: "Karta muddati o'tgan",
    0x09: "Noma'lum karta",  # MINOR_INVALID_CARD
    0x0A: "Anti-passback buzildi",
    0x0C: "Guruhga kirmaydi",
    0x0D: "Ko'p bosqichli tekshiruv vaqtidan tashqari",
    0x27: "Barmoq izi mos emas",
    0x29: "Karta + barmoq izi xato",
    0x2C: "Karta + barmoq izi + parol xato",
    0x2F: "Barmoq izi + parol xato",
    0x31: "Barmoq izi bazada yo'q",
    0x37: "Yuz + barmoq izi xato",
    0x3A: "Yuz + parol xato",
    0x3D: "Yuz + karta xato",
    0x40: "Yuz + parol + barmoq izi xato",
    0x43: "Yuz + karta + barmoq izi xato",
    0x46: "Xodim raqami + barmoq izi xato",
    0x49: "Xodim raqami + barmoq izi + parol xato",
    0x4C: "Yuz tanilmadi",  # MINOR_FACE_VERIFY_FAIL (76)
    0x4E: "Xodim raqami + yuz xato",
    0x50: "Yuzni aniqlash xatosi",
    0x67: "Xodim raqami + parol xato",
    0x6B: "Shaxs va ID karta mos emas",
}


class DeviceError(Exception):
    """Qurilma bilan aloqa xatosi — matni admin panelda ko'rinadi."""


def device_base_url(device: AccessDevice) -> str:
    if not device.ip:
        raise DeviceError("Qurilma IP manzili ko'rsatilmagan")
    host = device.ip.strip()
    if host.startswith(("http://", "https://")):
        return host.rstrip("/")
    port = device.port or 80
    scheme = "https" if port == 443 else "http"
    return f"{scheme}://{host}:{port}"


def _credentials(device: AccessDevice) -> httpx.DigestAuth:
    try:
        username = decrypt(device.username) if device.username else ""
        password = decrypt(device.password) if device.password else ""
    except ValueError as exc:
        raise DeviceError(str(exc)) from None
    if not username:
        raise DeviceError("Qurilma logini ko'rsatilmagan")
    return httpx.DigestAuth(username, password)


def _client(device: AccessDevice) -> httpx.AsyncClient:
    # Qurilmalar ichki tarmoqda, HTTPS'da o'z-o'zidan imzolangan sertifikat bilan.
    return make_client(timeout=REQUEST_TIMEOUT_SECONDS, auth=_credentials(device), verify=False)


def _http_error(response: httpx.Response) -> DeviceError:
    if response.status_code == 401:
        return DeviceError("Login yoki parol noto'g'ri (401)")
    if response.status_code == 403:
        return DeviceError("Foydalanuvchida bu amalga ruxsat yo'q (403)")
    if response.status_code == 404:
        return DeviceError("Qurilma bu ISAPI funksiyasini qo'llamaydi (404)")
    detail = ""
    try:
        payload = response.json()
        detail = str(payload.get("subStatusCode") or payload.get("statusString") or "")
    except ValueError:
        match = re.search(r"<subStatusCode>([^<]+)</subStatusCode>", response.text or "")
        detail = match.group(1) if match else ""
    return DeviceError(f"Qurilma xato qaytardi ({response.status_code}{', ' + detail if detail else ''})")


def _network_error(exc: httpx.HTTPError) -> DeviceError:
    if isinstance(exc, httpx.TimeoutException):
        return DeviceError(f"Qurilma javob bermadi ({REQUEST_TIMEOUT_SECONDS:.0f} s)")
    return DeviceError(f"Qurilmaga ulanib bo'lmadi: {type(exc).__name__}")


# ── Sof funksiyalar ─────────────────────────────────────────────────────────


def classify_minor(minor: Any) -> bool | None:
    """True — ruxsat berildi, False — rad etildi, None — odam hodisasi emas."""
    try:
        code = int(minor)
    except (TypeError, ValueError):
        return None
    if code in GRANTED_MINORS:
        return True
    if code in DENIED_MINORS:
        return False
    return None


def format_isapi_time(moment: datetime) -> str:
    """ISAPI vaqti: "2026-09-19T08:00:00+05:00" (qurilma mahalliy vaqtda ishlaydi)."""
    return moment.astimezone(INSTITUTE_TZ).replace(microsecond=0).isoformat()


def parse_acs_info(info: dict) -> NormalizedEvent | None:
    """InfoList elementi -> NormalizedEvent; odam hodisasi bo'lmasa None."""
    if not isinstance(info, dict):
        return None
    try:
        major = int(info.get("major", MAJOR_EVENT))
    except (TypeError, ValueError):
        major = MAJOR_EVENT
    if major != MAJOR_EVENT:
        return None
    granted = classify_minor(info.get("minor"))
    if granted is None:
        return None
    card = clean_identifier(info.get("cardNo"))
    employee = clean_identifier(info.get("employeeNoString") or info.get("employeeNo"))
    try:
        occurred_at = parse_event_time(info.get("time"))
    except ValueError:
        return None
    serial = clean_identifier(info.get("serialNo"))
    stamp = occurred_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S")
    # serialNo qurilma qayta tiklanganda (yoki jurnal tozalanganda) boshidan
    # boshlanadi — vaqt bilan birga olinadi, aks holda yangi hodisa eski
    # hodisaning "takrori" deb tashlanib ketardi.
    external = f"{serial}@{stamp}" if serial else f"{info.get('minor')}:{employee or card or '-'}@{stamp}"
    return NormalizedEvent(
        external_id=external,
        occurred_at=occurred_at,
        card_number=card,
        employee_no=employee,
        direction=normalize_direction(info.get("attendanceStatus")),
        granted=granted,
        raw={
            k: info.get(k)
            for k in ("serialNo", "time", "major", "minor", "cardNo", "employeeNoString", "name",
                      "attendanceStatus", "currentVerifyMode", "doorNo", "cardReaderNo")
            if info.get(k) is not None
        },
    )


def poll_start_time(device: AccessDevice, now: datetime) -> datetime:
    """Oxirgi o'qilgan hodisa vaqti (cursor), bo'lmasa oxirgi hodisa, bo'lmasa
    bugun 00:00 (institut vaqti) — overlap bilan, MAX_BACKFILL dan uzoq emas."""
    anchor: datetime | None = None
    if device.poll_cursor:
        try:
            anchor = parse_event_time(device.poll_cursor)
        except ValueError:
            anchor = None
    if anchor is None and device.last_event_at is not None:
        anchor = device.last_event_at
    if anchor is None:
        start = now.astimezone(INSTITUTE_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start = anchor - CURSOR_OVERLAP
    return max(start, now - MAX_BACKFILL)


# ── Tarmoq ──────────────────────────────────────────────────────────────────


async def fetch_events(device: AccessDevice, start: datetime, end: datetime) -> list[NormalizedEvent]:
    url = f"{device_base_url(device)}/ISAPI/AccessControl/AcsEvent?format=json"
    search_id = uuid.uuid4().hex
    position = 0
    events: list[NormalizedEvent] = []
    async with _client(device) as client:
        for _ in range(MAX_PAGES_PER_POLL):
            body = {
                "AcsEventCond": {
                    "searchID": search_id,
                    "searchResultPosition": position,
                    "maxResults": PAGE_SIZE,
                    "major": MAJOR_EVENT,
                    "minor": 0,
                    "startTime": format_isapi_time(start),
                    "endTime": format_isapi_time(end),
                }
            }
            try:
                response = await client.post(url, json=body)
            except httpx.HTTPError as exc:
                raise _network_error(exc) from None
            if response.status_code >= 400:
                raise _http_error(response)
            try:
                payload = response.json()
            except ValueError:
                raise DeviceError("Qurilma javobi JSON emas — ISAPI qo'llanadimi?") from None
            acs = payload.get("AcsEvent") if isinstance(payload, dict) else None
            if not isinstance(acs, dict):
                raise DeviceError("Qurilma javobida AcsEvent yo'q")
            infos = acs.get("InfoList") or []
            for info in infos if isinstance(infos, list) else []:
                event = parse_acs_info(info)
                if event is not None:
                    events.append(event)
            try:
                matches = int(acs.get("numOfMatches") or len(infos))
            except (TypeError, ValueError):
                matches = len(infos)
            if str(acs.get("responseStatusStrg", "")).upper() != "MORE" or matches <= 0:
                break
            position += matches
        else:
            logger.warning("ISAPI pagination limit reached", extra={"device_id": str(device.id)})
    return events


@dataclass
class PollResult:
    fetched: int = 0
    accepted: int = 0
    duplicates: int = 0
    error: str | None = None


async def poll_device(db: AsyncSession, device: AccessDevice) -> PollResult:
    """Bitta qurilma: hodisalarni olib, qabul qiladi, holatini yozadi.
    Istisno chiqarmaydi — xato device.last_error ga tushadi."""
    now = datetime.now(timezone.utc)
    start = poll_start_time(device, now)
    result = PollResult()
    try:
        events = await fetch_events(device, start, now)
        result.fetched = len(events)
        counts = await ingest_many(db, device, events)
        result.accepted = counts["accepted"]
        result.duplicates = counts["duplicates"]
        newest = max((e.occurred_at for e in events), default=None)
        # Hodisa bo'lmasa cursor joyida qoladi: qurilma soati serverdan
        # orqada bo'lsa, "hozir"ga surilgan cursor kechikib yozilgan
        # hodisani o'tkazib yuborardi. Oyna baribir oxirgi hodisadan
        # boshlanadi, ya'ni so'rov arzon.
        if newest is not None:
            previous = None
            if device.poll_cursor:
                try:
                    previous = parse_event_time(device.poll_cursor)
                except ValueError:
                    previous = None
            if previous is None or newest > previous:
                device.poll_cursor = format_isapi_time(newest)
        device.last_error = None
    except DeviceError as exc:
        result.error = str(exc)
        device.last_error = result.error
    except Exception as exc:  # noqa: BLE001 — bitta qurilma qolganlarini to'xtatmasin
        logger.exception("access device poll failed", extra={"device_id": str(device.id)})
        await db.rollback()
        result.error = f"Kutilmagan xato: {type(exc).__name__}"
        device = await db.get(AccessDevice, device.id) or device
        device.last_error = result.error
    device.last_poll_at = local_now()
    await db.commit()
    return result


def _xml_value(root: ElementTree.Element, tag: str) -> str | None:
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == tag and element.text:
            return element.text.strip()
    return None


async def fetch_device_info(device: AccessDevice) -> dict[str, str | None]:
    """GET /ISAPI/System/deviceInfo — ulanish va login/parolni tekshirish."""
    url = f"{device_base_url(device)}/ISAPI/System/deviceInfo"
    async with _client(device) as client:
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            raise _network_error(exc) from None
    if response.status_code >= 400:
        raise _http_error(response)
    try:
        root = ElementTree.fromstring(response.text)
    except ElementTree.ParseError:
        raise DeviceError("Qurilma javobi XML emas — bu Hikvision qurilmasimi?") from None
    return {
        "deviceName": _xml_value(root, "deviceName"),
        "model": _xml_value(root, "model"),
        "serialNumber": _xml_value(root, "serialNumber"),
        "firmwareVersion": _xml_value(root, "firmwareVersion"),
    }
