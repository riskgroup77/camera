"""Hisobotlar paroli (app/routers/report_lock.py)."""

import pytest
from httpx import AsyncClient

from app.config import settings
from app.routers.report_lock import hash_report_password, verify_report_password
from tests.conftest import auth_headers

pytestmark = pytest.mark.anyio

REPORT_URL = "/api/hisobot/filters?kind=xodim"


def test_hash_has_no_dollar_and_verifies():
    stored = hash_report_password("secret-1", iterations=1000)
    assert "$" not in stored and stored.startswith("pbkdf2:")
    assert verify_report_password(stored, "secret-1")
    assert not verify_report_password(stored, "secret-2")
    assert not verify_report_password("buzilgan", "secret-1")


async def test_reports_open_when_no_password_is_set(client: AsyncClient, seeded, monkeypatch):
    monkeypatch.setattr(settings, "report_password_hash", "")
    headers = await auth_headers(client, "admin", "admin123")
    assert (await client.get(REPORT_URL, headers=headers)).status_code == 200
    assert (await client.get("/api/hisobot-kirish", headers=headers)).json()["locked"] is False


async def test_password_unlocks_reports_for_that_user_only(client: AsyncClient, seeded, monkeypatch):
    monkeypatch.setattr(settings, "report_password_hash", hash_report_password("secret-1", iterations=1000))
    headers = await auth_headers(client, "admin", "admin123")

    locked = await client.get(REPORT_URL, headers=headers)
    assert locked.status_code == 403 and locked.headers.get("x-report-locked") == "1"
    assert (await client.get("/api/kpi", headers=headers)).status_code == 403
    assert (await client.get("/api/hisobot-kirish", headers=headers)).json()["locked"] is True

    wrong = await client.post("/api/hisobot-kirish", json={"password": "xato"}, headers=headers)
    assert wrong.status_code == 401

    ok = await client.post("/api/hisobot-kirish", json={"password": "secret-1"}, headers=headers)
    assert ok.status_code == 200, ok.text
    token = ok.json()["token"]
    assert (await client.get(REPORT_URL, headers={**headers, "X-Report-Token": token})).status_code == 200
    assert (await client.get(REPORT_URL, headers={**headers, "X-Report-Token": "soxta"})).status_code == 403

    # Boshqa foydalanuvchi shu kalit bilan kira olmaydi.
    other = await auth_headers(client, "operator", "operator123")
    assert (await client.get(REPORT_URL, headers={**other, "X-Report-Token": token})).status_code == 403


async def test_other_report_endpoints_are_behind_the_same_password(client: AsyncClient, seeded, monkeypatch):
    """Hisobot ma'lumotini boshqa yo'l bilan parolsiz olib bo'lmaydi; kundalik
    (jonli) ko'rinishlar esa ochiq qoladi."""
    monkeypatch.setattr(settings, "report_password_hash", hash_report_password("secret-1", iterations=1000))
    headers = await auth_headers(client, "admin", "admin123")
    for url in ("/api/reports", "/api/situation/analytics/summary", "/api/situation/analytics/heatmap",
                "/api/situation/analytics/people"):
        assert (await client.get(url, headers=headers)).status_code == 403, url
    token = (await client.post("/api/hisobot-kirish", json={"password": "secret-1"}, headers=headers)).json()["token"]
    for url in ("/api/situation/analytics/summary", "/api/situation/analytics/heatmap"):
        assert (await client.get(url, headers={**headers, "X-Report-Token": token})).status_code == 200, url
    # Jonli Nazorat va devor ekrani paroliz ishlaydi.
    assert (await client.get("/api/situation/people-status", headers=headers)).status_code == 200
    assert (await client.get("/api/situation/analytics/chronic", headers=headers)).status_code == 200
