"""PTZ API (app/routers/ptz.py) va kamera PTZ sozlamalari (app/routers/cameras.py)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.crypto import encrypt
from app.models import AuditLog, Building, Camera, User
from app.security import hash_password
from app.services import ptz
from tests.conftest import auth_headers
from tests.ptz_fake_camera import FakeIsapiCamera, FakeOnvifCamera, router_transport

CAM_IP = "10.30.0.15"
STEWARD_LOGIN = "ptz-kuzatuvchi"
STEWARD_PASSWORD = "kuzatuvchi-parol-1"


@pytest.fixture(autouse=True)
def _reset_ptz():
    ptz.reset_ptz_state_for_tests()
    yield
    ptz.set_transport_for_tests(None)
    ptz.reset_ptz_state_for_tests()


@pytest.fixture
def onvif_cam() -> FakeOnvifCamera:
    cam = FakeOnvifCamera()
    ptz.set_transport_for_tests(router_transport({f"{CAM_IP}:8000": cam.handler}))
    return cam


async def _camera(db_session, *, enabled=True, protocol="onvif", port=8000, username="admin", password="Parol-123") -> Camera:
    building = (await db_session.execute(select(Building).order_by(Building.name))).scalars().first()
    row = Camera(
        name="Hovli PTZ",
        ip=CAM_IP,
        port=554,
        rtsp_username=encrypt(username),
        rtsp_password=encrypt(password),
        building_id=building.id,
        zone="Hovli",
        resolution="1080p",
        status="faol",
        ptz_enabled=enabled,
        ptz_protocol=protocol,
        onvif_port=port,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest.fixture
async def steward(db_session, seeded) -> User:
    user = User(
        login=STEWARD_LOGIN,
        password_hash=hash_password(STEWARD_PASSWORD),
        full_name="Kamera Mas'uli",
        role="kamera-masuli",
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.mark.usefixtures("seeded")
class TestPtzControl:
    async def test_move_stop_uses_decrypted_credentials(self, client: AsyncClient, db_session, onvif_cam):
        camera = await _camera(db_session)
        headers = await auth_headers(client, "operator", "operator123")  # admin roli — controlPtz bor

        resp = await client.post(
            f"/api/cameras/{camera.id}/ptz/move", headers=headers, json={"pan": 0.5, "tilt": -0.5, "zoom": 0}
        )
        assert resp.status_code == 204, resp.text
        resp = await client.post(f"/api/cameras/{camera.id}/ptz/stop", headers=headers)
        assert resp.status_code == 204
        assert onvif_cam.actions()[-2:] == ["ContinuousMove", "Stop"]
        # Soxta kamera digest'ni parol bilan tekshiradi — o'tgani login/parol to'g'ri ochilganini bildiradi.
        assert onvif_cam.calls[-1].username == "admin"

        # Harakatlar jurnalga yozilmaydi.
        logs = (await db_session.execute(select(AuditLog).where(AuditLog.action.ilike("%PTZ%")))).scalars().all()
        assert logs == []

    async def test_disabled_camera_is_409(self, client: AsyncClient, db_session, onvif_cam):
        camera = await _camera(db_session, enabled=False)
        headers = await auth_headers(client, "admin", "admin123")
        for method, path, body in [
            ("post", "ptz/move", {"pan": 0.2}),
            ("post", "ptz/stop", None),
            ("get", "ptz/presets", None),
            ("post", "ptz/presets/1/goto", None),
            ("post", "ptz/presets", {"name": "Yangi"}),
        ]:
            kwargs = {"headers": headers}
            if body is not None:
                kwargs["json"] = body
            resp = await getattr(client, method)(f"/api/cameras/{camera.id}/{path}", **kwargs)
            assert resp.status_code == 409, (path, resp.text)
            assert "PTZ boshqaruvi yoqilmagan" in resp.json()["detail"]
        assert onvif_cam.calls == []

    async def test_permissions(self, client: AsyncClient, db_session, steward, onvif_cam):
        camera = await _camera(db_session)
        resp = await client.post(f"/api/cameras/{camera.id}/ptz/move", json={"pan": 0.2})
        assert resp.status_code == 401

        headers = await auth_headers(client, STEWARD_LOGIN, STEWARD_PASSWORD)
        for method, path in [("post", "ptz/stop"), ("get", "ptz/presets"), ("get", "ptz"), ("post", "ptz/probe")]:
            resp = await getattr(client, method)(f"/api/cameras/{camera.id}/{path}", headers=headers)
            assert resp.status_code == 403, path
        resp = await client.post("/api/cameras/ptz/probe", headers=headers, json={"ip": CAM_IP})
        assert resp.status_code == 403
        assert onvif_cam.calls == []

    async def test_validation(self, client: AsyncClient, db_session, onvif_cam):
        camera = await _camera(db_session)
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(f"/api/cameras/{camera.id}/ptz/move", headers=headers, json={"pan": 1.5})
        assert resp.status_code == 422
        resp = await client.post(
            f"/api/cameras/{camera.id}/ptz/move", headers=headers, json={"pan": 0.1, "durationMs": 50}
        )
        assert resp.status_code == 422
        resp = await client.post("/api/cameras/not-a-uuid/ptz/stop", headers=headers)
        assert resp.status_code == 404
        resp = await client.post(f"/api/cameras/{camera.id}/ptz/presets", headers=headers, json={"name": "   "})
        assert resp.status_code == 422

    async def test_presets_goto_and_save_is_audited(self, client: AsyncClient, db_session, onvif_cam):
        camera = await _camera(db_session)
        headers = await auth_headers(client, "admin", "admin123")

        resp = await client.get(f"/api/cameras/{camera.id}/ptz/presets", headers=headers)
        assert resp.status_code == 200
        assert resp.json() == [{"token": "1", "name": "Kirish eshigi"}, {"token": "2", "name": "Hovli"}]

        resp = await client.post(f"/api/cameras/{camera.id}/ptz/presets/2/goto", headers=headers)
        assert resp.status_code == 204
        assert onvif_cam.actions()[-1] == "GotoPreset"

        resp = await client.post(f"/api/cameras/{camera.id}/ptz/presets", headers=headers, json={"name": " Darvoza "})
        assert resp.status_code == 201
        assert resp.json() == {"token": "3", "name": "Darvoza"}
        log = (await db_session.execute(select(AuditLog).where(AuditLog.action.ilike("%PTZ preset%")))).scalar_one()
        assert "Hovli PTZ" in log.action and "Darvoza" in log.action

    async def test_camera_errors_are_mapped(self, client: AsyncClient, db_session, onvif_cam):
        headers = await auth_headers(client, "admin", "admin123")

        camera = await _camera(db_session, password="eski-parol")
        resp = await client.post(f"/api/cameras/{camera.id}/ptz/move", headers=headers, json={"pan": 0.2})
        # 401 EMAS — aks holda frontend foydalanuvchini tizimdan chiqarib yuborardi.
        assert resp.status_code == 502
        assert "paroli noto'g'ri" in resp.json()["detail"]

        onvif_cam.ptz = False
        camera.rtsp_password = encrypt(onvif_cam.password)
        await db_session.commit()
        resp = await client.post(f"/api/cameras/{camera.id}/ptz/stop", headers=headers)
        assert resp.status_code == 422
        assert "PTZ" in resp.json()["detail"]

        camera.onvif_port = 9999  # hech kim tinglamaydi
        await db_session.commit()
        resp = await client.post(f"/api/cameras/{camera.id}/ptz/stop", headers=headers)
        assert resp.status_code == 502
        assert "ulanib bo'lmadi" in resp.json()["detail"]

    async def test_isapi_camera(self, client: AsyncClient, db_session):
        cam = FakeIsapiCamera()
        ptz.set_transport_for_tests(router_transport({f"{CAM_IP}:80": cam.handler}))
        camera = await _camera(db_session, protocol="isapi", port=None, username=cam.username, password=cam.password)
        headers = await auth_headers(client, "admin", "admin123")

        resp = await client.post(
            f"/api/cameras/{camera.id}/ptz/move", headers=headers, json={"pan": 0, "tilt": 0.25, "zoom": -1}
        )
        assert resp.status_code == 204
        assert "<tilt>25</tilt>" in cam.calls[-1].body and "<zoom>-100</zoom>" in cam.calls[-1].body
        resp = await client.get(f"/api/cameras/{camera.id}/ptz/presets", headers=headers)
        assert [p["token"] for p in resp.json()] == ["1", "3"]
        assert cam.digest_failures == 0

    async def test_status_endpoint(self, client: AsyncClient, db_session):
        camera = await _camera(db_session, protocol="isapi", port=None)
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get(f"/api/cameras/{camera.id}/ptz", headers=headers)
        assert resp.json() == {"cameraId": str(camera.id), "enabled": True, "protocol": "isapi", "onvifPort": None}


@pytest.mark.usefixtures("seeded")
class TestProbe:
    async def test_probe_saved_camera_even_when_disabled(self, client: AsyncClient, db_session, onvif_cam):
        camera = await _camera(db_session, enabled=False, protocol=None)
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(f"/api/cameras/{camera.id}/ptz/probe", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True and body["protocol"] == "onvif"
        assert body["ptzSupported"] and body["presetsSupported"] and body["presetCount"] == 2
        assert "password" not in resp.text.lower() and "Parol-123" not in resp.text

    async def test_probe_with_form_overrides(self, client: AsyncClient, db_session, onvif_cam):
        camera = await _camera(db_session, enabled=False, protocol=None, port=80, password="eski")
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(f"/api/cameras/{camera.id}/ptz/probe", headers=headers, json={})
        assert resp.json()["success"] is False

        resp = await client.post(
            f"/api/cameras/{camera.id}/ptz/probe",
            headers=headers,
            json={"protocol": "onvif", "onvifPort": 8000, "password": onvif_cam.password},
        )
        assert resp.json()["success"] is True
        assert resp.json()["tried"] == ["onvif"]

    async def test_adhoc_probe(self, client: AsyncClient, onvif_cam):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/cameras/ptz/probe",
            headers=headers,
            json={"ip": CAM_IP, "onvifPort": 8000, "username": "admin", "password": "xato"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is False
        assert "paroli noto'g'ri" in resp.json()["message"]

        resp = await client.post(
            "/api/cameras/ptz/probe", headers=headers, json={"ip": "10.0.0.1/../admin?x=", "onvifPort": 80}
        )
        assert resp.status_code == 422


@pytest.mark.usefixtures("seeded")
class TestCameraPtzConfig:
    BASE = {
        "name": "Yangi PTZ",
        "ip": "10.30.0.99",
        "building": "1-Bino (Asosiy korpus)",
        "zone": "Hovli",
        "resolution": "1080p",
    }

    async def test_create_read_update(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/cameras",
            headers=headers,
            json={**self.BASE, "ptzEnabled": True, "ptzProtocol": "isapi", "onvifPort": 8080},
        )
        assert resp.status_code == 201, resp.text
        created = resp.json()
        assert (created["ptzEnabled"], created["ptzProtocol"], created["onvifPort"]) == (True, "isapi", 8080)

        # PTZ maydonlarini bilmaydigan eski mijoz — sozlama saqlanib qoladi.
        resp = await client.patch(f"/api/cameras/{created['id']}", headers=headers, json={**self.BASE, "zone": "Darvoza"})
        assert resp.status_code == 200
        assert (resp.json()["ptzEnabled"], resp.json()["ptzProtocol"], resp.json()["onvifPort"]) == (True, "isapi", 8080)

        resp = await client.patch(
            f"/api/cameras/{created['id']}",
            headers=headers,
            json={**self.BASE, "ptzEnabled": False, "ptzProtocol": None, "onvifPort": None},
        )
        assert (resp.json()["ptzEnabled"], resp.json()["ptzProtocol"], resp.json()["onvifPort"]) == (False, None, None)

    async def test_enabled_requires_protocol(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post("/api/cameras", headers=headers, json={**self.BASE, "ptzEnabled": True})
        assert resp.status_code == 422

        resp = await client.post("/api/cameras", headers=headers, json=self.BASE)
        assert resp.status_code == 201
        assert resp.json()["ptzEnabled"] is False
        camera_id = resp.json()["id"]
        resp = await client.patch(f"/api/cameras/{camera_id}", headers=headers, json={**self.BASE, "ptzEnabled": True})
        assert resp.status_code == 422
        resp = await client.patch(
            f"/api/cameras/{camera_id}", headers=headers, json={**self.BASE, "ptzEnabled": True, "ptzProtocol": "onvif"}
        )
        assert resp.status_code == 200 and resp.json()["ptzProtocol"] == "onvif"

    async def test_invalid_protocol_and_port(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post("/api/cameras", headers=headers, json={**self.BASE, "ptzProtocol": "pelco"})
        assert resp.status_code == 422
        resp = await client.post("/api/cameras", headers=headers, json={**self.BASE, "onvifPort": 70000})
        assert resp.status_code == 422
