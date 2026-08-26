"""P3 — MediaMTX stream status and camera network observability."""

import pytest
from httpx import AsyncClient

from app.services.camera_network_status import build_camera_network_status, offline_pct
from app.services.stream_status import build_stream_status
from tests.conftest import auth_headers


class TestOfflinePct:
    def test_rounds_percentage(self):
        assert offline_pct(3, 10) == 30


@pytest.mark.usefixtures("seeded")
class TestStreamStatusService:
    async def test_build_stream_status_shape(self, db_session, monkeypatch):
        async def fake_probe():
            return [
                {
                    "index": 0,
                    "api_url": "http://mtx-0:9997",
                    "hls_base_url": "http://mtx-0:8888",
                    "reachable": True,
                    "path_count": 2,
                    "error": None,
                }
            ]

        monkeypatch.setattr("app.services.stream_status.probe_shards", fake_probe)
        raw = await build_stream_status(db_session)
        assert "shard_count" in raw
        assert raw["sharding_enabled"] is False or raw["sharding_enabled"] is True
        assert isinstance(raw["shards"], list)


@pytest.mark.usefixtures("seeded")
class TestCameraNetworkService:
    async def test_build_camera_network_status_shape(self, db_session):
        raw = await build_camera_network_status(db_session)
        assert raw["faol_cameras"] >= 0
        assert raw["reachable_cameras"] >= 0
        assert "last_sweep" in raw
        assert isinstance(raw["recommendation"], str)


@pytest.mark.usefixtures("seeded")
class TestSystemP3Endpoints:
    async def test_stream_status(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/system/stream-status", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "shards" in body
        assert body["shardCount"] >= 1
        assert isinstance(body["recommendation"], str)

    async def test_camera_network(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/system/camera-network", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["faolCameras"] >= 0
        assert "lastSweep" in body
        assert body["healthConcurrency"] >= 1

    async def test_endpoints_require_auth(self, client: AsyncClient):
        assert (await client.get("/api/system/stream-status")).status_code == 401
        assert (await client.get("/api/system/camera-network")).status_code == 401

    async def test_resync_streams_requires_system_settings(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post("/api/system/resync-streams", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["synced"] >= 0
        assert body["failed"] >= 0
