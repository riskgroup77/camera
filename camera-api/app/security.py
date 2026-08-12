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
