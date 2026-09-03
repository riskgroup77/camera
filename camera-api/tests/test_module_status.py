from datetime import datetime, time

import pytest
from sqlalchemy import select

from app.config import settings
from app.jobs.module_status import (
    any_module_active,
    camera_allows_module,
    is_module_active,
    is_within_behaviour_hours,
)
from app.models import AIModuleConfig, Building, Camera


@pytest.mark.usefixtures("seeded")
class TestIsModuleActive:
    async def test_active_module_reads_true(self, db_session):
        db_session.add(AIModuleConfig(
            code=901, group="A", name="Test", description="d", method="m", active=True,
        ))
        await db_session.commit()
        assert await is_module_active(db_session, 901) is True

    async def test_inactive_module_reads_false(self, db_session):
        db_session.add(AIModuleConfig(
            code=902, group="A", name="Test", description="d", method="m", active=False,
        ))
        await db_session.commit()
        assert await is_module_active(db_session, 902) is False

    async def test_missing_module_reads_false_not_error(self, db_session):
        assert await is_module_active(db_session, 999999) is False


@pytest.mark.usefixtures("seeded")
class TestAnyModuleActive:
    async def test_true_if_at_least_one_is_active(self, db_session):
        db_session.add_all([
            AIModuleConfig(code=911, group="A", name="A", description="d", method="m", active=False),
            AIModuleConfig(code=912, group="A", name="B", description="d", method="m", active=True),
        ])
        await db_session.commit()
        assert await any_module_active(db_session, [911, 912]) is True

    async def test_false_if_all_are_inactive(self, db_session):
        db_session.add_all([
            AIModuleConfig(code=921, group="A", name="A", description="d", method="m", active=False),
            AIModuleConfig(code=922, group="A", name="B", description="d", method="m", active=False),
        ])
        await db_session.commit()
        assert await any_module_active(db_session, [921, 922]) is False

    async def test_false_if_none_exist(self, db_session):
        assert await any_module_active(db_session, [999998, 999999]) is False


@pytest.mark.usefixtures("seeded")
class TestCameraAllowsModule:
    async def _make_camera(self, db_session, excluded_module_codes=None):
        building = (await db_session.execute(select(Building))).scalars().first()
        camera = Camera(
            name="Test kamerasi", ip="10.0.9.99", building_id=building.id,
            zone="Z", resolution="1080p", status="faol",
            excluded_module_codes=excluded_module_codes,
        )
        db_session.add(camera)
        await db_session.commit()
        return camera

    async def test_camera_with_no_exclusions_allows_every_module(self, db_session):
        await self._make_camera(db_session, excluded_module_codes=None)
        result = await db_session.execute(select(Camera).where(camera_allows_module(25)))
        assert len(result.scalars().all()) == 1

    async def test_camera_excluding_this_module_is_filtered_out(self, db_session):
        await self._make_camera(db_session, excluded_module_codes=[25])
        result = await db_session.execute(select(Camera).where(camera_allows_module(25)))
        assert result.scalars().all() == []

    async def test_camera_excluding_a_different_module_is_unaffected(self, db_session):
        await self._make_camera(db_session, excluded_module_codes=[10, 11])
        result = await db_session.execute(select(Camera).where(camera_allows_module(25)))
        assert len(result.scalars().all()) == 1

    async def test_empty_exclusion_list_allows_every_module(self, db_session):
        await self._make_camera(db_session, excluded_module_codes=[])
        result = await db_session.execute(select(Camera).where(camera_allows_module(25)))
        assert len(result.scalars().all()) == 1


