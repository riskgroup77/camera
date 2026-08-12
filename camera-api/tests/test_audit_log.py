import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers


@pytest.mark.usefixtures("seeded")
class TestAuditLog:
    async def test_login_is_logged(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/audit-log", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert any(e["module"] == "Autentifikatsiya" and e["status"] == "muvaffaqiyatli" for e in body["items"])

    async def test_failed_login_is_logged_as_error(self, client: AsyncClient):
        await client.post("/api/auth/login", json={"login": "admin", "password": "wrong-password"})
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/audit-log?status=xatolik", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(e["status"] == "xatolik" for e in body["items"])

    async def test_filter_by_module(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        await client.post(
            "/api/buildings", headers=headers, json={"name": "Test filtr binosi", "cameraCount": 0}
        )
        resp = await client.get("/api/audit-log?module=Tashkilot", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert all(e["module"] == "Tashkilot" for e in body["items"])

    async def test_requires_system_settings_permission(self, client: AsyncClient):
        headers = await auth_headers(client, "operator", "operator123")
        resp = await client.get("/api/audit-log", headers=headers)
        assert resp.status_code == 403
