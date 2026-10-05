"""Administratorlar uchun ikki bosqichli kirish (2FA) majburiy."""

import pytest
from httpx import AsyncClient

from app.config import settings
from app.models import User
from app.security import hash_password
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _required(monkeypatch):
    monkeypatch.setattr(settings, "admin_2fa_required", True)


async def test_admin_without_2fa_can_only_reach_the_setup(client: AsyncClient, seeded):
    headers = await auth_headers(client, "admin", "admin123")
    blocked = await client.get("/api/events", headers=headers)
    assert blocked.status_code == 403 and blocked.headers.get("x-2fa-required") == "1"
    # Sessiya va 2FA sozlash ochiq — aks holda uni yoqib bo'lmasdi.
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["twoFactorRequired"] is True
    assert (await client.get("/api/auth/2fa", headers=headers)).status_code == 200
    assert (await client.post("/api/auth/2fa/boshlash", headers=headers)).status_code == 200


async def test_non_admin_roles_are_not_forced(client: AsyncClient, db_session, seeded):
    db_session.add(User(login="masul_2fa", password_hash=hash_password("masul-pass-123"), full_name="Mas'ul",
                        role="kamera-masuli"))
    await db_session.commit()
    headers = await auth_headers(client, "masul_2fa", "masul-pass-123")
    me = (await client.get("/api/auth/me", headers=headers)).json()
    assert me["twoFactorRequired"] is False
    assert (await client.get("/api/cameras", headers=headers)).status_code != 403


async def test_admin_with_2fa_is_not_blocked(db_session, seeded):
    from sqlalchemy import select

    from app.dependencies import ensure_two_factor, user_from_token
    from app.security import create_access_token

    admin = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
    admin.totp_enabled = True
    await db_session.commit()
    user = await user_from_token(create_access_token(str(admin.id), admin.role, admin.token_version), db_session)
    assert user.needs_2fa_setup is False
    assert ensure_two_factor(user, "/api/events") is user