class TestBehaviourHoursWindow:
    """Watching for "a student fell asleep" in a building with nobody in
    it cannot produce a true result, only a false one. Measured on
    production: ~30% of the disorder module's events landed between
    00:00 and 05:00, and every sampled snapshot from that window showed
    an empty room."""

    @pytest.fixture(autouse=True)
    def _daytime_window(self, monkeypatch):
        monkeypatch.setattr(settings, "behaviour_hours_enabled", True)
        monkeypatch.setattr(settings, "behaviour_hours_start", "07:00")
        monkeypatch.setattr(settings, "behaviour_hours_end", "21:00")

    @pytest.mark.parametrize(
        "moment, inside",
        [
            ("06:59", False),
            ("07:00", True),   # boundaries are inclusive on both ends
            ("13:30", True),
            ("21:00", True),
            ("21:01", False),
            ("03:00", False),
        ],
    )
    def test_window_boundaries(self, moment, inside):
        hour, minute = moment.split(":")
        assert is_within_behaviour_hours(time(int(hour), int(minute))) is inside

    def test_a_window_crossing_midnight_is_read_the_right_way_round(self, monkeypatch):
        """Nothing stops an operator configuring 21:00-07:00. Read
        naively that is an empty range, which would disable the module
        all day instead of all night — the exact opposite of the intent."""
        monkeypatch.setattr(settings, "behaviour_hours_start", "21:00")
        monkeypatch.setattr(settings, "behaviour_hours_end", "07:00")
        assert is_within_behaviour_hours(time(23, 55)) is True
        assert is_within_behaviour_hours(time(3, 0)) is True
        assert is_within_behaviour_hours(time(12, 0)) is False

    def test_an_unparseable_setting_falls_back_instead_of_crashing(self, monkeypatch):
        monkeypatch.setattr(settings, "behaviour_hours_start", "not a time")
        monkeypatch.setattr(settings, "behaviour_hours_end", "21:00")
        assert is_within_behaviour_hours(time(13, 0)) is True
        assert is_within_behaviour_hours(time(3, 0)) is False


@pytest.mark.usefixtures("seeded")
class TestBehaviourHoursGate:
    @pytest.fixture
    async def a_behaviour_module(self, db_session):
        db_session.add(AIModuleConfig(
            code=917, group="D", name="Test", description="d", method="m", active=True,
        ))
        await db_session.commit()
        return 917

    @pytest.fixture(autouse=True)
    def _gate_module_917(self, monkeypatch):
        monkeypatch.setattr(settings, "behaviour_hours_enabled", True)
        monkeypatch.setattr(settings, "behaviour_hours_module_codes", "917")

    async def test_a_gated_module_is_inactive_outside_the_window(
        self, db_session, a_behaviour_module, monkeypatch
    ):
        monkeypatch.setattr("app.jobs.module_status.local_now", lambda: datetime(2026, 9, 4, 3, 0))
        assert await is_module_active(db_session, a_behaviour_module) is False

    async def test_the_same_module_is_active_inside_the_window(
        self, db_session, a_behaviour_module, monkeypatch
    ):
        monkeypatch.setattr("app.jobs.module_status.local_now", lambda: datetime(2026, 9, 4, 13, 0))
        assert await is_module_active(db_session, a_behaviour_module) is True

    async def test_an_ungated_module_runs_at_night(self, db_session, monkeypatch):
        """Security modules are deliberately NOT in the gated list — an
        intruder at 03:00 is the case they exist for."""
        db_session.add(AIModuleConfig(
            code=918, group="A", name="Security", description="d", method="m", active=True,
        ))
        await db_session.commit()
        monkeypatch.setattr("app.jobs.module_status.local_now", lambda: datetime(2026, 9, 4, 3, 0))
        assert await is_module_active(db_session, 918) is True

    async def test_the_gate_never_revives_a_module_switched_off_in_the_panel(
        self, db_session, monkeypatch
    ):
        db_session.add(AIModuleConfig(
            code=919, group="D", name="Off", description="d", method="m", active=False,
        ))
        await db_session.commit()
        monkeypatch.setattr(settings, "behaviour_hours_module_codes", "919")
        monkeypatch.setattr("app.jobs.module_status.local_now", lambda: datetime(2026, 9, 4, 13, 0))
        assert await is_module_active(db_session, 919) is False

    async def test_the_whole_gate_can_be_switched_off(
        self, db_session, a_behaviour_module, monkeypatch
    ):
        monkeypatch.setattr(settings, "behaviour_hours_enabled", False)
        monkeypatch.setattr("app.jobs.module_status.local_now", lambda: datetime(2026, 9, 4, 3, 0))
        assert await is_module_active(db_session, a_behaviour_module) is True
