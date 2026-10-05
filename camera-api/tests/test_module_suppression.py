"""Shovqinli kamera × modul juftliklarini avtomatik o'chirish va begona
shaxs (#1) uchun joy/vaqt qoidasi."""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.jobs.module_status import (
    camera_allows_module,
    camera_can_report_unauthorized,
    is_unauthorized_alert_time,
    load_suppressed_pairs,
)
from app.jobs.module_suppression import run_module_suppression_once
from app.models import Building, Camera, Event, ModuleCameraSuppression
from app.timezone import INSTITUTE_TZ
from tests.conftest import TestSessionLocal, auth_headers


pytestmark = pytest.mark.six_am_day


@pytest.fixture
async def camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    cam = Camera(name="Shovqinli kamera", ip="10.0.0.92", building_id=building.id, zone="Hovli",
                 resolution="1080p", status="faol")
    db_session.add(cam)
    await db_session.commit()
    return cam


async def _reviewed(db_session, camera, code, confirmed, rejected):
    for status_value, count in (("tasdiqlangan", confirmed), ("rad_etilgan", rejected)):
        for _ in range(count):
            db_session.add(
                Event(camera_id=camera.id, camera_name=camera.name, building="1-bino", module_code=code,
                      module_name="m", group="D", confidence=50, severity="past", status=status_value,
                      reviewed_at=datetime.now(timezone.utc))
            )
    await db_session.commit()


async def _allowed_camera_ids(db_session, code):
    return {c.id for c in (await db_session.execute(select(Camera).where(camera_allows_module(code)))).scalars()}


class TestAutoSuppression:
    async def test_noisy_pair_is_suppressed_only_for_that_module(self, db_session, camera):
        await _reviewed(db_session, camera, 17, confirmed=1, rejected=8)
        assert await run_module_suppression_once(session_factory=TestSessionLocal) == 1

        assert camera.id not in await _allowed_camera_ids(db_session, 17)
        assert camera.id in await _allowed_camera_ids(db_session, 23)
        assert (str(camera.id), 17) in await load_suppressed_pairs(db_session)
        # Takroriy ishga tushirish ikkinchi yozuv yaratmaydi.
        assert await run_module_suppression_once(session_factory=TestSessionLocal) == 0

    @pytest.mark.parametrize("confirmed,rejected", [(0, 7), (8, 8)])
    async def test_small_or_precise_samples_are_left_alone(self, db_session, camera, confirmed, rejected):
        await _reviewed(db_session, camera, 17, confirmed=confirmed, rejected=rejected)
        assert await run_module_suppression_once(session_factory=TestSessionLocal) == 0

    async def test_restore_counts_only_reviews_after_it(self, client: AsyncClient, db_session, camera):
        await _reviewed(db_session, camera, 17, confirmed=0, rejected=9)
        await run_module_suppression_once(session_factory=TestSessionLocal)
        headers = await auth_headers(client, "admin", "admin123")

        listed = (await client.get("/api/ai-modules/suppressions", headers=headers)).json()
        assert len(listed) == 1 and listed[0]["cameraName"] == "Shovqinli kamera" and listed[0]["rejected"] == 9

        resp = await client.post(f"/api/ai-modules/suppressions/{listed[0]['id']}/restore", headers=headers)
        assert resp.status_code == 204
        assert (await client.get("/api/ai-modules/suppressions", headers=headers)).json() == []
        assert camera.id in await _allowed_camera_ids(db_session, 17)

        # Eski rad etishlar qaytarilgan juftlikni yana o'chirmaydi.
        assert await run_module_suppression_once(session_factory=TestSessionLocal) == 0
        rows = (await db_session.execute(select(ModuleCameraSuppression))).scalars().all()
        assert len(rows) == 1 and rows[0].restored_by is not None

    async def test_disabled_setting_does_nothing(self, db_session, camera, monkeypatch):
        monkeypatch.setattr(settings, "suppression_enabled", False)
        await _reviewed(db_session, camera, 17, confirmed=0, rejected=12)
        assert await run_module_suppression_once(session_factory=TestSessionLocal) == 0


class TestUnauthorizedContext:
    @pytest.fixture(autouse=True)
    def _settings(self, monkeypatch):
        monkeypatch.setattr(settings, "unauthorized_active_windows", "19:00-07:00")
        monkeypatch.setattr(settings, "attendance_working_weekdays", "1,2,3,4,5,6")

    @pytest.mark.parametrize(
        "moment,expected",
        [
            (datetime(2026, 9, 15, 12, 0, tzinfo=INSTITUTE_TZ), False),  # seshanba, kunduzi
            (datetime(2026, 9, 15, 20, 30, tzinfo=INSTITUTE_TZ), True),
            (datetime(2026, 9, 15, 6, 0, tzinfo=INSTITUTE_TZ), True),
            (datetime(2026, 9, 20, 12, 0, tzinfo=INSTITUTE_TZ), True),  # yakshanba — ish kuni emas
        ],
    )
    @pytest.mark.default_policy
    def test_alert_window(self, moment, expected):
        assert is_unauthorized_alert_time(moment) is expected

    def test_broken_window_setting_fails_open(self, monkeypatch):
        monkeypatch.setattr(settings, "unauthorized_active_windows", "kechqurun")
        assert is_unauthorized_alert_time(datetime(2026, 9, 15, 12, 0, tzinfo=INSTITUTE_TZ)) is True

    def test_only_entrance_or_perimeter_cameras(self, monkeypatch):
        assert camera_can_report_unauthorized(Camera(name="a", is_entrance=True)) is True
        assert camera_can_report_unauthorized(Camera(name="b", is_perimeter=True)) is True
        assert camera_can_report_unauthorized(Camera(name="c")) is False
        monkeypatch.setattr(settings, "unauthorized_perimeter_only", False)
        assert camera_can_report_unauthorized(Camera(name="c")) is True
