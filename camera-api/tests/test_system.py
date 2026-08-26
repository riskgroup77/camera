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
        assert body["ffmpegProcessCount"] >= 0
        assert body["streamReaderCount"] >= 0
        assert isinstance(body["alerts"], list)

    async def test_alerts_have_expected_shape_when_present(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/system/resources", headers=headers)
        assert resp.status_code == 200
        for alert in resp.json()["alerts"]:
            assert alert["metric"]
            assert alert["level"] in ("warning", "critical")
            assert alert["message"]

    async def test_requires_authentication(self, client: AsyncClient):
        resp = await client.get("/api/system/resources")
        assert resp.status_code == 401
