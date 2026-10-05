"""Bino doirasi (User.allowed_building_ids): kamera bilan bog'liq har bir
o'qish endpointi faqat ruxsat etilgan binolarni ko'rsatadi, doiradan
tashqaridagi kamera/hodisa — 404. Super Admin doim cheklovsiz."""

import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.models import AIModuleConfig, Building, Camera, Event, Permission, User
from app.routers.public import reset_campus_cache_for_tests
from app.security import hash_password
from app.services import access_scope
from app.timezone import local_now
from tests.conftest import auth_headers

pytestmark = pytest.mark.anyio

SCOPED_LOGIN = "bino-a-admin"
SCOPED_PASSWORD = "bino-a-parol-123"


@pytest.fixture
async def world(db_session, seeded):
    reset_campus_cache_for_tests()
    a = Building(name="Doira A binosi")
    b = Building(name="Doira B binosi")
    db_session.add_all([a, b])
    await db_session.flush()
    cam_a = Camera(name="A kamera", ip="10.1.0.1", zone="A zona", resolution="1080p", status="faol", building_id=a.id)
    cam_b = Camera(name="B kamera", ip="10.1.0.2", zone="B zona", resolution="1080p", status="faol", building_id=b.id)
    cam_none = Camera(name="Binosiz kamera", ip="10.1.0.3", zone="N zona", resolution="1080p", status="faol")
    db_session.add_all([cam_a, cam_b, cam_none])
    await db_session.flush()

    module = (await db_session.execute(select(AIModuleConfig).order_by(AIModuleConfig.code))).scalars().first()
    now = local_now()

    def event(cam: Camera, building: str) -> Event:
        return Event(
            camera_id=cam.id, camera_name=cam.name, building=building, module_code=module.code,
            module_name=module.name, group="A", confidence=90, severity="yuqori",
            occurred_at=now - timedelta(minutes=5),
        )

    ev_a, ev_b = event(cam_a, a.name), event(cam_b, b.name)
    db_session.add_all([ev_a, ev_b])

    scoped = User(
        login=SCOPED_LOGIN,
        password_hash=hash_password(SCOPED_PASSWORD),
        full_name="Bino A Administratori",
        role="admin",
        allowed_building_ids=[str(a.id)],
    )
    db_session.add(scoped)
    await db_session.commit()
    return {"a": a, "b": b, "cam_a": cam_a, "cam_b": cam_b, "cam_none": cam_none, "ev_a": ev_a, "ev_b": ev_b,
            "scoped": scoped}


async def _scoped(client: AsyncClient) -> dict[str, str]:
    return await auth_headers(client, SCOPED_LOGIN, SCOPED_PASSWORD)


class TestHelper:
    def test_super_admin_and_empty_scope_are_unrestricted(self):
        class U:
            def __init__(self, role, ids):
                self.role, self.allowed_building_ids = role, ids

        some = str(uuid.uuid4())
        assert access_scope.allowed_buildings(None) is None
        assert access_scope.allowed_buildings(U("super-admin", [some])) is None
        assert access_scope.allowed_buildings(U("admin", None)) is None
        assert access_scope.allowed_buildings(U("admin", [])) is None
        assert access_scope.allowed_buildings(U("admin", [some])) == {uuid.UUID(some)}
        # Buzilgan qiymat "hammasi" emas, "hech narsa".
        assert access_scope.allowed_buildings(U("admin", ["buzuq"])) == set()


