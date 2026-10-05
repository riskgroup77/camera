import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select, update

from app.jobs.camera_health import run_camera_health_sweep_once
from app.models import Building, Camera, CameraOutage, Permission
from app.services import camera_health_dashboard as dash
from app.services import runtime_snapshot, video_gateway
from app.services.recognition_stats import RecognitionView
from app.timezone import local_now
from tests.conftest import auth_headers

URL = "/api/kamera-salomatligi"


@pytest.fixture(autouse=True)
def _reset_samples():
    dash.reset_for_tests()
    yield
    dash.reset_for_tests()


@pytest.fixture
async def a_building(db_session, seeded):
    return (await db_session.execute(select(Building))).scalars().first()


async def _camera(db, building, **kw) -> Camera:
    fields = dict(name="Kamera", ip="192.0.2.55", port=554, building_id=building.id, zone="Z",
                  resolution="1080p", status="faol")
    fields.update(kw)
    camera = Camera(**fields)
    db.add(camera)
    await db.commit()
    await db.refresh(camera)
    return camera


async def _outages(db, camera) -> list[CameraOutage]:
    camera_id = camera.id
    db.expire_all()
    rows = await db.execute(select(CameraOutage).where(CameraOutage.camera_id == camera_id))
    return list(rows.scalars().all())


class TestUptimeMath:
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

    def test_no_outages_is_full(self):
        assert dash.uptime_percent([], self.now - timedelta(days=1), self.now) == 100.0

    def test_clipped_to_window(self):
        # 2 soat oynadan oldin boshlangan, oyna ichida 6 soat davom etgan.
        start = self.now - timedelta(hours=26)
        end = self.now - timedelta(hours=18)
        assert dash.uptime_percent([(start, end)], self.now - timedelta(days=1), self.now) == 75.0

    def test_open_outage_runs_until_now(self):
        start = self.now - timedelta(hours=12)
        assert dash.uptime_percent([(start, None)], self.now - timedelta(days=1), self.now) == 50.0

    def test_overlaps_counted_once(self):
        a = (self.now - timedelta(hours=6), self.now - timedelta(hours=3))
        b = (self.now - timedelta(hours=4), self.now - timedelta(hours=2))
        assert dash.uptime_percent([a, b], self.now - timedelta(days=1), self.now) == round(100 * (1 - 4 / 24), 2)

    def test_outside_window_ignored(self):
        old = (self.now - timedelta(days=3), self.now - timedelta(days=2))
        assert dash.uptime_percent([old], self.now - timedelta(days=1), self.now) == 100.0


class TestBitrate:
    def test_first_sample_is_unknown_then_rate(self):
        assert dash.bitrate_mbps("rec-x", 0, now=100.0) is None
        # 10 soniyada 1_250_000 bayt = 1 Mbit/s
        assert dash.bitrate_mbps("rec-x", 1_250_000, now=110.0) == 1.0
        # Juda yaqin namuna — oldingi natija
        assert dash.bitrate_mbps("rec-x", 9_000_000, now=111.0) == 1.0

    def test_counter_reset_gives_none(self):
        dash.bitrate_mbps("rec-y", 5_000_000, now=0.0)
        assert dash.bitrate_mbps("rec-y", 100, now=10.0) is None


class TestMediamtxList:
    async def test_paginates(self):
        def handler(request: httpx.Request) -> httpx.Response:
            page = int(request.url.params["page"])
            items = [{"name": f"cam-{page}", "ready": True, "bytesReceived": 10 * page}]
            return httpx.Response(200, json={"pageCount": 2, "items": items})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            out = await dash._list_shard(client, "http://mtx")
        assert set(out) == {"cam-0", "cam-1"}
        assert out["cam-1"].bytes_received == 10

    async def test_unreachable_returns_none(self, monkeypatch):
        monkeypatch.setattr(video_gateway, "_get_shards", lambda: [video_gateway._Shard("http://127.0.0.1:1", "x")])
        assert await dash.fetch_mediamtx_paths() is None


