"""GET /api/auth/me — sessiyaning hozirgi haqiqati.

Mijoz rolni kirish paytida olib localStorage'da saqlaydi (JWT 12 soat).
Admin rolni shu orada o'zgartirsa, mijozning menyusi bir yarim kun
yolg'on gapirardi: lavozimidan olingan odam o'zida "Super Admin" yozuvini
va to'liq menyuni ko'rib turardi (so'rovlar backendda rad etilsa ham).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from tests.conftest import login


@pytest.mark.usefixtures("seeded")
class TestSessionMe:
    async def test_returns_role_and_name_from_the_database(self, client: AsyncClient):
        token = await login(client, "admin", "admin123")
        resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json() == {"role": "super-admin", "userName": "Jamshid Alimov", "twoFactorRequired": False}

    async def test_role_change_is_visible_without_a_new_login(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        token = await login(client, "operator", "operator123")
        headers = {"Authorization": f"Bearer {token}"}
        assert (await client.get("/api/auth/me", headers=headers)).json()["role"] == "admin"

        user = (await db_session.execute(select(User).where(User.login == "operator"))).scalar_one()
        user.role = "kamera-masuli"
        await db_session.commit()

        # O'sha token, yangi rol — mijoz menyusini shu javob bo'yicha tozalaydi.
        assert (await client.get("/api/auth/me", headers=headers)).json()["role"] == "kamera-masuli"

    async def test_without_a_token_it_is_401(self, client: AsyncClient):
        assert (await client.get("/api/auth/me")).status_code == 401

    async def test_after_logout_the_token_is_rejected(self, client: AsyncClient):
        token = await login(client, "admin", "admin123")
        headers = {"Authorization": f"Bearer {token}"}
        await client.post("/api/auth/logout", headers=headers)
        assert (await client.get("/api/auth/me", headers=headers)).status_code == 401
