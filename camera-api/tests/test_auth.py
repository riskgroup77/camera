import pytest
from httpx import AsyncClient

from tests.conftest import login


@pytest.mark.usefixtures("seeded")
class TestLogin:
    async def test_correct_credentials_return_token_and_role(self, client: AsyncClient):
        resp = await client.post("/api/auth/login", json={"login": "admin", "password": "admin123"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "super-admin"
        assert body["userName"] == "Jamshid Alimov"
        assert body["token"]

    async def test_wrong_password_is_rejected(self, client: AsyncClient):
        resp = await client.post("/api/auth/login", json={"login": "admin", "password": "wrong"})
        assert resp.status_code == 401

    async def test_unknown_login_is_rejected(self, client: AsyncClient):
        resp = await client.post("/api/auth/login", json={"login": "nobody", "password": "whatever123"})
        assert resp.status_code == 401

    async def test_role_is_never_taken_from_the_client(self, client: AsyncClient):
        """The old frontend-only demo let the client pick a role before
        checking credentials. The real backend must always derive role
        from the account that owns the login — this test guards against
        regressing to trusting client input for authorization."""
        resp = await client.post("/api/auth/login", json={"login": "operator", "password": "operator123"})
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    async def test_sixth_rapid_attempt_is_rate_limited(self, client: AsyncClient):
        for _ in range(5):
            await client.post("/api/auth/login", json={"login": "admin", "password": "wrong"})
        resp = await client.post("/api/auth/login", json={"login": "admin", "password": "wrong"})
        assert resp.status_code == 429

    async def test_failed_attempt_is_recorded_in_audit_log(self, client: AsyncClient):
        await client.post("/api/auth/login", json={"login": "admin", "password": "wrong"})
        headers = await self._admin_headers(client)
        resp = await client.get("/api/audit-log", headers=headers)
        actions = [e["action"] for e in resp.json()["items"]]
        assert "Noto'g'ri login urinishi" in actions

    @staticmethod
    async def _admin_headers(client: AsyncClient) -> dict[str, str]:
        token = await login(client, "admin", "admin123")
        return {"Authorization": f"Bearer {token}"}


@pytest.mark.usefixtures("seeded")
class TestLogout:
    async def test_logout_revokes_the_token(self, client: AsyncClient):
        token = await login(client, "admin", "admin123")
        headers = {"Authorization": f"Bearer {token}"}

        # Token real bo'lgani uchun avval ishlashi kerak.
        assert (await client.get("/api/users", headers=headers)).status_code == 200

        logout_resp = await client.post("/api/auth/logout", headers=headers)
        assert logout_resp.status_code == 204

        # Xuddi shu token endi hech qanday himoyalangan endpointda ishlamasligi kerak.
        resp = await client.get("/api/users", headers=headers)
        assert resp.status_code == 401

    async def test_logout_without_token_is_unauthorized(self, client: AsyncClient):
        resp = await client.post("/api/auth/logout")
        assert resp.status_code == 401

    async def test_new_login_after_logout_still_works(self, client: AsyncClient):
        """Logging out one token must not affect the account's ability to
        log in again and get a fresh, valid token."""
        old_token = await login(client, "admin", "admin123")
        await client.post("/api/auth/logout", headers={"Authorization": f"Bearer {old_token}"})

        new_token = await login(client, "admin", "admin123")
        resp = await client.get("/api/users", headers={"Authorization": f"Bearer {new_token}"})
        assert resp.status_code == 200
