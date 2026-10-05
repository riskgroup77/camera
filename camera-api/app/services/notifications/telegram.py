"""Telegram Bot API mijozi (sendMessage, sendPhoto, sendDocument, getUpdates, getMe).

Hech bir funksiya istisno ko'tarmaydi (get_updates bundan mustasno —
bot sikli o'zi qayta urinadi): natija SendResult bo'lib qaytadi va
dispatcher uni notification_log'ga yozadi.
"""

import asyncio
import html as html_lib
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.services.notifications.http import make_client, redact

logger = logging.getLogger("app.notifications.telegram")


class _RedactBotToken(logging.Filter):
    """httpx har bir so'rovni INFO darajasida to'liq URL bilan loglaydi, bot
    tokeni esa URL ichida (…/bot<token>/sendMessage). Token server logiga
    tushmasligi uchun xabardan olib tashlanadi."""

    def filter(self, record: logging.LogRecord) -> bool:
        token = settings.telegram_bot_token
        if token:
            try:
                message = record.getMessage()
            except Exception:
                return True
            if token in message:
                record.msg = message.replace(token, "***")
                record.args = ()
        return True


logging.getLogger("httpx").addFilter(_RedactBotToken())

# Telegram cheklovlari: xabar matni 4096, rasm izohi 1024 belgi.
MESSAGE_LIMIT = 4096
CAPTION_LIMIT = 1024
# 429 javobidagi retry_after shu qiymatdan oshsa kutmaymiz — fondagi
# vazifa daqiqalab osilib qolmasin.
MAX_RETRY_AFTER_SECONDS = 30
MAX_ATTEMPTS = 3

# Testlar kutishni o'chirib qo'yishi uchun alohida nom.
_sleep = asyncio.sleep


@dataclass(frozen=True)
class SendResult:
    ok: bool
    error: str | None = None
    # Foydalanuvchi botni bloklagan yoki chat yo'q (403 / "chat not found") —
    # bu manzilga qayta yuborishdan foyda yo'q.
    blocked: bool = False
    # Javob kelmadi (timeout — xabar yetib borgan bo'lishi mumkin) yoki
    # Telegram cheklovi (429): boshqa kanalga (SMS) almashtirilmaydi — aks
    # holda ota-ona bir xabarni ikki marta oladi va har biri pullik SMS.
    no_fallback: bool = False


