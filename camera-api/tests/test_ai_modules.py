import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIModuleConfig
from tests.conftest import auth_headers


async def _get_module(db_session: AsyncSession, code: int) -> AIModuleConfig:
    return (
        await db_session.execute(select(AIModuleConfig).where(AIModuleConfig.code == code))
    ).scalar_one()


@pytest.mark.usefixtures("seeded")
class TestAiModules:
    async def test_list_includes_has_detector(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/ai-modules", headers=headers)
        assert resp.status_code == 200
        module_1 = next(m for m in resp.json() if m["code"] == 1)
        assert module_1["hasDetector"] is True
        module_12 = next(m for m in resp.json() if m["code"] == 12)
        assert module_12["hasDetector"] is True

    async def test_p3_modules_have_detectors_and_can_activate(self, client: AsyncClient, db_session: AsyncSession):
        for code in (12, 13, 15, 18):
            module = await _get_module(db_session, code)
            assert module.has_detector is True
        headers = await auth_headers(client, "admin", "admin123")
        module = await _get_module(db_session, 12)
        resp = await client.patch(
            f"/api/ai-modules/{module.id}",
            headers=headers,
            json={"threshold": module.threshold, "sensitivity": module.sensitivity, "active": True},
        )
        assert resp.status_code == 200

    async def test_activating_a_module_with_a_real_detector_but_zero_accuracy_succeeds(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Code 1 (unauthorized-person detection) has a real InsightFace
        detector behind it (app/jobs/unauthorized_person_ai.py) but has
        never been benchmarked, so accuracy stays 0 — that must not be
        treated as 'nothing implemented' the way it used to be."""
        module = await _get_module(db_session, 1)
        assert module.accuracy == 0
        headers = await auth_headers(client, "admin", "admin123")

        resp = await client.patch(
            f"/api/ai-modules/{module.id}",
            headers=headers,
            json={"threshold": module.threshold, "sensitivity": module.sensitivity, "active": True},
        )
        assert resp.status_code == 200
        assert resp.json()["active"] is True

    async def test_deactivating_a_no_detector_module_is_always_allowed(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        module = await _get_module(db_session, 12)
        headers = await auth_headers(client, "admin", "admin123")

        resp = await client.patch(
            f"/api/ai-modules/{module.id}",
            headers=headers,
            json={"threshold": module.threshold, "sensitivity": module.sensitivity, "active": False},
        )
        assert resp.status_code == 200
        assert resp.json()["active"] is False
