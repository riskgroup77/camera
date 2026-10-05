import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers


@pytest.mark.usefixtures("seeded")
class TestStudentsStaff:
    async def test_create_and_fetch(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/students-staff",
            headers=headers,
            json={
                "fullName": "Karimova Dildora",
                "type": "talaba",
                "faculty": "Davolash ishi",
                "groupOrPosition": "302-guruh",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["faculty"] == "Davolash ishi"
        assert body["initials"] == "KD"
        assert body["biometricsStatus"] == "yoq"

    async def test_unknown_faculty_is_404(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/students-staff",
            headers=headers,
            json={"fullName": "Test Kishi", "type": "talaba", "faculty": "Yoq Fakultet", "groupOrPosition": "1"},
        )
        assert resp.status_code == 404

    async def test_filter_by_faculty(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        await client.post(
            "/api/students-staff",
            headers=headers,
            json={"fullName": "Aliyev Aziz", "type": "talaba", "faculty": "Davolash ishi", "groupOrPosition": "1"},
        )
        await client.post(
            "/api/students-staff",
            headers=headers,
            json={"fullName": "Botirov Bekzod", "type": "talaba", "faculty": "Farmatsiya", "groupOrPosition": "1"},
        )
        resp = await client.get("/api/students-staff", headers=headers, params={"faculty": "Farmatsiya"})
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["fullName"] == "Botirov Bekzod"

    async def test_search_matches_partial_name(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        await client.post(
            "/api/students-staff",
            headers=headers,
            json={"fullName": "Sharipova Feruza", "type": "talaba", "faculty": "Davolash ishi", "groupOrPosition": "1"},
        )
        resp = await client.get("/api/students-staff", headers=headers, params={"search": "sharipova"})
        assert resp.json()["total"] == 1

    async def test_update_record(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = (
            await client.post(
                "/api/students-staff",
                headers=headers,
                json={"fullName": "Old Name", "type": "talaba", "faculty": "Davolash ishi", "groupOrPosition": "1"},
            )
        ).json()

        resp = await client.patch(
            f"/api/students-staff/{created['id']}",
            headers=headers,
            json={"fullName": "New Name", "type": "xodim", "faculty": "Farmatsiya", "groupOrPosition": "Farmatsevt"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["fullName"] == "New Name"
        assert body["faculty"] == "Farmatsiya"
        assert body["type"] == "xodim"

    async def test_update_missing_record_is_404(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.patch(
            "/api/students-staff/00000000-0000-0000-0000-000000000000",
            headers=headers,
            json={"fullName": "Test Kishilar", "type": "talaba", "faculty": "Davolash ishi", "groupOrPosition": "1"},
        )
        assert resp.status_code == 404

    async def test_operator_without_register_people_is_forbidden(self, client: AsyncClient):
        super_headers = await auth_headers(client, "admin", "admin123")
        await client.patch("/api/permissions/registerPeople", headers=super_headers, json={"role": "admin"})
        # toggled off from its default True
        admin_headers = await auth_headers(client, "operator", "operator123")
        resp = await client.get("/api/students-staff", headers=admin_headers)
        assert resp.status_code == 403
