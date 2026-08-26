"""P2 — GPU status probe and /api/system/ai-status."""

import pytest
from httpx import AsyncClient

from app.services.ai_runtime_status import build_ai_runtime_status
from app.services.gpu_status import get_gpu_status
from tests.conftest import auth_headers


class TestGpuStatus:
    def test_returns_structured_fields(self):
        status = get_gpu_status()
        assert "cuda_available" in status
        assert "onnx_providers" in status
        assert isinstance(status["onnx_providers"], list)
        assert isinstance(status["recommendation"], str)

    def test_build_ai_runtime_status_shape(self):
        raw = build_ai_runtime_status()
        assert raw["scheduler_enabled"] is not None
        assert "gpu" in raw
        assert "last_tick" in raw
        assert "sweep_slots" in raw
        assert raw["sweep_slots"]["max"] >= 1


@pytest.mark.usefixtures("seeded")
class TestSystemAiStatusEndpoint:
    async def test_returns_ai_status(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/system/ai-status", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["schedulerEnabled"] is True or body["schedulerEnabled"] is False
        assert "gpu" in body
        assert body["gpu"]["onnxProviders"] is not None
        assert "lastTick" in body
        assert body["globalSweepConcurrency"] >= 1

    async def test_requires_authentication(self, client: AsyncClient):
        resp = await client.get("/api/system/ai-status")
        assert resp.status_code == 401