class TestPublicWall:
    async def test_camera_list_is_scoped(self, client: AsyncClient, world):
        names = {c["name"] for c in (await client.get("/api/public/cameras", headers=await _scoped(client))).json()["items"]}
        assert names == {"A kamera"}
        admin = await auth_headers(client, "admin", "admin123")
        names = {c["name"] for c in (await client.get("/api/public/cameras", headers=admin)).json()["items"]}
        assert {"A kamera", "B kamera", "Binosiz kamera"} <= names

    async def test_out_of_scope_camera_is_404(self, client: AsyncClient, world):
        headers = await _scoped(client)
        cam_b, cam_none, cam_a = world["cam_b"].id, world["cam_none"].id, world["cam_a"].id
        for cam in (cam_b, cam_none):
            for suffix in ("live-detection", "analysis-status", "thumbnail"):
                resp = await client.get(f"/api/public/cameras/{cam}/{suffix}", headers=headers)
                assert resp.status_code == 404, (suffix, resp.text)
                assert resp.json()["detail"] == "Kamera topilmadi"
        assert (await client.get(f"/api/public/cameras/{cam_a}/analysis-status", headers=headers)).status_code == 200

    async def test_campus_is_scoped_and_not_cached_across_users(self, client: AsyncClient, world):
        admin = await auth_headers(client, "admin", "admin123")
        full = (await client.get("/api/public/campus", headers=admin)).json()
        assert {"Doira A binosi", "Doira B binosi"} <= {b["name"] for b in full["buildings"]}

        scoped = (await client.get("/api/public/campus", headers=await _scoped(client))).json()
        assert [b["name"] for b in scoped["buildings"]] == ["Doira A binosi"]
        assert scoped["cameras"] == 1

        # Cheklangan javob umumiy keshga tushmagan.
        again = (await client.get("/api/public/campus", headers=admin)).json()
        assert again["cameras"] == full["cameras"]

    async def test_anonymous_wall_mode(self, client: AsyncClient, world, monkeypatch):
        """Himoya ataylab o'chirilgan devor: anonim — hammasi, token bilan — o'z doirasi."""
        monkeypatch.setattr(settings, "public_monitoring_requires_auth", False)
        anon = {c["name"] for c in (await client.get("/api/public/cameras")).json()["items"]}
        assert {"A kamera", "B kamera"} <= anon
        scoped = {c["name"] for c in (await client.get("/api/public/cameras", headers=await _scoped(client))).json()["items"]}
        assert scoped == {"A kamera"}
        bad = {c["name"] for c in (await client.get("/api/public/cameras", headers={"Authorization": "Bearer x"})).json()["items"]}
        assert {"A kamera", "B kamera"} <= bad  # anonim kabi — 401 emas


