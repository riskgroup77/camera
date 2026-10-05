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
        zone = next(m for m in resp.json() if m["code"] == 2)
        assert zone["hasDetector"] is True
        # Olib tashlangan modullar: #12 (beyjik, 2026-09-16), #13, #14, #17, #23
        # (2026-09-24). #10 (xalat) va #15 (chekish) 2026-10-04 da kunlik video
        # tahlilda qaytdi (sinov rejimida).
        codes = {m["code"] for m in resp.json()}
        assert not codes & {12, 13, 14, 17, 23}
        assert {10, 15} <= codes
        assert all(m["maturity"] == "sinov" for m in resp.json() if m["code"] in (10, 15))
        # Aniqlik — statik raqam emas, ko'rib chiqilgan signallardan o'lchanadi.
        assert module_1["measuredPrecision"] is None
        assert module_1["accuracy"] == 0
        assert zone["maturity"] == "sinov"

    async def test_no_module_ships_a_made_up_accuracy(self, db_session: AsyncSession):
        """96,4 / 98,6 / 99,2 kabi raqamlar hech qachon o'lchanmagan edi."""
        rows = (await db_session.execute(select(AIModuleConfig))).scalars().all()
        assert rows and all(row.accuracy == 0 for row in rows)

    async def test_student_attendance_module_is_on(self, client: AsyncClient, db_session: AsyncSession):
        """#7 2026-09-16 da to'xtatilgan edi; kunlik video tahlilda (2026-10-04)
        dars xonalari ham ko'riladi va u qayta yoqilgan."""
        from app.jobs.module_status import is_module_active

        module = await _get_module(db_session, 7)
        assert module.active is True
        assert await is_module_active(db_session, 7) is True

        headers = await auth_headers(client, "admin", "admin123")
        listed = (await client.get("/api/ai-modules", headers=headers)).json()
        assert next(m for m in listed if m["code"] == 7)["active"] is True

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
        module = await _get_module(db_session, 2)
        headers = await auth_headers(client, "admin", "admin123")

        resp = await client.patch(
            f"/api/ai-modules/{module.id}",
            headers=headers,
            json={"threshold": module.threshold, "sensitivity": module.sensitivity, "active": False},
        )
        assert resp.status_code == 200
        assert resp.json()["active"] is False


@pytest.mark.usefixtures("seeded")
class TestMeasuredPrecision:
    """Audit #7/#8: aniqlik statik raqam emas — operator ko'rib chiqqan
    signallardan o'lchanadi; ko'p yolg'on signal bergan modul "sozlash kerak"."""

    async def _events(self, db_session: AsyncSession, code: int, confirmed: int, rejected: int, new: int = 0):
        from app.models import Event

        for status_value, count in (("tasdiqlangan", confirmed), ("rad_etilgan", rejected), ("yangi", new)):
            for _ in range(count):
                db_session.add(Event(camera_name="Sinov", building="1-bino", module_code=code, module_name="m",
                                     group="D", confidence=50, severity="o'rta", status=status_value))
        await db_session.commit()

    async def _module(self, client: AsyncClient, code: int) -> dict:
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/ai-modules", headers=headers)
        return next(m for m in resp.json() if m["code"] == code)

    async def test_precision_is_confirmed_share_of_reviewed(self, client: AsyncClient, db_session: AsyncSession):
        await self._events(db_session, 1, confirmed=9, rejected=3, new=5)
        module = await self._module(client, 1)
        assert module["measuredPrecision"] == 75.0
        assert module["accuracy"] == 75.0
        assert module["reviewedEvents"] == 12
        assert module["recentEvents"] == 17
        assert module["maturity"] == "asosiy"

    async def test_small_sample_is_not_a_percentage(self, client: AsyncClient, db_session: AsyncSession):
        await self._events(db_session, 19, confirmed=1, rejected=0)
        module = await self._module(client, 19)
        assert module["measuredPrecision"] is None  # "100% (1/1)" emas
        assert module["maturity"] == "sinov"
        assert "1" in module["maturityNote"]

    async def test_mostly_rejected_module_needs_tuning(self, client: AsyncClient, db_session: AsyncSession):
        await self._events(db_session, 2, confirmed=2, rejected=18)
        module = await self._module(client, 2)
        assert module["maturity"] == "sozlash_kerak"
        assert module["measuredPrecision"] == 10.0
