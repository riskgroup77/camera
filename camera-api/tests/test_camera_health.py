import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import settings
from app.jobs.camera_health import is_reachable, run_camera_health_sweep_once
from app.models import Building, Camera


@pytest.fixture
async def a_building(db_session, seeded):
    result = await db_session.execute(select(Building))
    return result.scalars().first()


class TestIsReachable:
    def test_none_is_not_reachable(self):
        assert is_reachable(None) is False

    def test_recent_timestamp_is_reachable(self):
        assert is_reachable(datetime.now(timezone.utc)) is True

    def test_stale_timestamp_is_not_reachable(self):
        stale = datetime.now(timezone.utc) - timedelta(seconds=settings.camera_health_freshness_seconds + 10)
        assert is_reachable(stale) is False


@pytest.mark.usefixtures("seeded")
class TestCameraHealthSweep:
    async def test_reachable_camera_gets_last_seen_stamped(self, db_session, a_building):
        # A real TCP listener on localhost — the same kind of genuine
        # reachability proof used by test_cameras.py's connection-test
        # coverage, not a mock.
        server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            camera = Camera(
                name="Sinov kamerasi", ip="127.0.0.1", port=port, building_id=a_building.id,
                zone="Z", resolution="1080p", status="faol",
            )
            db_session.add(camera)
            await db_session.commit()

            reachable_count = await run_camera_health_sweep_once(db_session)
            assert reachable_count == 1

            await db_session.refresh(camera)
            assert camera.last_seen_at is not None
            assert is_reachable(camera.last_seen_at) is True

    async def test_unreachable_camera_is_not_stamped(self, db_session, a_building):
        # 192.0.2.0/24 is TEST-NET-1 (RFC 5737) — guaranteed unreachable,
        # same convention already used in test_cameras.py.
        camera = Camera(
            name="Ulanmaydigan kamera", ip="192.0.2.55", port=554, building_id=a_building.id,
            zone="Z", resolution="1080p", status="faol",
        )
        db_session.add(camera)
        await db_session.commit()

        reachable_count = await run_camera_health_sweep_once(db_session)
        assert reachable_count == 0

        await db_session.refresh(camera)
        assert camera.last_seen_at is None
        assert is_reachable(camera.last_seen_at) is False

    async def test_inactive_camera_is_not_swept(self, db_session, a_building):
        """nofaol/tamirda cameras are skipped — status='faol' is what marks
        a camera as one the admin currently wants watched."""
        server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            camera = Camera(
                name="Nofaol kamera", ip="127.0.0.1", port=port, building_id=a_building.id,
                zone="Z", resolution="1080p", status="nofaol",
            )
            db_session.add(camera)
            await db_session.commit()

            reachable_count = await run_camera_health_sweep_once(db_session)
            assert reachable_count == 0

            await db_session.refresh(camera)
            assert camera.last_seen_at is None