class TestEvents:
    async def test_list_detail_and_summary(self, client: AsyncClient, world):
        headers = await _scoped(client)
        items = (await client.get("/api/events", headers=headers)).json()["items"]
        assert [e["cameraName"] for e in items] == ["A kamera"]

        assert (await client.get(f"/api/events/{world['ev_a'].id}", headers=headers)).status_code == 200
        for path in ("", "/comments", "/timeline"):
            resp = await client.get(f"/api/events/{world['ev_b'].id}{path}", headers=headers)
            assert resp.status_code == 404, path
        resp = await client.patch(f"/api/events/{world['ev_b'].id}/review", json={"status": "tasdiqlangan"}, headers=headers)
        assert resp.status_code == 404

        summary = (await client.get("/api/events/summary", headers=headers)).json()
        assert summary["total"] == 1
        assert [f["value"] for f in summary["buildings"]] == ["Doira A binosi"]

        admin = await auth_headers(client, "admin", "admin123")
        assert (await client.get("/api/events/summary", headers=admin)).json()["total"] == 2

    async def test_bulk_review_skips_out_of_scope(self, client: AsyncClient, db_session, world):
        headers = await _scoped(client)
        resp = await client.post(
            "/api/events/review-bulk",
            json={"ids": [str(world["ev_a"].id), str(world["ev_b"].id)], "status": "tasdiqlangan"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["updated"] == 1
        await db_session.refresh(world["ev_b"])
        assert world["ev_b"].status == "yangi"


class TestEventsSocket:
    async def test_socket_scope_and_fanout_filter(self, client: AsyncClient, world):
        from app.routers.events import socket_camera_scope
        from app.ws import ConnectionManager
        from tests.conftest import TestSessionLocal, login

        scoped_token = await login(client, SCOPED_LOGIN, SCOPED_PASSWORD)
        admin_token = await login(client, "admin", "admin123")
        scope = await socket_camera_scope(scoped_token, TestSessionLocal)
        assert scope == frozenset({str(world["cam_a"].id)})
        assert await socket_camera_scope(admin_token, TestSessionLocal) is None

        class FakeWs:
            def __init__(self):
                self.sent: list[dict] = []

            async def accept(self):
                pass

            async def send_json(self, message):
                self.sent.append(message)

        mgr = ConnectionManager()
        restricted, full = FakeWs(), FakeWs()
        await mgr.connect(restricted, scope)
        await mgr.connect(full, None)
        await mgr._send_local({"cameraId": str(world["cam_a"].id), "moduleName": "A"})
        await mgr._send_local({"cameraId": str(world["cam_b"].id), "moduleName": "B"})
        await mgr._send_local({"cameraId": "", "moduleName": "Kamerasiz"})
        await mgr._send_local({"kind": "attendance_recorded", "personId": "p"})
        assert [m.get("moduleName", m.get("kind")) for m in restricted.sent] == ["A", "attendance_recorded"]
        assert len(full.sent) == 4


class TestPtz:
    async def test_ptz_status(self, client: AsyncClient, world):
        headers = await _scoped(client)
        assert (await client.get(f"/api/cameras/{world['cam_a'].id}/ptz", headers=headers)).status_code == 200
        assert (await client.get(f"/api/cameras/{world['cam_b'].id}/ptz", headers=headers)).status_code == 404
        resp = await client.post(
            f"/api/cameras/{world['cam_b'].id}/ptz/move", json={"pan": 0.5, "tilt": 0, "zoom": 0}, headers=headers
        )
        assert resp.status_code == 404


class TestCameraAdmin:
    async def test_list_summary_zones_and_edit(self, client: AsyncClient, world):
        headers = await _scoped(client)
        names = {c["name"] for c in (await client.get("/api/cameras", headers=headers)).json()["items"]}
        assert names == {"A kamera"}
        assert (await client.get("/api/cameras/summary", headers=headers)).json()["total"] == 1
        zones = {z["zone"] for z in (await client.get("/api/cameras/zones", headers=headers)).json()}
        assert zones == {"A zona"}
        resp = await client.patch(f"/api/cameras/{world['cam_b'].id}/location", json={"zone": "X"}, headers=headers)
        assert resp.status_code == 404

    async def test_scope_change_applies_to_existing_session(self, client: AsyncClient, db_session, world):
        headers = await _scoped(client)
        user = world["scoped"]
        user.allowed_building_ids = [str(world["b"].id)]
        await db_session.commit()
        names = {c["name"] for c in (await client.get("/api/cameras", headers=headers)).json()["items"]}
        assert names == {"B kamera"}


class TestScopeManagement:
    async def test_super_admin_sets_and_clears_scope(self, client: AsyncClient, db_session, world):
        admin = await auth_headers(client, "admin", "admin123")
        operator = (await db_session.execute(select(User).where(User.login == "operator"))).scalar_one()
        a, b = str(world["a"].id), str(world["b"].id)

        resp = await client.put(f"/api/users/{operator.id}/binolar", json={"buildingIds": [a, b, a]}, headers=admin)
        assert resp.status_code == 200, resp.text
        assert sorted(resp.json()["allowedBuildingIds"]) == sorted([a, b])

        resp = await client.put(f"/api/users/{operator.id}/binolar", json={"buildingIds": []}, headers=admin)
        assert resp.json()["allowedBuildingIds"] == []
        await db_session.refresh(operator)
        assert operator.allowed_building_ids is None

    async def test_validation(self, client: AsyncClient, db_session, world):
        admin = await auth_headers(client, "admin", "admin123")
        operator = (await db_session.execute(select(User).where(User.login == "operator"))).scalar_one()
        me = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
        url = f"/api/users/{operator.id}/binolar"
        assert (await client.put(url, json={"buildingIds": ["buzuq"]}, headers=admin)).status_code == 422
        assert (await client.put(url, json={"buildingIds": [str(uuid.uuid4())]}, headers=admin)).status_code == 422
        resp = await client.put(f"/api/users/{me.id}/binolar", json={"buildingIds": [str(world["a"].id)]}, headers=admin)
        assert resp.status_code == 400

    async def test_scoped_manager_cannot_escape_scope(self, client: AsyncClient, db_session, world):
        perm = (await db_session.execute(select(Permission).where(Permission.key == "manageRoles"))).scalar_one()
        perm.admin = True
        await db_session.commit()
        headers = await _scoped(client)
        scoped = world["scoped"]
        operator = (await db_session.execute(select(User).where(User.login == "operator"))).scalar_one()

        # O'z doirasini kengaytira olmaydi.
        resp = await client.put(f"/api/users/{scoped.id}/binolar", json={"buildingIds": []}, headers=headers)
        assert resp.status_code == 403
        # Cheklanmagan hamkasbning parolini tiklab, uning nomidan kira olmaydi.
        resp = await client.post(
            f"/api/users/{operator.id}/reset-password", json={"newPassword": "yangi-parol-123"}, headers=headers
        )
        assert resp.status_code == 403
        # Yaratgan yangi hisobi uning doirasini meros oladi.
        resp = await client.post(
            "/api/users",
            json={"name": "Yangi Xodim Ismi", "login": "yangi-xodim", "password": "yangi-parol-123", "role": "Admin"},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["allowedBuildingIds"] == [str(world["a"].id)]
        # O'z doirasidagi hisobni esa boshqara oladi.
        new_id = resp.json()["id"]
        resp = await client.post(
            f"/api/users/{new_id}/reset-password", json={"newPassword": "boshqa-parol-123"}, headers=headers
        )
        assert resp.status_code == 204