class TelegramError(Exception):
    def __init__(self, message: str, *, status: int | None = None, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def is_configured() -> bool:
    return bool(settings.telegram_bot_token)


def _url(method: str) -> str:
    base = settings.telegram_api_base_url.rstrip("/")
    return f"{base}/bot{settings.telegram_bot_token}/{method}"


def _safe(text: str) -> str:
    return redact(text, settings.telegram_bot_token)


async def _call(
    method: str,
    *,
    json: dict | None = None,
    data: dict | None = None,
    files: dict | None = None,
    timeout: float | None = None,
) -> Any:
    """Bitta API chaqiruv. Muvaffaqiyatli bo'lsa `result` maydonini qaytaradi,
    aks holda TelegramError (matnida token bo'lmaydi)."""
    try:
        async with make_client(timeout) as client:
            response = await client.post(_url(method), json=json, data=data, files=files)
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        # Ulanib bo'lmadi — so'rov Telegram'ga yetmagan, qayta urinish xavfsiz
        # (status=None).
        raise TelegramError(_safe(f"Telegram bilan ulanib bo'lmadi: {type(exc).__name__} {exc}")) from None
    except httpx.TimeoutException as exc:
        # Javob kelmadi — xabar yetib borgan bo'lishi mumkin, takror yubormaymiz.
        raise TelegramError(f"Telegram javob bermadi (timeout): {type(exc).__name__}", status=0) from None
    except httpx.HTTPError as exc:
        raise TelegramError(_safe(f"Telegram bilan aloqa xatosi: {exc}"), status=0) from None

    try:
        payload = response.json()
    except ValueError:
        raise TelegramError(f"Telegram noto'g'ri javob qaytardi (HTTP {response.status_code})", status=response.status_code) from None

    if response.status_code == 200 and payload.get("ok"):
        return payload.get("result")

    description = _safe(str(payload.get("description") or f"HTTP {response.status_code}"))
    code = payload.get("error_code") or response.status_code
    retry_after = (payload.get("parameters") or {}).get("retry_after")
    raise TelegramError(description, status=int(code), retry_after=int(retry_after) if retry_after else None)


def _is_blocked(exc: TelegramError) -> bool:
    text = str(exc).lower()
    return exc.status == 403 or "chat not found" in text or "user is deactivated" in text


def _is_parse_error(exc: TelegramError) -> bool:
    return exc.status == 400 and "parse" in str(exc).lower()


async def _with_retry(method: str, **kwargs: Any) -> SendResult:
    """429 (juda ko'p so'rov) — Telegram aytgan vaqt kutiladi va qayta
    uriniladi; 403 — bot bloklangan, qayta urinilmaydi."""
    if not is_configured():
        return SendResult(ok=False, error="Telegram bot sozlanmagan (TELEGRAM_BOT_TOKEN)")
    last_error = "Noma'lum xato"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            await _call(method, **kwargs)
            return SendResult(ok=True)
        except TelegramError as exc:
            last_error = str(exc)
            if _is_blocked(exc):
                return SendResult(ok=False, error=f"Bot bloklangan yoki chat topilmadi: {exc}", blocked=True)
            if exc.status == 429 and attempt < MAX_ATTEMPTS:
                wait = min(exc.retry_after or 1, MAX_RETRY_AFTER_SECONDS)
                if (exc.retry_after or 0) > MAX_RETRY_AFTER_SECONDS:
                    return SendResult(
                        ok=False, error=f"Telegram cheklovi: {exc.retry_after} s kutish kerak", no_fallback=True
                    )
                await _sleep(wait)
                continue
            if exc.status is None and attempt < MAX_ATTEMPTS:
                # Tarmoq xatosi — qisqa kutib yana bir bor.
                await _sleep(attempt)
                continue
            if _is_parse_error(exc) and (kwargs.get("json") or {}).get("parse_mode"):
                # HTML belgilash rad etildi (masalan, havola manzili) — oddiy
                # matn sifatida yuboramiz: xabar yetib borishi muhimroq.
                plain = dict(kwargs["json"])
                plain.pop("parse_mode", None)
                plain["text"] = strip_html(plain.get("text", ""))
                kwargs = {**kwargs, "json": plain}
                continue
            return SendResult(ok=False, error=last_error, no_fallback=exc.status in (0, 429))
    return SendResult(ok=False, error=last_error)


_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    return html_lib.unescape(_TAG_RE.sub("", text))


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def send_message(chat_id: str | int, text: str, *, html: bool = True) -> SendResult:
    body: dict[str, Any] = {
        "chat_id": chat_id,
        "text": _truncate(text, MESSAGE_LIMIT),
        "disable_web_page_preview": True,
    }
    if html:
        body["parse_mode"] = "HTML"
    return await _with_retry("sendMessage", json=body)


async def send_photo(chat_id: str | int, photo: bytes, caption: str, *, filename: str = "hodisa.jpg") -> SendResult:
    """Hodisa kadri bilan xabar. Izoh 1024 belgidan uzun bo'lsa qisqartiriladi.

    Rasm yuborilmasa (hajm, format) — chaqiruvchi oddiy matnga qaytadi."""
    if not is_configured():
        return SendResult(ok=False, error="Telegram bot sozlanmagan (TELEGRAM_BOT_TOKEN)")
    data = {"chat_id": str(chat_id), "caption": _truncate(caption, CAPTION_LIMIT), "parse_mode": "HTML"}
    last_error = "Noma'lum xato"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            await _call("sendPhoto", data=data, files={"photo": (filename, photo, "image/jpeg")})
            return SendResult(ok=True)
        except TelegramError as exc:
            last_error = str(exc)
            if _is_blocked(exc):
                return SendResult(ok=False, error=f"Bot bloklangan yoki chat topilmadi: {exc}", blocked=True)
            if exc.status == 429 and attempt < MAX_ATTEMPTS and (exc.retry_after or 0) <= MAX_RETRY_AFTER_SECONDS:
                await _sleep(exc.retry_after or 1)
                continue
            return SendResult(ok=False, error=last_error)
    return SendResult(ok=False, error=last_error)


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def send_document(
    chat_id: str | int, content: bytes, filename: str, caption: str, *, mime: str = XLSX_MIME
) -> SendResult:
    """Fayl (masalan, Excel hisobot) izoh bilan. Avtomatik hisobotlar
    (app/services/report_schedule.py) shu orqali yuboriladi. Qayta urinish
    qoidasi send_photo bilan bir xil: timeout'da takror yuborilmaydi —
    rahbarga bir hisobot ikki marta kelmasin."""
    if not is_configured():
        return SendResult(ok=False, error="Telegram bot sozlanmagan (TELEGRAM_BOT_TOKEN)")
    data = {"chat_id": str(chat_id), "caption": _truncate(caption, CAPTION_LIMIT), "parse_mode": "HTML"}
    last_error = "Noma'lum xato"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            await _call("sendDocument", data=data, files={"document": (filename, content, mime)}, timeout=60)
            return SendResult(ok=True)
        except TelegramError as exc:
            last_error = str(exc)
            if _is_blocked(exc):
                return SendResult(ok=False, error=f"Bot bloklangan yoki chat topilmadi: {exc}", blocked=True)
            if exc.status == 429 and attempt < MAX_ATTEMPTS and (exc.retry_after or 0) <= MAX_RETRY_AFTER_SECONDS:
                await _sleep(exc.retry_after or 1)
                continue
            if exc.status is None and attempt < MAX_ATTEMPTS:
                await _sleep(attempt)
                continue
            return SendResult(ok=False, error=last_error)
    return SendResult(ok=False, error=last_error)


async def get_updates(offset: int | None, timeout: int = 25) -> list[dict]:
    """Long polling. Xato bo'lsa TelegramError — bot sikli qayta urinadi."""
    body: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
    if offset is not None:
        body["offset"] = offset
    # HTTP kutish vaqti Telegram'ning o'z kutishidan uzunroq bo'lishi shart.
    result = await _call("getUpdates", json=body, timeout=timeout + 10)
    return list(result or [])


_bot_username_cache: tuple[str, float] | None = None
_BOT_USERNAME_TTL = 3600.0
_BOT_USERNAME_FAILURE_TTL = 60.0


async def bot_username() -> str | None:
    """Bog'lash havolasi (t.me/<bot>) uchun. Sozlamada bo'lsa — o'sha,
    aks holda getMe (bir soat keshlanadi)."""
    global _bot_username_cache
    if settings.telegram_bot_username:
        return settings.telegram_bot_username.lstrip("@")
    if not is_configured():
        return None
    now = time.monotonic()
    if _bot_username_cache is not None and _bot_username_cache[1] > now:
        return _bot_username_cache[0] or None
    try:
        me = await _call("getMe")
    except TelegramError as exc:
        logger.warning("telegram getMe failed", extra={"error": str(exc)})
        # Xato ham qisqa muddat eslab qolinadi — holat sahifasi har ochilganda
        # javob bermayotgan Telegram'ni kutib qolmasin.
        _bot_username_cache = ("", now + _BOT_USERNAME_FAILURE_TTL)
        return None
    username = (me or {}).get("username") or ""
    _bot_username_cache = (username, now + (_BOT_USERNAME_TTL if username else _BOT_USERNAME_FAILURE_TTL))
    return username or None


def reset_cache_for_tests() -> None:
    global _bot_username_cache
    _bot_username_cache = None