@pytest.mark.usefixtures("seeded")
class TestOutageTracking:
    async def test_unreachable_opens_one_outage_idempotently(self, db_session, a_building):
        camera = await _camera(db_session, a_building)
        await run_camera_health_sweep_once(db_session)
        await run_camera_health_sweep_once(db_session)
        rows = await _outages(db_session, camera)
        assert len(rows) == 1
        assert rows[0].ended_at is None
        assert rows[0].reason == "tarmoq"

    async def test_restart_uses_last_seen_as_start(self, db_session, a_building):
        # Jarayon qayta ishga tushdi: xotira bo'sh, kamera allaqachon eskirgan.
        seen = datetime.now(timezone.utc) - timedelta(hours=2)
        camera = await _camera(db_session, a_building, last_seen_at=seen)
        await run_camera_health_sweep_once(db_session)
        rows = await _outages(db_session, camera)
        assert len(rows) == 1
        assert abs((rows[0].started_at - seen).total_seconds()) < 1

    async def test_single_miss_while_fresh_is_not_an_outage(self, db_session, a_building):
        camera = await _camera(db_session, a_building, last_seen_at=datetime.now(timezone.utc))
        await run_camera_health_sweep_once(db_session)
        assert await _outages(db_session, camera) == []

    async def test_recovery_closes_outage(self, db_session, a_building):
        server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            camera = await _camera(db_session, a_building, ip="127.0.0.1", port=port)
            db_session.add(CameraOutage(camera_id=camera.id, started_at=datetime.now(timezone.utc) - timedelta(minutes=10)))
            await db_session.commit()
            await run_camera_health_sweep_once(db_session)
        rows = await _outages(db_session, camera)
        assert len(rows) == 1 and rows[0].ended_at is not None

    async def test_disabled_camera_outage_is_closed(self, db_session, a_building):
        camera = await _camera(db_session, a_building, status="tamirda")
        db_session.add(CameraOutage(camera_id=camera.id, started_at=datetime.now(timezone.utc) - timedelta(minutes=10)))
        await db_session.commit()
        await run_camera_health_sweep_once(db_session)
        rows = await _outages(db_session, camera)
        assert rows[0].ended_at is not None


@pytest.mark.usefixtures("seeded")
class TestDashboardEndpoint:
    async def test_shape(self, client, db_session, a_building, monkeypatch):
        now = datetime.now(timezone.utc)
        online = await _camera(db_session, a_building, name="A", ip="10.0.0.1", last_seen_at=now, last_frame_at=now)
        offline = await _camera(db_session, a_building, name="B", ip="10.0.0.2", floor=2)
        # Uptime oynasi kamera yaratilgan paytdan boshlanadi — testda eski qilamiz.
        await db_session.execute(
            update(Camera).where(Camera.id.in_([online.id, offline.id])).values(created_at=now - timedelta(days=30))
        )
        db_session.add(CameraOutage(camera_id=offline.id, started_at=now - timedelta(hours=6)))
        db_session.add(
            CameraOutage(camera_id=online.id, started_at=now - timedelta(days=2), ended_at=now - timedelta(days=2) + timedelta(hours=1))
        )
        await db_session.commit()

        paths = {
            f"cam-{online.id}": dash.PathState(ready=True, bytes_received=0),
            f"rec-{online.id}": dash.PathState(ready=True, bytes_received=1000),
        }

        async def fake_paths():
            return paths

        async def fake_views():
            return {str(online.id): RecognitionView(day=local_now().date(), last_frame_at=now, stream="sub")}

        monkeypatch.setattr(dash, "fetch_mediamtx_paths", fake_paths)
        monkeypatch.setattr(runtime_snapshot, "load_recognition_views", fake_views)

        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get(URL, headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["mediamtxReachable"] is True
        assert body["summary"] == {
            "total": 2, "online": 1, "offline": 1, "noVideo": 0,
            "avgUptimeDay": 87.5, "recording": 1,
        }
        rows = {row["name"]: row for row in body["cameras"]}
        a, b = rows["A"], rows["B"]
        assert a["status"] == "online" and a["liveReady"] is True and a["recordingReady"] is True
        assert a["recordingMbps"] is None  # birinchi namuna
        assert a["aiStream"] == "sub" and a["aiLastAnalyzedAt"] is not None
        assert a["uptimeDay"] == 100.0 and a["outagesWeek"] == 1
        assert a["uptimeWeek"] == round(100 * (1 - 1 / (7 * 24)), 2)
        assert b["status"] == "offline" and b["offlineSince"] is not None
        assert b["uptimeDay"] == 75.0 and b["floor"] == 2
        assert b["liveReady"] is False and b["recordingReady"] is False
        assert b["building"] == a_building.name

        hist = await client.get(f"{URL}/{offline.id}/uzilishlar", headers=headers)
        assert hist.status_code == 200
        items = hist.json()["items"]
        assert len(items) == 1 and items[0]["endedAt"] is None and items[0]["durationSeconds"] >= 6 * 3600 - 5

    async def test_mediamtx_down_gives_nulls(self, client, db_session, a_building, monkeypatch):
        await _camera(db_session, a_building)

        async def no_paths():
            return None

        monkeypatch.setattr(dash, "fetch_mediamtx_paths", no_paths)
        headers = await auth_headers(client, "admin", "admin123")
        body = (await client.get(URL, headers=headers)).json()
        assert body["mediamtxReachable"] is False
        assert body["summary"]["recording"] is None
        assert body["cameras"][0]["liveReady"] is None

    async def test_permission(self, client, db_session, a_building):
        assert (await client.get(URL)).status_code == 401
        await db_session.execute(
            update(Permission)
            .where(Permission.key.in_(["systemSettings", "editCameraLocation"]))
            .values(admin=False)
        )
        await db_session.commit()
        headers = await auth_headers(client, "operator", "operator123")
        assert (await client.get(URL, headers=headers)).status_code == 403

    async def test_history_404(self, client, a_building):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get(f"{URL}/00000000-0000-0000-0000-000000000000/uzilishlar", headers=headers)
        assert resp.status_code == 404
