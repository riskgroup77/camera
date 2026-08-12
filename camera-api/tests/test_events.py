import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Building, Camera
from tests.conftest import auth_headers


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(name="Test kamerasi", ip="10.0.0.5", building_id=building.id, zone="Z", resolution="1080p")
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera)
    return camera


@pytest.mark.usefixtures("seeded")
class TestEvents:
    async def test_create_event_snapshots_camera_and_building(self, client: AsyncClient, a_camera):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/events",
            headers=headers,
            json={
                "cameraId": str(a_camera.id),
                "moduleCode": 7,
                "moduleName": "Talaba davomati",
                "group": "B",
                "confidence": 88,
                "severity": "past",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["cameraName"] == "Test kamerasi"
        assert body["status"] == "yangi"

    async def test_unknown_camera_is_404(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/events",
            headers=headers,
            json={
                "cameraId": "00000000-0000-0000-0000-000000000000",
                "moduleCode": 1,
                "moduleName": "X",
                "group": "A",
                "confidence": 50,
                "severity": "past",
            },
        )
        assert resp.status_code == 404

    async def test_review_sets_status_and_reviewer_name(self, client: AsyncClient, a_camera):
        headers = await auth_headers(client, "admin", "admin123")
        created = (
            await client.post(
                "/api/events",
                headers=headers,
                json={
                    "cameraId": str(a_camera.id),
                    "moduleCode": 1,
                    "moduleName": "X",
                    "group": "A",
                    "confidence": 50,
                    "severity": "past",
                },
            )
        ).json()

        resp = await client.patch(
            f"/api/events/{created['id']}/review", headers=headers, json={"status": "tasdiqlangan"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "tasdiqlangan"
        assert body["reviewedBy"] == "Jamshid Alimov"

    async def test_filter_by_severity(self, client: AsyncClient, a_camera):
        headers = await auth_headers(client, "admin", "admin123")
        for severity in ["past", "yuqori"]:
            await client.post(
                "/api/events",
                headers=headers,
                json={
                    "cameraId": str(a_camera.id),
                    "moduleCode": 1,
                    "moduleName": "X",
                    "group": "A",
                    "confidence": 50,
                    "severity": severity,
                },
            )
        resp = await client.get("/api/events", headers=headers, params={"severity": "yuqori"})
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["severity"] == "yuqori"

    async def test_filter_by_today(self, client: AsyncClient, a_camera):
        headers = await auth_headers(client, "admin", "admin123")
        await client.post(
            "/api/events",
            headers=headers,
            json={
                "cameraId": str(a_camera.id),
                "moduleCode": 1,
                "moduleName": "X",
                "group": "A",
                "confidence": 50,
                "severity": "past",
            },
        )
        resp = await client.get("/api/events", headers=headers, params={"today": True})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_delete_event(self, client: AsyncClient, a_camera):
        headers = await auth_headers(client, "admin", "admin123")
        created = (
            await client.post(
                "/api/events",
                headers=headers,
                json={
                    "cameraId": str(a_camera.id),
                    "moduleCode": 1,
                    "moduleName": "X",
                    "group": "A",
                    "confidence": 50,
                    "severity": "past",
                },
            )
        ).json()

        resp = await client.delete(f"/api/events/{created['id']}", headers=headers)
        assert resp.status_code == 204

        listed = await client.get("/api/events", headers=headers)
        assert listed.json()["total"] == 0

    async def test_delete_unknown_event_is_404(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.delete("/api/events/00000000-0000-0000-0000-000000000000", headers=headers)
        assert resp.status_code == 404
