import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers, login


@pytest.mark.usefixtures("seeded")
class TestUsers:
    async def test_create_user_with_email(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/users",
            headers=headers,
            json={
                "name": "Test Foydalanuvchi",
                "login": "test.user",
                "password": "parol12345",
                "role": "Admin",
                "email": "test.user@example.com",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["email"] == "test.user@example.com"

    async def test_update_user_name_login_role(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = (
            await client.post(
                "/api/users",
                headers=headers,
                json={"name": "Boshlang'ich Ism", "login": "edit.me", "password": "parol12345", "role": "Admin"},
            )
        ).json()

        resp = await client.patch(
            f"/api/users/{created['id']}",
            headers=headers,
            json={"name": "Yangilangan Ism", "login": "edited.login", "role": "Super Admin"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Yangilangan Ism"
        assert body["login"] == "edited.login"
        assert body["role"] == "Super Admin"

    async def test_update_user_login_conflict_is_409(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        await client.post(
            "/api/users",
            headers=headers,
            json={"name": "Birinchi Foydalanuvchi", "login": "taken.login", "password": "parol12345", "role": "Admin"},
        )
        created = (
            await client.post(
                "/api/users",
                headers=headers,
                json={"name": "Ikkinchi Foydalanuvchi", "login": "free.login", "password": "parol12345", "role": "Admin"},
            )
        ).json()

        resp = await client.patch(
            f"/api/users/{created['id']}",
            headers=headers,
            json={"name": "Ikkinchi Foydalanuvchi", "login": "taken.login", "role": "Admin"},
        )
        assert resp.status_code == 409

    async def test_update_unknown_user_is_404(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.patch(
            "/api/users/00000000-0000-0000-0000-000000000000",
            headers=headers,
            json={"name": "Yo'q Foydalanuvchi", "login": "ghost", "role": "Admin"},
        )
        assert resp.status_code == 404

    async def test_admin_reset_password_changes_password_and_revokes_sessions(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = (
            await client.post(
                "/api/users",
                headers=headers,
                json={"name": "Reset Qilinuvchi", "login": "reset.target", "password": "eski-parol1", "role": "Admin"},
            )
        ).json()

        target_token = await login(client, "reset.target", "eski-parol1")
        assert (await client.get("/api/users", headers={"Authorization": f"Bearer {target_token}"})).status_code == 403
        # (403 emas 401 kutilardi degan fikr tug'ilishi mumkin — operator kabi
        # "reset.target" ham manageRoles huquqiga ega emas, shuning uchun /api/users
        # ro'yxatiga umuman ruxsati yo'q; bu yerda faqat token ISHLAYOTGANINI
        # tekshiramiz, keyingi qatorda esa reset'dan keyin ISHLAMASLIGINI.)

        reset = await client.post(
            f"/api/users/{created['id']}/reset-password", headers=headers, json={"newPassword": "yangi-parol2"}
        )
        assert reset.status_code == 204

        # Eski token endi hech qanday himoyalangan so'rovda ishlamaydi (401,
        # 403 emas — chunki token_version tekshiruvi autentifikatsiya
        # bosqichida ishlaydi, ruxsat bosqichidan oldin).
        stale = await client.get("/api/users", headers={"Authorization": f"Bearer {target_token}"})
        assert stale.status_code == 401

        assert (await client.post("/api/auth/login", json={"login": "reset.target", "password": "eski-parol1"})).status_code == 401
        fresh = await client.post("/api/auth/login", json={"login": "reset.target", "password": "yangi-parol2"})
        assert fresh.status_code == 200

    async def test_sixth_rapid_admin_reset_attempt_is_rate_limited(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = (
            await client.post(
                "/api/users",
                headers=headers,
                json={"name": "Limit Nishoni", "login": "rate.limit.target", "password": "parol12345", "role": "Admin"},
            )
        ).json()

        for _ in range(5):
            await client.post(
                f"/api/users/{created['id']}/reset-password", headers=headers, json={"newPassword": "yangi-parol1"}
            )
        resp = await client.post(
            f"/api/users/{created['id']}/reset-password", headers=headers, json={"newPassword": "yangi-parol1"}
        )
        assert resp.status_code == 429

    async def test_operator_cannot_edit_or_reset_users(self, client: AsyncClient):
        headers = await auth_headers(client, "operator", "operator123")
        resp = await client.patch(
            "/api/users/00000000-0000-0000-0000-000000000000",
            headers=headers,
            json={"name": "X", "login": "y", "role": "Admin"},
        )
        assert resp.status_code == 403

    async def test_delete_user(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = (
            await client.post(
                "/api/users",
                headers=headers,
                json={"name": "O'chiriladigan", "login": "delete.me", "password": "parol12345", "role": "Admin"},
            )
        ).json()

        resp = await client.delete(f"/api/users/{created['id']}", headers=headers)
        assert resp.status_code == 204

        listed = await client.get("/api/users", headers=headers)
        assert created["id"] not in [u["id"] for u in listed.json()["items"]]

    async def test_delete_unknown_user_is_404(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.delete("/api/users/00000000-0000-0000-0000-000000000000", headers=headers)
        assert resp.status_code == 404

    async def test_cannot_delete_self(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        me = (await client.get("/api/users", headers=headers)).json()["items"]
        admin_user = next(u for u in me if u["login"] == "admin")

        resp = await client.delete(f"/api/users/{admin_user['id']}", headers=headers)
        assert resp.status_code == 400

    async def test_cannot_delete_last_super_admin(self, client: AsyncClient):
        """Isolates the last-super-admin guard from the self-deletion guard:
        the actor here ("operator", role Admin, granted manageRoles) is
        deleting a DIFFERENT user (the seeded "admin", the only super-admin),
        so a 400 here can only come from the last-super-admin check."""
        super_headers = await auth_headers(client, "admin", "admin123")
        await client.patch("/api/permissions/manageRoles", headers=super_headers, json={"role": "admin"})
        operator_headers = await auth_headers(client, "operator", "operator123")

        users = (await client.get("/api/users", headers=operator_headers)).json()["items"]
        original_admin = next(u for u in users if u["login"] == "admin")

        resp = await client.delete(f"/api/users/{original_admin['id']}", headers=operator_headers)
        assert resp.status_code == 400
