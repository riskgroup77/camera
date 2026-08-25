import pytest
from sqlalchemy import select

from app.jobs.module_status import any_module_active, camera_allows_module, is_module_active
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
