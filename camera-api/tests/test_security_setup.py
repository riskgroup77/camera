"""Production xavfsizligi: demo hisoblar, birinchi admin, API hujjatlari.

2026-09-17 da production'da `admin` / `admin123` ishlatilgan — parol ochiq
repozitoriyda va kirish sahifasining o'zida yozilgan edi.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import Settings, settings
from app.models import User
from app.seed import seed_all
from app.services.security_checks import forget_default_password_check
from tests.conftest import auth_headers

INITIAL_PASSWORD = "Uzun-Tasodifiy-Parol-42"


@pytest.fixture(autouse=True)
def _fresh_password_check():
    forget_default_password_check()
    yield
    forget_default_password_check()


async def _logins(db_session) -> list[tuple[str, str]]:
    users = (await db_session.execute(select(User).order_by(User.login))).scalars().all()
    return [(u.login, u.role) for u in users]


class TestSafeDefaults:
    def test_demo_users_and_docs_are_off_unless_asked_for(self):
        assert Settings.model_fields["seed_demo_users"].default is False
        assert Settings.model_fields["api_docs_enabled"].default is False
        assert Settings.model_fields["initial_admin_password"].default == ""


class TestFirstUsers:
    async def test_production_seed_creates_no_demo_users(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "seed_demo_users", False)
        monkeypatch.setattr(settings, "initial_admin_login", "")
        monkeypatch.setattr(settings, "initial_admin_password", "")

        await seed_all(db_session)

        assert await _logins(db_session) == []

    async def test_initial_admin_is_the_only_user(self, client: AsyncClient, db_session, monkeypatch):
        # Demo ham yoqilgan bo'lsa, aniq berilgan admin ustun turadi.
        monkeypatch.setattr(settings, "seed_demo_users", True)
        monkeypatch.setattr(settings, "initial_admin_login", "bosh")
        monkeypatch.setattr(settings, "initial_admin_password", INITIAL_PASSWORD)

        await seed_all(db_session)

        assert await _logins(db_session) == [("bosh", "super-admin")]
        headers = await auth_headers(client, "bosh", INITIAL_PASSWORD)
        assert (await client.get("/api/users", headers=headers)).status_code == 200
        demo = await client.post("/api/auth/login", json={"login": "admin", "password": "admin123"})
        assert demo.status_code == 401

    async def test_existing_users_are_never_touched(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "seed_demo_users", True)
        await seed_all(db_session)
        before = await _logins(db_session)

        monkeypatch.setattr(settings, "initial_admin_login", "bosh")
        monkeypatch.setattr(settings, "initial_admin_password", INITIAL_PASSWORD)
        await seed_all(db_session)

        assert await _logins(db_session) == before
        assert ("bosh", "super-admin") not in before


class TestDefaultPasswordAlert:
    @staticmethod
    async def _security_alerts(client: AsyncClient, headers) -> list[dict]:
        resp = await client.get("/api/system/resources", headers=headers)
        assert resp.status_code == 200, resp.text
        return [a for a in resp.json()["alerts"] if a["metric"] == "security"]

    async def test_dashboard_warns_while_a_demo_password_works(self, client: AsyncClient, seeded):
        headers = await auth_headers(client, "admin", "admin123")

        alerts = await self._security_alerts(client, headers)

        assert len(alerts) == 1
        assert alerts[0]["level"] == "critical"
        assert "admin" in alerts[0]["message"]
        assert "operator" in alerts[0]["message"]

    async def test_warning_goes_away_once_the_passwords_change(self, client: AsyncClient, db_session, seeded):
        headers = await auth_headers(client, "admin", "admin123")
        assert await self._security_alerts(client, headers)  # natija keshga tushdi
        ids = {u.login: u.id for u in (await db_session.execute(select(User))).scalars()}

        resp = await client.post(
            f"/api/users/{ids['operator']}/reset-password", headers=headers, json={"newPassword": INITIAL_PASSWORD}
        )
        assert resp.status_code == 204
        alerts = await self._security_alerts(client, headers)
        assert len(alerts) == 1
        assert "operator" not in alerts[0]["message"]

        resp = await client.post(
            f"/api/users/{ids['admin']}/reset-password", headers=headers, json={"newPassword": INITIAL_PASSWORD}
        )
        assert resp.status_code == 204
        # O'z parolini tiklash eski sessiyani yopadi — yangi parol bilan kiramiz.
        headers = await auth_headers(client, "admin", INITIAL_PASSWORD)
        assert await self._security_alerts(client, headers) == []


class TestApiDocs:
    async def test_docs_follow_the_setting(self, client: AsyncClient):
        expected = 200 if settings.api_docs_enabled else 404
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await client.get(path)).status_code == expected, path


class TestNoAnonymousDocumentDump:
    async def test_the_generic_upload_endpoint_is_gone(self, client: AsyncClient, seeded):
        """Pasport PDF va jonli suratlar hech qaysi yozuvga bog'lanmay
        omborda qolib ketardi — endpoint olib tashlandi."""
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/uploads", headers=headers, files={"file": ("passport.pdf", b"%PDF-1.4", "application/pdf")}
        )
        assert resp.status_code in (404, 405)
