import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(hashed: str, plain: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: str, role: str, token_version: int = 0) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "ver": token_version,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_ttl_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


class TokenPayload:
    def __init__(self, user_id: str, role: str, token_version: int, jti: str, expires_at: datetime) -> None:
        self.user_id = user_id
        self.role = role
        self.token_version = token_version
        self.jti = jti
        self.expires_at = expires_at


def decode_access_token(token: str) -> TokenPayload:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    # Ikkinchi himoya qatlami: 2FA chaqiruv tokeni boshqa kalit bilan
    # imzolanadi, shuning uchun bu yerga yetib kelmaydi. Lekin kelajakda
    # kimdir yangi "maqsadli" token chiqarib, uni asosiy kalit bilan
    # imzolasa ham, u to'liq sessiya o'rnida ishlamasin.
    if "purpose" in payload:
        raise jwt.InvalidTokenError("maqsadli token sessiya o'rnida ishlatilmaydi")
    if "role" not in payload or "sub" not in payload:
        raise jwt.InvalidTokenError("token tarkibi to'liq emas")
    return TokenPayload(
        user_id=payload["sub"],
        role=payload["role"],
        # Eski (ushbu o'zgarishdan oldin chiqarilgan) tokenlarda bu maydonlar
        # yo'q — ularni yaroqsiz deb hisoblamaslik uchun xavfsiz standart
        # qiymatlar bilan o'qiymiz (ver=0, jti=doim yangi tasodifiy qiymat,
        # ya'ni blocklist'da hech qachon topilmaydi).
        token_version=payload.get("ver", 0),
        jti=payload.get("jti", str(uuid.uuid4())),
        expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
    )


# --- Ikki bosqichli kirish: chaqiruv (challenge) tokeni -------------------
#
# Parol to'g'ri, lekin 2FA yoqilgan bo'lsa, login to'liq sessiya o'rniga shu
# qisqa muddatli tokenni beradi. U FAQAT POST /api/auth/2fa/kirish uchun:
#   * alohida kalit bilan imzolanadi (jwt_secret'dan HMAC orqali olingan) —
#     access token tekshiruvi uni imzo darajasida rad etadi;
#   * "purpose" va "aud" claim'lari bor — boshqa maqsadga yaramaydi;
#   * 5 daqiqa yashaydi va bir martalik (jti revoked_tokens'ga yoziladi);
#   * token_version'ni o'zida saqlaydi — shu orada parol almashtirilsa,
#     eski parol bilan olingan chaqiruv ham kuyadi.

TWO_FACTOR_CHALLENGE_TTL = timedelta(minutes=5)
_CHALLENGE_PURPOSE = "2fa-kirish"
_CHALLENGE_AUDIENCE = "camera-api:2fa"


def _challenge_key() -> bytes:
    return hmac.new(settings.jwt_secret.encode("utf-8"), b"2fa-challenge-v1", hashlib.sha256).digest()


class ChallengePayload:
    def __init__(self, user_id: str, token_version: int, jti: str, expires_at: datetime) -> None:
        self.user_id = user_id
        self.token_version = token_version
        self.jti = jti
        self.expires_at = expires_at


def create_two_factor_challenge(user_id: str, token_version: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "purpose": _CHALLENGE_PURPOSE,
        "aud": _CHALLENGE_AUDIENCE,
        "ver": token_version,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + TWO_FACTOR_CHALLENGE_TTL,
    }
    return jwt.encode(payload, _challenge_key(), algorithm="HS256")


def decode_two_factor_challenge(token: str) -> ChallengePayload:
    payload = jwt.decode(
        token,
        _challenge_key(),
        algorithms=["HS256"],
        audience=_CHALLENGE_AUDIENCE,
        options={"require": ["exp", "sub", "jti", "aud"]},
    )
    if payload.get("purpose") != _CHALLENGE_PURPOSE:
        raise jwt.InvalidTokenError("noto'g'ri maqsad")
    return ChallengePayload(
        user_id=payload["sub"],
        token_version=int(payload.get("ver", 0)),
        jti=payload["jti"],
        expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
    )
