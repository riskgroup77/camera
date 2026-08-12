import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers


@pytest.mark.usefixtures("seeded")
class TestSystemResources:
    async def test_returns_real_resource_percentages(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/system/resources", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        for key in ("cpu", "ram", "disk"):
            assert 0 <= body[key] <= 100

    async def test_requires_authentication(self, client: AsyncClient):
        resp = await client.get("/api/system/resources")
        assert resp.status_code == 401
