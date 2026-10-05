"""SMS — Eskiz.uz (notify.eskiz.uz) orqali.

Eskiz tokeni 30 kun amal qiladi: bir marta olinadi va xotirada saqlanadi,
401 kelganda qayta olinadi. Raqam O'zbekiston formatida: +998XXXXXXXXX
(Eskiz'ga '+' siz yuboriladi).
"""

import asyncio
import logging
import re
import time

import httpx

from app.config import settings
from app.services.notifications.http import make_client, redact
from app.services.notifications.telegram import SendResult

logger = logging.getLogger("app.notifications.sms")

# Eskiz bitta SMS uchun 918 belgigacha qabul qiladi (6 qism); undan uzunini
# qisqartiramiz — har qism alohida pullik.
SMS_MAX_LENGTH = 480
# Token 30 kun amal qiladi — ehtiyot uchun 29 kundan keyin yangilanadi.
TOKEN_TTL_SECONDS = 29 * 24 * 3600

_token: tuple[str, float] | None = None
_token_lock = asyncio.Lock()

# Operator/hudud kodi ham tekshiriladi: ilgari istalgan 9 raqam raqam
# sifatida qabul qilinardi va Telegram ID (masalan 123456789)
# "+998123456789" bo'lib SMS ro'yxatiga tushib ketardi.
_UZ_PHONE_RE = re.compile(r"^998(20|33|50|55|6[1-9]|7[0-9]|88|9[0-9])\d{7}$")


def normalize_phone(raw: str | None) -> str | None:
    """O'zbekiston raqamini '+998XXXXXXXXX' ko'rinishiga keltiradi.

    Qabul qilinadi: '+998 90 123-45-67', '998901234567', '90 123 45 67'
    (9 raqam — operator kodi bilan), '8 90 123 45 67' (eski ichki format).
    Boshqa hamma narsa — None (yaroqsiz)."""
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 9:
        digits = "998" + digits
    elif len(digits) == 10 and digits.startswith("8"):
        digits = "998" + digits[1:]
    if not _UZ_PHONE_RE.match(digits):
        return None
    return "+" + digits


def is_configured() -> bool:
    return settings.sms_provider == "eskiz" and bool(settings.eskiz_email and settings.eskiz_password)


def _base() -> str:
    return settings.eskiz_base_url.rstrip("/")


def _safe(text: str) -> str:
    return redact(text, settings.eskiz_password, _token[0] if _token else "")


async def _login(client: httpx.AsyncClient) -> str:
    global _token
    response = await client.post(
        f"{_base()}/auth/login",
        data={"email": settings.eskiz_email, "password": settings.eskiz_password},
    )
    if response.status_code != 200:
        raise RuntimeError(f"Eskiz avtorizatsiyasi rad etildi (HTTP {response.status_code})")
    try:
        token = response.json()["data"]["token"]
    except (ValueError, KeyError, TypeError):
        raise RuntimeError("Eskiz avtorizatsiya javobi tushunarsiz") from None
    _token = (token, time.monotonic() + TOKEN_TTL_SECONDS)
    return token


async def _get_token(client: httpx.AsyncClient, *, force: bool = False) -> str:
    async with _token_lock:
        if not force and _token is not None and _token[1] > time.monotonic():
            return _token[0]
        return await _login(client)


def _truncate(text: str) -> str:
    return text if len(text) <= SMS_MAX_LENGTH else text[: SMS_MAX_LENGTH - 1] + "…"


async def send_sms(phone: str, text: str) -> SendResult:
    if not is_configured():
        return SendResult(ok=False, error="SMS xizmati sozlanmagan (SMS_PROVIDER=eskiz, ESKIZ_EMAIL/PASSWORD)")
    normalized = normalize_phone(phone)
    if normalized is None:
        return SendResult(ok=False, error=f"Telefon raqami noto'g'ri: {phone}")
    body = {"mobile_phone": normalized.lstrip("+"), "message": _truncate(text), "from": settings.eskiz_sender}
    try:
        async with make_client() as client:
            token = await _get_token(client)
            response = await client.post(
                f"{_base()}/message/sms/send", data=body, headers={"Authorization": f"Bearer {token}"}
            )
            if response.status_code == 401:
                # Token muddati tugagan yoki bekor qilingan — bir marta yangilab qayta.
                token = await _get_token(client, force=True)
                response = await client.post(
                    f"{_base()}/message/sms/send", data=body, headers={"Authorization": f"Bearer {token}"}
                )
    except httpx.TimeoutException:
        return SendResult(ok=False, error="Eskiz javob bermadi (timeout)")
    except httpx.HTTPError as exc:
        return SendResult(ok=False, error=_safe(f"Eskiz bilan aloqa xatosi: {type(exc).__name__} {exc}"))
    except RuntimeError as exc:
        return SendResult(ok=False, error=_safe(str(exc)))

    if 200 <= response.status_code < 300:
        return SendResult(ok=True)
    try:
        payload = response.json()
        detail = payload.get("message") or payload.get("status") or ""
        if isinstance(detail, dict):
            detail = "; ".join(f"{k}: {v}" for k, v in detail.items())
    except ValueError:
        detail = ""
    return SendResult(ok=False, error=_safe(f"Eskiz xatosi (HTTP {response.status_code}) {detail}".strip()))


def reset_token_for_tests() -> None:
    global _token
    _token = None
