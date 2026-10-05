"""TOTP (RFC 6238) — ikki bosqichli kirish kodlari.

Tashqi kutubxonasiz, faqat standart kutubxona: HMAC-SHA1, 30 soniyalik
qadam, 6 raqam. Google Authenticator, Microsoft Authenticator, Aegis va
boshqa ilovalar aynan shu standart qiymatlarni kutadi — boshqasini
(SHA256, 8 raqam) tanlasak, ba'zi ilovalar URI'dagi parametrni
e'tiborsiz qoldirib, noto'g'ri kod ko'rsatadi.

Soat farqi uchun ±1 qadam (ya'ni ±30 soniya) qabul qilinadi: telefon
soati bir oz orqada yoki oldinda bo'lishi odatiy hol.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

STEP_SECONDS = 30
DIGITS = 6
# Soat farqi uchun qo'shni qadamlar soni (har tomonga).
DRIFT_STEPS = 1

# Soat manbai — testlar vaqtni shu orqali boshqaradi (time.time'ni butun
# jarayon uchun almashtirmasdan).
_clock = time.time


def generate_secret() -> str:
    """160 bitli tasodifiy sir, base32 (paddingsiz) — RFC 4226 tavsiyasi."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    cleaned = secret.replace(" ", "").upper()
    return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))


def current_step(now: float | None = None) -> int:
    return int((_clock() if now is None else now) // STEP_SECONDS)


def code_at(secret: str, step: int) -> str:
    """RFC 4226 HOTP — berilgan qadam uchun kod."""
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10**DIGITS)).zfill(DIGITS)


def normalize_code(code: str | None) -> str | None:
    """Foydalanuvchi "123 456" yoki "123-456" deb yozishi mumkin."""
    if code is None:
        return None
    cleaned = "".join(ch for ch in code if ch not in " -")
    if len(cleaned) != DIGITS or not cleaned.isdigit():
        return None
    return cleaned


def verify(secret: str, code: str | None, *, last_step: int | None = None, now: float | None = None) -> int | None:
    """Kod to'g'ri bo'lsa — mos kelgan qadam raqami, aks holda None.

    `last_step` dan katta bo'lmagan qadam qabul qilinmaydi: bir marta
    ishlatilgan kod (yoki undan eskisi) qayta kirish uchun yaramaydi.
    Barcha nomzodlar solishtiriladi (birinchi moslikda to'xtamaydi) va
    solishtirish doimiy vaqtli — javob vaqti qaysi qadam mos kelganini
    oshkor qilmasin."""
    cleaned = normalize_code(code)
    if cleaned is None:
        return None
    center = current_step(now)
    matched: int | None = None
    for step in range(center - DRIFT_STEPS, center + DRIFT_STEPS + 1):
        if hmac.compare_digest(code_at(secret, step), cleaned) and matched is None:
            matched = step
    if matched is None or (last_step is not None and matched <= last_step):
        return None
    return matched


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    """otpauth:// URI — QR-kod shu satrdan chiziladi (Key URI Format)."""
    label = quote(f"{issuer}:{account}", safe="")
    params = urlencode(
        {"secret": secret, "issuer": issuer, "algorithm": "SHA1", "digits": DIGITS, "period": STEP_SECONDS},
        quote_via=quote,
    )
    return f"otpauth://totp/{label}?{params}"
