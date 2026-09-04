import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import settings
from app.jobs.camera_health import is_reachable, is_video_flowing, run_camera_health_sweep_once
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

    async def test_offline_alert_writes_audit_log_with_valid_status(self, db_session, a_building, monkeypatch):
        monkeypatch.setattr(settings, "camera_offline_alert_minutes", 0)
        camera = Camera(
            name="Alert kamera",
            ip="192.0.2.66",
            port=554,
            building_id=a_building.id,
            zone="Z",
            resolution="1080p",
            status="faol",
        )
        db_session.add(camera)
        await db_session.commit()

        await run_camera_health_sweep_once(db_session)

        from app.models import AuditLog

        result = await db_session.execute(
            select(AuditLog).where(AuditLog.module == "Kameralar", AuditLog.action.like("%Alert kamera%"))
        )
        entry = result.scalars().first()
        assert entry is not None
        assert entry.status == "ogohlantirish"


class TestVideoFlowing:
    """A camera answering on its RTSP port is not the same as a camera
    producing a picture. Measured on production: 6 of 107 were reachable
    and decoded to a flat grey frame, while the wall showed them JONLI.
    Nothing in the system could tell those two states apart."""

    def test_a_camera_that_never_produced_a_frame_is_not_flowing(self):
        assert is_video_flowing(None) is False

    def test_a_recent_frame_counts_as_flowing(self):
        assert is_video_flowing(datetime.now(timezone.utc)) is True

    def test_an_old_frame_does_not(self):
        stale = datetime.now(timezone.utc) - timedelta(
            seconds=settings.camera_video_stale_seconds + 1
        )
        assert is_video_flowing(stale) is False

    def test_the_video_window_is_wider_than_the_reachability_one(self):
        """Some cameras take up to 25 seconds to hand over their first
        frame (measured). A window as tight as the ping check would mark
        a healthy but slow camera as broken."""
        assert settings.camera_video_stale_seconds > settings.camera_health_freshness_seconds


@pytest.mark.usefixtures("seeded")
class TestSweepRecordsVideo:
    async def test_a_reachable_camera_with_a_frame_is_stamped(
        self, db_session, a_building, monkeypatch
    ):
        camera = Camera(
            name="Tasvirli", ip="10.0.0.61", building_id=a_building.id, zone="Z",
            resolution="1080p", status="faol", stream_url="rtsp://fake/a",
        )
        db_session.add(camera)
        await db_session.commit()

        monkeypatch.setattr("app.jobs.camera_health.tcp_check", _reachable)
        monkeypatch.setattr("app.jobs.camera_health.peek_cached_frame", lambda _url: b"jpeg")

        await run_camera_health_sweep_once(db_session)
        await db_session.refresh(camera)
        assert camera.last_seen_at is not None
        assert camera.last_frame_at is not None

    async def test_a_reachable_camera_without_a_frame_is_not_stamped(
        self, db_session, a_building, monkeypatch
    ):
        """This is the case the whole change exists for: the ping
        succeeds, so last_seen_at advances and the camera reads as live,
        while no picture ever arrives."""
        camera = Camera(
            name="Tasvirsiz", ip="10.0.0.62", building_id=a_building.id, zone="Z",
            resolution="1080p", status="faol", stream_url="rtsp://fake/b",
        )
        db_session.add(camera)
        await db_session.commit()

        monkeypatch.setattr("app.jobs.camera_health.tcp_check", _reachable)
        monkeypatch.setattr("app.jobs.camera_health.peek_cached_frame", lambda _url: None)

        await run_camera_health_sweep_once(db_session)
        await db_session.refresh(camera)
        assert camera.last_seen_at is not None
        assert camera.last_frame_at is None
        assert is_reachable(camera.last_seen_at) is True
        assert is_video_flowing(camera.last_frame_at) is False


async def _reachable(_ip, _port):
    return True, 1.0
