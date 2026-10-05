"""Tizim nosozliklari haqida ogohlantirish (app/jobs/system_alerts.py)."""

from collections import namedtuple
from datetime import datetime, timedelta, timezone

import pytest

from app.jobs import system_alerts
from app.models import IntegrationSyncRun
from app.services.integrations import hemis
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.anyio

Usage = namedtuple("Usage", "total used free")


@pytest.fixture(autouse=True)
def _reset():
    system_alerts.reset_for_tests()
    yield
    system_alerts.reset_for_tests()


def test_alert_once_repeat_later_and_announce_recovery():
    first = system_alerts.plan_messages({"disk": "Disk 95% band"}, now_mono=0)
    assert [m.title for m in first] == ["Server diski to'lmoqda"]
    assert system_alerts.plan_messages({"disk": "Disk 95% band"}, now_mono=600) == []
    again = system_alerts.plan_messages({"disk": "Disk 96% band"}, now_mono=7 * 3600)
    assert len(again) == 1
    recovered = system_alerts.plan_messages({}, now_mono=8 * 3600)
    assert [m.title for m in recovered] == ["Server diski to'lmoqda — tiklandi"]


def test_disk_threshold(monkeypatch):
    monkeypatch.setattr(system_alerts.shutil, "disk_usage", lambda _p: Usage(100 * 1024**3, 95 * 1024**3, 5 * 1024**3))
    assert "95%" in system_alerts.disk_problem()
    monkeypatch.setattr(system_alerts.shutil, "disk_usage", lambda _p: Usage(100 * 1024**3, 50 * 1024**3, 50 * 1024**3))
    assert system_alerts.disk_problem() is None


async def test_hemis_failure_and_staleness(db_session, monkeypatch):
    monkeypatch.setattr(hemis, "hemis_configured", lambda: True)
    now = datetime.now(timezone.utc)
    db_session.add(IntegrationSyncRun(source=hemis.SOURCE, status="muvaffaqiyatli", started_at=now - timedelta(hours=60),
                                      finished_at=now - timedelta(hours=60)))
    await db_session.commit()
    assert "soatdan beri" in await system_alerts.hemis_problem(db_session, now)
    db_session.add(IntegrationSyncRun(source=hemis.SOURCE, status="xato", started_at=now - timedelta(hours=1),
                                      finished_at=now - timedelta(hours=1), error="401 token"))
    await db_session.commit()
    assert "401 token" in await system_alerts.hemis_problem(db_session, now)


async def test_run_dispatches_system_kind(db_session, monkeypatch):
    monkeypatch.setattr(system_alerts, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(system_alerts.shutil, "disk_usage", lambda _p: Usage(100, 99, 1))
    sent = []

    async def fake_dispatch(db, kind, message, **kwargs):
        sent.append((kind, message.title))
        return []

    monkeypatch.setattr(system_alerts.dispatcher, "_dispatch_rules", fake_dispatch)
    assert await system_alerts.run_system_alerts_once() == 1
    assert sent == [("system", "Server diski to'lmoqda")]
    assert await system_alerts.run_system_alerts_once() == 0
