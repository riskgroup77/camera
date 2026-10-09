"""iMentor (server-server) integratsiyasi: talabani aniqlash.

    POST /api/v1/integration/students/lookup         {"student_id": "..."} | {"pinfl": "..."}
    POST /api/v1/integration/students/face-identify  multipart image | {"image_base64": "..."}
    GET  /api/v1/integration/health

Login/token iMentor tomonda; bu yerda faqat X-API-Key (settings.camfermi_integration_key,
timing-safe), ixtiyoriy IP ro'yxati (settings.integration_allowed_ips) va kalit
boshiga daqiqasiga N so'rov. Har so'rov audit jurnaliga yoziladi — JSHSHIR
niqoblangan (1234********34), rasm umuman yozilmaydi va diskka saqlanmaydi.
Xatolar: {"code": ..., "message": "o'zbekcha matn"}.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from limits import RateLimitItemPerMinute
from limits.storage import storage_from_string
from limits.aio.strategies import FixedWindowRateLimiter
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal, get_db
from app.models import AuditLog
from app.services import integration_students as svc

logger = logging.getLogger("app.integration")

router = APIRouter(prefix="/api/v1/integration", tags=["integration"])

AUDIT_USER = "iMentor (integratsiya)"
AUDIT_MODULE = "Integratsiya"
JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class IntegrationError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


async def integration_error_handler(_request: Request, exc: IntegrationError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": exc.message})


# ── Rate limit (kalit boshiga) ──────────────────────────────────────────────
_limiter: FixedWindowRateLimiter | None = None


def _get_limiter() -> FixedWindowRateLimiter:
    global _limiter
    if _limiter is None:
        # Redis bo'lsa — barcha worker'lar uchun bitta hisob (redis-py; coredis yo'q).
        redis = (settings.redis_url or "").strip()
        if redis.startswith(("redis://", "rediss://")):
            storage = storage_from_string("async+" + redis, implementation="redispy")
        else:
            storage = storage_from_string("async+memory://")
        _limiter = FixedWindowRateLimiter(storage)
    return _limiter


def reset_limiter_for_tests() -> None:
    global _limiter
    _limiter = None


async def _audit(request: Request, action: str, ok: bool) -> None:
    """Alohida sessiya: so'rov natijasidan qat'i nazar yoziladi. Xato — faqat log."""
    try:
        async with SessionLocal() as db:
            db.add(AuditLog(
                user_id=None, user_name=AUDIT_USER, module=AUDIT_MODULE,
                status="muvaffaqiyatli" if ok else "xato",
                ip=request.client.host if request.client else "unknown", action=action[:500],
            ))
            await db.commit()
    except Exception:
        logger.warning("integration audit write failed", exc_info=True)


def _ip_allowed(host: str | None) -> bool:
    allowed = [part.strip() for part in settings.integration_allowed_ips.split(",") if part.strip()]
    if not allowed:
        return True
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    for entry in allowed:
        try:
            if ip in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            logger.warning("bad INTEGRATION_ALLOWED_IPS entry", extra={"entry": entry})
    return False


async def require_integration_key(request: Request) -> None:
    key = settings.camfermi_integration_key
    provided = request.headers.get("x-api-key") or ""
    method = f"{request.method} {request.url.path.removeprefix(router.prefix)}"
    # Bo'sh kalit — API o'chiq; compare_digest bo'sh satrlarni ham teng deydi.
    if not key or not hmac.compare_digest(provided.encode(), key.encode()):
        await _audit(request, f"{method}: ruxsat yo'q (kalit noto'g'ri yoki yo'q)", ok=False)
        raise IntegrationError(401, "unauthorized", "API kaliti noto'g'ri yoki yuborilmagan")
    if not _ip_allowed(request.client.host if request.client else None):
        await _audit(request, f"{method}: IP ruxsat ro'yxatida yo'q", ok=False)
        raise IntegrationError(403, "forbidden", "Bu manzildan so'rov qabul qilinmaydi")
    bucket = hashlib.sha256(key.encode()).hexdigest()[:16]
    limit = RateLimitItemPerMinute(max(1, settings.integration_rate_limit_per_minute))
    if not await _get_limiter().hit(limit, "integration", bucket):
        await _audit(request, f"{method}: so'rovlar chegarasi oshdi", ok=False)
        raise IntegrationError(429, "rate_limited", "So'rovlar soni chegaradan oshdi — bir daqiqadan keyin urinib ko'ring")


Authorized = Annotated[None, Depends(require_integration_key)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except ValueError as exc:
        raise IntegrationError(400, "invalid_request", "So'rov tanasi JSON bo'lishi kerak") from exc
    if not isinstance(body, dict):
        raise IntegrationError(400, "invalid_request", "So'rov tanasi JSON obyekt bo'lishi kerak")
    return body


@router.get("/health")
async def health(_: Authorized) -> dict:
    return {"status": "ok", "service": "camfermi-integration"}


@router.post("/students/lookup")
async def lookup_student(request: Request, _: Authorized, db: DbDep) -> dict:
    body = await _json_body(request)
    student_id = str(body.get("student_id") or "").strip()
    pinfl = str(body.get("pinfl") or "").strip()
    if bool(student_id) == bool(pinfl):
        await _audit(request, "lookup: noto'g'ri so'rov (student_id yoki pinfl — faqat bittasi)", ok=False)
        raise IntegrationError(400, "invalid_request", "student_id yoki pinfl — faqat bittasi yuborilishi kerak")
    if pinfl:
        if not svc.PINFL_RE.match(pinfl):
            await _audit(request, f"lookup pinfl={svc.mask_pinfl(pinfl)}: noto'g'ri JSHSHIR", ok=False)
            raise IntegrationError(400, "invalid_pinfl", "JSHSHIR 14 xonali raqam bo'lishi kerak")
        person, matched_by, label = await svc.find_by_pinfl(db, pinfl), "pinfl", f"pinfl={svc.mask_pinfl(pinfl)}"
    else:
        person, matched_by, label = await svc.find_by_student_id(db, student_id), "student_id", f"student_id={student_id[:32]}"
    if person is None:
        await _audit(request, f"lookup {label}: topilmadi", ok=True)
        raise IntegrationError(404, "not_found", "Talaba topilmadi")
    await _audit(request, f"lookup {label}: topildi", ok=True)
    return svc.student_payload(person, matched_by=matched_by)


async def _read_image(request: Request) -> bytes:
    limit = settings.integration_max_image_bytes
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("image")
        if upload is None or not hasattr(upload, "read"):
            raise IntegrationError(400, "invalid_request", "multipart'da \"image\" fayli yuborilishi kerak")
        data = await upload.read(limit + 1)
    else:
        body = await _json_body(request)
        raw = str(body.get("image_base64") or "")
        if not raw:
            raise IntegrationError(400, "invalid_request", "image (multipart) yoki image_base64 (JSON) yuborilishi kerak")
        if raw.startswith("data:") and "," in raw:
            raw = raw.split(",", 1)[1]
        if len(raw) > (limit * 4) // 3 + 8:
            raise IntegrationError(413, "image_too_large", "Rasm 5 MB dan katta bo'lmasligi kerak")
        try:
            data = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise IntegrationError(400, "invalid_image", "image_base64 noto'g'ri") from exc
    if len(data) > limit:
        raise IntegrationError(413, "image_too_large", "Rasm 5 MB dan katta bo'lmasligi kerak")
    if not (data.startswith(JPEG_MAGIC) or data.startswith(PNG_MAGIC)):
        raise IntegrationError(415, "invalid_image", "Faqat JPEG yoki PNG rasm qabul qilinadi")
    return data


@router.post("/students/face-identify")
async def face_identify(request: Request, _: Authorized, db: DbDep) -> dict:
    try:
        image = await _read_image(request)
    except IntegrationError as exc:
        await _audit(request, f"face-identify: {exc.code}", ok=False)
        raise
    try:
        match = await svc.identify_face(db, image)
    except svc.IdentifyError as exc:
        await _audit(request, f"face-identify: {exc.code}", ok=exc.status == 404)
        raise IntegrationError(exc.status, exc.code, exc.message) from exc
    finally:
        del image  # rasm hech qayerga yozilmaydi
    await _audit(request, f"face-identify: topildi (ishonch {match.confidence:.2f})", ok=True)
    return svc.student_payload(match.person, matched_by="face", confidence=match.confidence)
