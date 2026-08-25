from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Building, Camera
from tests.conftest import auth_headers


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Ommaviy test kamerasi",
        ip="10.0.0.9",
        building_id=building.id,
        zone="Z",
        resolution="1080p",
        status="faol",
        # Simulates app/jobs/camera_health.py having just swept this camera
        # successfully — public "live" status needs both status='faol' AND
        # a fresh last_seen_at, not status alone.
        last_seen_at=datetime.now(timezone.utc),
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera)
    return camera


@pytest.mark.usefixtures("seeded")
class TestPublicEndpoints:
    async def test_public_cameras_requires_no_auth_and_hides_credentials(self, client: AsyncClient, a_camera):
        resp = await client.get("/api/public/cameras")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        cam = body["items"][0]
        assert cam["name"] == "Ommaviy test kamerasi"
        assert cam["status"] == "live"
        assert "ip" not in cam
        assert "rtspPath" not in cam
        assert "rtspUsername" not in cam

    async def test_faol_camera_never_swept_shows_offline_not_live(self, client: AsyncClient, db_session):
        """The exact bug this feature fixes: before app/jobs/camera_health.py,
        status='faol' alone made a camera show as JONLI on the public page
        forever, even if it had never actually been reached (or its cable
        was unplugged) — status is admin intent, not an observation."""
        building = (await db_session.execute(select(Building))).scalars().first()
        camera = Camera(
            name="Hech qachon tekshirilmagan kamera",
            ip="192.0.2.88",
            building_id=building.id,
            zone="Z",
            resolution="1080p",
            status="faol",
            last_seen_at=None,
        )
        db_session.add(camera)
        await db_session.commit()

        resp = await client.get("/api/public/cameras")
        cam = next(c for c in resp.json()["items"] if c["name"] == "Hech qachon tekshirilmagan kamera")
        assert cam["status"] == "offline"

    async def test_public_stats_requires_no_auth(self, client: AsyncClient):
        resp = await client.get("/api/public/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {
            "totalStudents", "present", "absent", "late", "sleepIncidents", "violations",
            "liveCameras", "offlineCameras", "buildings",
        }

    async def test_public_stats_reflects_real_attendance(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        student = (
            await client.post(
                "/api/students-staff",
                headers=headers,
                json={"fullName": "Ochiq Talaba", "type": "talaba", "faculty": "Davolash ishi", "groupOrPosition": "1"},
            )
        ).json()
        today = date.today().isoformat()
        await client.post(
            "/api/attendance",
            headers=headers,
            json={"studentStaffId": student["id"], "date": today, "status": "keldi"},
        )

        resp = await client.get("/api/public/stats")
        assert resp.json()["present"] == 1
        assert resp.json()["totalStudents"] >= 1

    async def test_top_students_ranks_by_real_attendance_rate(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        student = (
            await client.post(
                "/api/students-staff",
                headers=headers,
                json={"fullName": "Reyting Talaba", "type": "talaba", "faculty": "Davolash ishi", "groupOrPosition": "5-guruh"},
            )
        ).json()
        today = date.today().isoformat()
        await client.post(
            "/api/attendance",
            headers=headers,
            json={"studentStaffId": student["id"], "date": today, "status": "keldi"},
        )

        resp = await client.get("/api/public/top-students")
        assert resp.status_code == 200
        body = resp.json()
        assert any(s["id"] == student["id"] and s["attendanceRate"] == 100 for s in body)

    async def test_live_detection_unknown_camera_is_404(self, client: AsyncClient):
        resp = await client.get("/api/public/cameras/00000000-0000-0000-0000-000000000000/live-detection")
        assert resp.status_code == 404

    async def test_live_detection_camera_without_stream_returns_empty(self, client: AsyncClient, a_camera):
        # a_camera has no stream_url configured -- no ffmpeg/RTSP available
        # to actually grab a frame from in this test environment, so the
        # endpoint's early-return path is what's under test here.
        resp = await client.get(f"/api/public/cameras/{a_camera.id}/live-detection")
        assert resp.status_code == 200
        body = resp.json()
        assert body["faces"] == []
        assert body["frameWidth"] == 0
        assert body["frameHeight"] == 0

    async def test_public_cameras_pagination_bounds_page_size(self, client: AsyncClient, db_session):
        building = (await db_session.execute(select(Building))).scalars().first()
        for i in range(5):
            db_session.add(
                Camera(
                    name=f"Sahifa kamerasi {i}", ip=f"10.0.1.{i}", building_id=building.id, zone="Z",
                    resolution="1080p", status="faol",
                )
            )
        await db_session.commit()

        resp = await client.get("/api/public/cameras?pageSize=2&page=1")
        body = resp.json()
        assert body["total"] == 5
        assert body["totalPages"] == 3
        assert len(body["items"]) == 2

        resp2 = await client.get("/api/public/cameras?pageSize=2&page=3")
        assert len(resp2.json()["items"]) == 1  # last page has the 1 remaining camera

    async def test_public_cameras_search_filters_by_name_or_zone(self, client: AsyncClient, db_session):
        building = (await db_session.execute(select(Building))).scalars().first()
        db_session.add(
            Camera(
                name="Kirish nazorati", ip="10.0.2.1", building_id=building.id, zone="Bosh kirish",
                resolution="1080p", status="faol",
            )
        )
        db_session.add(
            Camera(
                name="Boshqa kamera", ip="10.0.2.2", building_id=building.id, zone="Ombor",
                resolution="1080p", status="faol",
            )
        )
        await db_session.commit()

        resp = await client.get("/api/public/cameras?search=kirish")
        names = [c["name"] for c in resp.json()["items"]]
        assert names == ["Kirish nazorati"]  # matches by name

        resp2 = await client.get("/api/public/cameras?search=Ombor")
        names2 = [c["name"] for c in resp2.json()["items"]]
        assert names2 == ["Boshqa kamera"]  # matches by zone

    async def test_public_cameras_status_filter(self, client: AsyncClient, a_camera, db_session):
        building = (await db_session.execute(select(Building))).scalars().first()
        db_session.add(
            Camera(
                name="Oflayn kamera", ip="10.0.3.1", building_id=building.id, zone="Z",
                resolution="1080p", status="faol", last_seen_at=None,
            )
        )
        await db_session.commit()

        live_resp = await client.get("/api/public/cameras?status=live")
        live_names = [c["name"] for c in live_resp.json()["items"]]
        assert live_names == [a_camera.name]

        offline_resp = await client.get("/api/public/cameras?status=offline")
        offline_names = [c["name"] for c in offline_resp.json()["items"]]
        assert offline_names == ["Oflayn kamera"]

    async def test_public_cameras_building_filter(self, client: AsyncClient, db_session):
        buildings = (await db_session.execute(select(Building))).scalars().all()
        assert len(buildings) >= 2
        db_session.add(
            Camera(
                name="Birinchi bino kamerasi", ip="10.0.4.1", building_id=buildings[0].id, zone="Z",
                resolution="1080p", status="faol",
            )
        )
        db_session.add(
            Camera(
                name="Ikkinchi bino kamerasi", ip="10.0.4.2", building_id=buildings[1].id, zone="Z",
                resolution="1080p", status="faol",
            )
        )
        await db_session.commit()

        resp = await client.get(f"/api/public/cameras?building={buildings[0].name}")
        names = [c["name"] for c in resp.json()["items"]]
        assert "Birinchi bino kamerasi" in names
        assert "Ikkinchi bino kamerasi" not in names

    async def test_public_stats_camera_counts_and_buildings(self, client: AsyncClient, a_camera, db_session):
        building = (await db_session.execute(select(Building))).scalars().first()
        db_session.add(
            Camera(
                name="Oflayn statistika kamerasi", ip="10.0.5.1", building_id=building.id, zone="Z",
                resolution="1080p", status="faol", last_seen_at=None,
            )
        )
        await db_session.commit()

        resp = await client.get("/api/public/stats")
        body = resp.json()
        assert body["liveCameras"] >= 1
        assert body["offlineCameras"] >= 1
        assert building.name in body["buildings"]

    async def test_top_students_excludes_students_with_no_attendance(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        await client.post(
            "/api/students-staff",
            headers=headers,
            json={"fullName": "Yozuvsiz Talaba", "type": "talaba", "faculty": "Davolash ishi", "groupOrPosition": "1"},
        )

        resp = await client.get("/api/public/top-students")
        names = [s["name"] for s in resp.json()]
        assert "Yozuvsiz Talaba" not in names
