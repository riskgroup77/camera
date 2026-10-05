"""Telegram va SMS mijozlari uchun umumiy httpx sozlamasi.

Testlar tashqi xizmatga hech qachon murojaat qilmasligi uchun transport
bitta joydan almashtiriladi (httpx.MockTransport) — set_transport_for_tests.
"""

import httpx

from app.config import settings

_transport: httpx.AsyncBaseTransport | None = None


def set_transport_for_tests(transport: httpx.AsyncBaseTransport | None) -> None:
    """Faqat testlar uchun: barcha tashqi so'rovlar shu transport orqali o'tadi."""
    global _transport
    _transport = transport


def make_client(timeout: float | None = None) -> httpx.AsyncClient:
    seconds = timeout if timeout is not None else settings.notification_timeout_seconds
    return httpx.AsyncClient(
        transport=_transport,
        timeout=httpx.Timeout(seconds, connect=min(seconds, 10.0)),
        follow_redirects=False,
    )


def redact(message: str, *secrets: str) -> str:
    """Xato matnidan maxfiy qiymatlarni olib tashlaydi.

    httpx istisnosi so'rov URL'ini o'z ichiga oladi, Telegram URL'ida esa
    bot tokeni bor (…/bot<token>/sendMessage). Bu matn notification_log'ga
    va server logiga yoziladi — token u yerga tushmasligi shart."""
    for secret in secrets:
        if secret:
            message = message.replace(secret, "***")
    return message
