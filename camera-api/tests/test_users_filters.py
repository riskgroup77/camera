"""Foydalanuvchilar ro'yxati: qidiruv, rol va xavf filtrlari."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.models import User
from app.security import hash_password
from tests.conftest import auth_headers


@pytest.mark.usefixtures("seeded")
async def test_search_role_and_risk_filters(client: AsyncClient, db_session):
    now = datetime.now(timezone.utc)
    db_session.add_all([
        User(login="eski_admin", password_hash=hash_password("x-pass-1234"), full_name="Eski Admin", role="admin",
             last_login_at=now - timedelta(days=120)),
        User(login="yangi_masul", password_hash=hash_password("x-pass-1234"), full_name="Yangi Mas'ul", role="kamera-masuli"),
    ])
    await db_session.commit()
    headers = await auth_headers(client, "admin", "admin123")

    async def logins(**params) -> set[str]:
        body = (await client.get("/api/users", params={"pageSize": 100, **params}, headers=headers)).json()
        return {u["login"] for u in body["items"]}

    assert await logins(search="eski") == {"eski_admin"}
    assert "yangi_masul" in await logins(role="kamera-masuli")
    assert "eski_admin" not in await logins(role="kamera-masuli")
    assert "yangi_masul" in await logins(xavf="kirmagan")
    assert await logins(xavf="eski") == {"eski_admin"}
    no_2fa = await logins(xavf="2fa_yoq")
    assert "eski_admin" in no_2fa and "yangi_masul" not in no_2fa

    items = (await client.get("/api/users", params={"search": "eski"}, headers=headers)).json()["items"]
    assert items[0]["lastLoginDays"] >= 119
