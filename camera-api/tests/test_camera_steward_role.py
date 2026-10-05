"""Kamera mas'uli roli — kamera ma'lumotini to'g'rilaydi, boshqa hech narsani.

Bu rol kamera ULANISHIGA tegmasligi kerak: uning so'rovida IP, port,
RTSP yo'li va login/parol umuman bo'lmaydi, shuning uchun bu testlar
avvalo "tegilmagan" ekanini va ruxsat chegaralarini tekshiradi.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Building, Camera, User
from app.security import hash_password
from tests.conftest import auth_headers

STEWARD_LOGIN = "kamera1"
STEWARD_PASSWORD = "kamera-parol-123"


@pytest.fixture
async def steward(db_session, seeded) -> User:
    user = User(
        login=STEWARD_LOGIN,
        password_hash=hash_password(STEWARD_PASSWORD),
        full_name="Kamera Mas'uli Birinchi",
        role="kamera-masuli",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def camera(db_session, seeded) -> Camera:
    building = (await db_session.execute(select(Building).order_by(Building.name))).scalars().first()
    row = Camera(
        name="Eski nom",
        ip="10.10.0.5",
        port=554,
        rtsp_path="/Streaming/Channels/101",
        rtsp_username="shifrlangan-login",
        rtsp_password="shifrlangan-parol",
        building_id=building.id,
        zone="Koridor",
        floor=1,
        resolution="1080p",
        status="faol",
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest.mark.usefixtures("seeded")
class TestStewardCanFixCameraData:
    async def test_can_read_the_camera_list(self, client: AsyncClient, steward, camera):
        headers = await auth_headers(client, STEWARD_LOGIN, STEWARD_PASSWORD)
        resp = await client.get("/api/cameras", headers=headers, params={"pageSize": 50})
        assert resp.status_code == 200
        assert any(item["name"] == "Eski nom" for item in resp.json()["items"])

    async def test_location_edit_never_touches_the_connection(
        self, client: AsyncClient, db_session, steward, camera
    ):
        headers = await auth_headers(client, STEWARD_LOGIN, STEWARD_PASSWORD)
        other_building = (
            await db_session.execute(select(Building).order_by(Building.name.desc()))
        ).scalars().first()

        resp = await client.patch(
            f"/api/cameras/{camera.id}/location",
            headers=headers,
            json={"name": "2-qavat koridor", "building": other_building.name, "floor": 2, "zone": "Koridor-2"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "2-qavat koridor"
        assert body["building"] == other_building.name
        assert body["floor"] == 2 and body["zone"] == "Koridor-2"

        await db_session.refresh(camera)
        assert camera.ip == "10.10.0.5"
        assert camera.port == 554
        assert camera.rtsp_path == "/Streaming/Channels/101"
        assert camera.rtsp_username == "shifrlangan-login"
        assert camera.rtsp_password == "shifrlangan-parol"
        assert camera.status == "faol"

    async def test_omitted_fields_stay_as_they_were(self, client: AsyncClient, db_session, steward, camera):
        headers = await auth_headers(client, STEWARD_LOGIN, STEWARD_PASSWORD)
        resp = await client.patch(
            f"/api/cameras/{camera.id}/location", headers=headers, json={"zone": "Kirish"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["zone"] == "Kirish"
        assert body["name"] == "Eski nom"  # nom yuborilmagan — o'zgarmadi
        assert body["floor"] == 1

    async def test_floor_can_be_cleared_explicitly(self, client: AsyncClient, steward, camera):
        headers = await auth_headers(client, STEWARD_LOGIN, STEWARD_PASSWORD)
        resp = await client.patch(
            f"/api/cameras/{camera.id}/location", headers=headers, json={"clearFloor": True}
        )
        assert resp.status_code == 200 and resp.json()["floor"] is None

    async def test_bulk_location_is_allowed(self, client: AsyncClient, steward, camera):
        headers = await auth_headers(client, STEWARD_LOGIN, STEWARD_PASSWORD)
        resp = await client.post(
            "/api/cameras/bulk-location",
            headers=headers,
            json={"cameraIds": [str(camera.id)], "floor": 3},
        )
        assert resp.status_code == 200 and resp.json()["updated"] == 1

    async def test_unknown_camera_is_404(self, client: AsyncClient, steward):
        headers = await auth_headers(client, STEWARD_LOGIN, STEWARD_PASSWORD)
        missing = await client.patch(
            "/api/cameras/00000000-0000-0000-0000-000000000000/location", headers=headers, json={"zone": "X"}
        )
        assert missing.status_code == 404
        assert (
            await client.patch("/api/cameras/not-a-uuid/location", headers=headers, json={"zone": "X"})
        ).status_code == 404


@pytest.mark.usefixtures("seeded")
class TestStewardCannotDoAnythingElse:
    async def test_cannot_add_edit_or_delete_a_camera(self, client: AsyncClient, steward, camera):
        headers = await auth_headers(client, STEWARD_LOGIN, STEWARD_PASSWORD)
        created = await client.post(
            "/api/cameras",
            headers=headers,
            json={
                "name": "Yangi kamera",
                "ip": "10.10.0.9",
                "building": "1-Bino (Asosiy korpus)",
                "zone": "Zona",
                "resolution": "1080p",
            },
        )
        assert created.status_code == 403

        full_edit = await client.patch(
            f"/api/cameras/{camera.id}",
            headers=headers,
            json={
                "name": "Nom",
                "ip": "10.10.0.5",
                "building": "1-Bino (Asosiy korpus)",
                "zone": "Zona",
                "resolution": "1080p",
                "status": "faol",
            },
        )
        assert full_edit.status_code == 403

        assert (
            await client.patch(f"/api/cameras/{camera.id}/modules", headers=headers, json={})
        ).status_code == 403
        assert (
            await client.patch(
                f"/api/cameras/{camera.id}/zone-polygon", headers=headers, json={"polygon": None}
            )
        ).status_code == 403

    async def test_cannot_reach_other_sections(self, client: AsyncClient, steward):
        headers = await auth_headers(client, STEWARD_LOGIN, STEWARD_PASSWORD)
        assert (await client.get("/api/students-staff", headers=headers)).status_code == 403
        assert (await client.get("/api/users", headers=headers)).status_code == 403
        assert (await client.get("/api/ai-modules", headers=headers)).status_code == 403
        assert (await client.get("/api/audit-log", headers=headers)).status_code == 403


@pytest.mark.usefixtures("seeded")
class TestAdminsKeepEverything:
    async def test_admin_can_use_the_location_endpoint_too(self, client: AsyncClient, camera):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.patch(
            f"/api/cameras/{camera.id}/location", headers=headers, json={"zone": "Admin zonasi"}
        )
        assert resp.status_code == 200 and resp.json()["zone"] == "Admin zonasi"

    async def test_admin_still_sees_the_camera_list(self, client: AsyncClient, camera):
        headers = await auth_headers(client, "admin", "admin123")
        assert (await client.get("/api/cameras", headers=headers)).status_code == 200

    async def test_permission_matrix_exposes_the_third_role(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        matrix = (await client.get("/api/permissions", headers=headers)).json()
        assert matrix["editCameraLocation"]["cameraSteward"] is True
        assert matrix["manageCameras"]["cameraSteward"] is False
