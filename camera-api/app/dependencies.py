from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Permission, RevokedToken, User
from app.security import TokenPayload, decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser:
    def __init__(self, id: str, role: str, jti: str, expires_at) -> None:
        self.id = id
        self.role = role
        self.jti = jti
        self.expires_at = expires_at


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Autentifikatsiya talab qilinadi")
    try:
        payload: TokenPayload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token yaroqsiz yoki muddati tugagan") from exc

    # Chiqish (logout) qilingan token — blocklist'da.
    revoked = await db.get(RevokedToken, payload.jti)
    if revoked is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessiya tugatilgan — qayta kiring")

    # Parol o'zgargan yoki hisob bloklangan bo'lsa token_version oshiriladi —
    # eski token (hatto muddati tugamagan bo'lsa ham) shu yerda yaroqsiz bo'ladi.
    user = await db.get(User, payload.user_id)
    if user is None or user.token_version != payload.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessiya tugatilgan — qayta kiring")

    return CurrentUser(id=payload.user_id, role=payload.role, jti=payload.jti, expires_at=payload.expires_at)


def require_permission(key: str):
    """Server-side equivalent of the frontend's usePermissions().can(key, role) —
    this is the real security boundary; the frontend's own check is UX-only.
    """

    async def checker(
        current_user: Annotated[CurrentUser, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> CurrentUser:
        column = Permission.super_admin if current_user.role == "super-admin" else Permission.admin
        result = await db.execute(select(column).where(Permission.key == key))
        allowed = result.scalar_one_or_none()
        if not allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Sizda bu amal uchun huquq yo'q")
        return current_user

    return checker
