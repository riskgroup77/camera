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
        assert len(body) == 1
        cam = body[0]
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
        cam = next(c for c in resp.json() if c["name"] == "Hech qachon tekshirilmagan kamera")
        assert cam["status"] == "offline"

    async def test_public_stats_requires_no_auth(self, client: AsyncClient):
        resp = await client.get("/api/public/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {
            "totalStudents", "present", "absent", "late", "sleepIncidents", "violations",
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
