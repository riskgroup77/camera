import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Building, Camera
from tests.conftest import auth_headers


@pytest.mark.usefixtures("seeded")
class TestOrgStructure:
    async def test_list_buildings(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/buildings", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    async def test_camera_count_reflects_real_registered_cameras_not_the_stale_field(
        self, client: AsyncClient, db_session
    ):
        """Regression: Building.camera_count is never set through any admin
        UI (AddBuildingModal.tsx always sends 0/whatever it already was) —
        GET /api/buildings must report the real, live count of registered
        Camera rows, not that dead field, or the dashboard silently lies
        about how many cameras are actually connected."""
        headers = await auth_headers(client, "admin", "admin123")
        building = (await db_session.execute(select(Building))).scalars().first()

        before = await client.get("/api/buildings", headers=headers)
        before_count = next(b["cameraCount"] for b in before.json() if b["id"] == str(building.id))
        assert before_count == 0

        db_session.add(
            Camera(
                name="Yangi kamera", ip="10.0.9.50", building_id=building.id,
                zone="Test", resolution="1080p", status="faol",
            )
        )
        await db_session.commit()

        after = await client.get("/api/buildings", headers=headers)
        after_count = next(b["cameraCount"] for b in after.json() if b["id"] == str(building.id))
        assert after_count == 1

    async def test_create_update_delete_building(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")

        created = await client.post(
            "/api/buildings", headers=headers, json={"name": "4-Bino (Sport majmuasi)", "cameraCount": 0}
        )
        assert created.status_code == 201
        building_id = created.json()["id"]

        updated = await client.patch(
            f"/api/buildings/{building_id}",
            headers=headers,
            json={"name": "4-Bino (Yangi nom)", "cameraCount": 2},
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "4-Bino (Yangi nom)"
        assert updated.json()["cameraCount"] == 2

        deleted = await client.delete(f"/api/buildings/{building_id}", headers=headers)
        assert deleted.status_code == 204

        listing = await client.get("/api/buildings", headers=headers)
        assert building_id not in [b["id"] for b in listing.json()]

    async def test_delete_unknown_building_is_404(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.delete("/api/buildings/00000000-0000-0000-0000-000000000000", headers=headers)
        assert resp.status_code == 404

    async def test_create_and_delete_faculty(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")

        created = await client.post("/api/faculties", headers=headers, json={"name": "Stomatologiya", "courseCount": 5})
        assert created.status_code == 201
        faculty_id = created.json()["id"]
        assert created.json()["studentCount"] == 0

        deleted = await client.delete(f"/api/faculties/{faculty_id}", headers=headers)
        assert deleted.status_code == 204

        listing = await client.get("/api/faculties", headers=headers)
        assert faculty_id not in [f["id"] for f in listing.json()]

    async def test_create_student_group_requires_known_faculty(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/student-groups",
            headers=headers,
            json={"name": "207-guruh", "facultyId": "00000000-0000-0000-0000-000000000000", "course": 2},
        )
        assert resp.status_code == 404

    async def test_create_and_delete_student_group(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")

        faculties = (await client.get("/api/faculties", headers=headers)).json()
        faculty = next(f for f in faculties if f["name"] == "Davolash ishi")

        created = await client.post(
            "/api/student-groups",
            headers=headers,
            json={"name": "207-guruh", "facultyId": faculty["id"], "course": 2},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["faculty"] == "Davolash ishi"
        group_id = body["id"]

        deleted = await client.delete(f"/api/student-groups/{group_id}", headers=headers)
        assert deleted.status_code == 204

        listing = await client.get("/api/student-groups", headers=headers)
        assert group_id not in [g["id"] for g in listing.json()]

    async def test_org_structure_requires_authentication(self, client: AsyncClient):
        resp = await client.get("/api/buildings")
        assert resp.status_code == 401
