"""Hisobotlar bo'limi paroli (2026-09-26, institut talabi).

Hisobot sahifasi (/api/hisobot, /api/kpi, /api/hisobot-jadval) ochilishidan
oldin alohida parol so'raladi. Parol faqat xesh ko'rinishida — serverning
.env faylida (REPORT_PASSWORD_HASH, `pbkdf2:<iter>:<salt>:<hash>` — "$"
belgisisiz, docker env_file uni o'zgartirmasin). Frontend kodida parol yo'q.

To'g'ri parol — shu foydalanuvchi uchun report_unlock_hours soatlik kalit
(JWT, alohida kalit bilan imzolangan); brauzer uni X-Report-Token sarlavhasida
yuboradi. REPORT_PASSWORD_HASH bo'sh bo'lsa — qulf o'chiq (testlar, boshqa
o'rnatishlar).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.config import settings
from app.dependencies import CurrentUser, get_current_user, require_permission
from app.rate_limit import limiter
from app.schemas.base import CamelModel

router = APIRouter(prefix="/api/hisobot-kirish", tags=["hisobot"])
PURPOSE = "report-unlock"
HEADER = "X-Report-Token"
ITERATIONS = 200_000


def hash_report_password(plain: str, *, salt: str | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), bytes.fromhex(salt), iterations).hex()
    return f"pbkdf2:{iterations}:{salt}:{digest}"


def verify_report_password(stored: str, plain: str) -> bool:
    try:
        scheme, iterations, salt, digest = stored.split(":")
        if scheme != "pbkdf2":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), bytes.fromhex(salt), int(iterations)).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, digest)


def _key() -> bytes:
    return hmac.new(settings.jwt_secret.encode("utf-8"), b"report-unlock-v1", hashlib.sha256).digest()


def create_report_token(user_id: str) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=settings.report_unlock_hours)
    token = jwt.encode({"sub": str(user_id), "purpose": PURPOSE, "iat": now, "exp": expires}, _key(), algorithm="HS256")
    return token, expires


def report_locked() -> bool:
    return bool(settings.report_password_hash.strip())


async def require_report_unlock(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    token: Annotated[str | None, Header(alias=HEADER)] = None,
) -> None:
    """Hisobot endpointlari uchun: qulf yoqilgan bo'lsa — shu foydalanuvchining
    amaldagi kaliti bo'lishi shart."""
    if not report_locked():
        return
    if token:
        try:
            payload = jwt.decode(token, _key(), algorithms=["HS256"], options={"require": ["exp", "sub"]})
            if payload.get("purpose") == PURPOSE and payload.get("sub") == str(user.id):
                return
        except jwt.InvalidTokenError:
            pass
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Hisobotlar uchun parol kiriting", headers={"X-Report-Locked": "1"})


class UnlockIn(CamelModel):
    password: str


class UnlockOut(CamelModel):
    token: str | None
    expires_at: datetime | None
    locked: bool


@router.get("", response_model=UnlockOut)
async def lock_state(_: Annotated[CurrentUser, Depends(require_permission("viewReports"))]) -> UnlockOut:
    """Qulf yoqilganmi (frontend parol oynasini ko'rsatadimi)."""
    return UnlockOut(token=None, expires_at=None, locked=report_locked())


@router.post("", response_model=UnlockOut)
@limiter.limit("5/minute")
async def unlock(
    request: Request,
    body: UnlockIn,
    user: Annotated[CurrentUser, Depends(require_permission("viewReports"))],
) -> UnlockOut:
    if not report_locked():
        return UnlockOut(token=None, expires_at=None, locked=False)
    if not verify_report_password(settings.report_password_hash.strip(), body.password or ""):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Parol noto'g'ri")
    token, expires = create_report_token(str(user.id))
    return UnlockOut(token=token, expires_at=expires, locked=True)
