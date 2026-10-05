"""P2 — offline alert semantics, motion history isolation, fight mock kwargs."""

import pytest
from sqlalchemy import select

from app.config import settings
from app.jobs.camera_health import run_camera_health_sweep_once
from app.models import AuditLog, Building, Camera


@pytest.mark.usefixtures("seeded")
class TestOfflineAlertSemantics:
    async def test_zero_minutes_alerts_on_first_failed_check(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "camera_offline_alert_minutes", 0)
        building = (await db_session.execute(select(Building))).scalars().first()
        camera = Camera(
            name="Darhol alert kamera",
            ip="192.0.2.70",
            port=554,
            building_id=building.id,
            zone="Z",
            resolution="1080p",
            status="faol",
        )
        db_session.add(camera)
        await db_session.commit()

        await run_camera_health_sweep_once(db_session)

        result = await db_session.execute(
            select(AuditLog).where(AuditLog.module == "Kameralar", AuditLog.action.like("%Darhol alert%"))
        )
        entry = result.scalars().first()
        assert entry is not None
        assert "javob bermayapti" in entry.action

    async def test_negative_minutes_disables_alerts(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "camera_offline_alert_minutes", -1)
        building = (await db_session.execute(select(Building))).scalars().first()
        camera = Camera(
            name="Alert o'chirilgan kamera",
            ip="192.0.2.71",
            port=554,
            building_id=building.id,
            zone="Z",
            resolution="1080p",
            status="faol",
        )
        db_session.add(camera)
        await db_session.commit()

        await run_camera_health_sweep_once(db_session)

        result = await db_session.execute(
            select(AuditLog).where(AuditLog.module == "Kameralar", AuditLog.action.like("%Alert o'chirilgan%"))
        )
        assert result.scalars().first() is None
