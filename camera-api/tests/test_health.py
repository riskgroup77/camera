import pytest
from httpx import AsyncClient

import app.main as main_module


class TestHealth:
    async def test_healthy_when_all_dependencies_reachable(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"status": "ok", "database": "ok", "storage": "ok", "video_gateway": "ok"}

    async def test_degraded_when_storage_unreachable(self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
        def boom():
            raise ConnectionError("MinIO unreachable")

        monkeypatch.setattr(main_module, "check_bucket", boom)
        resp = await client.get("/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["storage"] == "unreachable"
        assert body["database"] == "ok"

    async def test_degraded_when_video_gateway_unreachable(self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
        async def boom():
            raise ConnectionError("MediaMTX unreachable")

        monkeypatch.setattr(main_module.video_gateway, "check_reachable", boom)
        resp = await client.get("/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["video_gateway"] == "unreachable"
        assert body["storage"] == "ok"
