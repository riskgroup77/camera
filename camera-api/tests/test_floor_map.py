"""Xarita (/api/xarita): binolar, qavat ko'rinishi, rasm yuklash va
kamerani joylash. Ombor (MinIO) monkeypatch bilan lug'atga almashtiriladi."""

from datetime import datetime, timedelta, timezone

import cv2
import numpy as np
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import AIModuleConfig, AuditLog, Building, Camera, Event, User
from app.models.platform import FloorPlan
from app.routers import xarita as xarita_router
from app.security import hash_password
from tests.conftest import auth_headers


def _png(width: int = 64, height: int = 48) -> bytes:
    ok, buf = cv2.imencode(".png", np.zeros((height, width, 3), dtype=np.uint8))
    assert ok
    return buf.tobytes()


def _webp() -> bytes:
    ok, buf = cv2.imencode(".webp", np.zeros((32, 32, 3), dtype=np.uint8))
    assert ok
    return buf.tobytes()


@pytest.fixture
def storage(monkeypatch):
    objects: dict[str, bytes] = {}
    counter = {"n": 0}

    def fake_upload(data, filename, content_type, prefix):
        counter["n"] += 1
        key = f"{prefix}/{counter['n']}-{filename}"
        objects[key] = data
        return str(counter["n"]), key

    async def fake_delete(keys):
        return sum(1 for key in keys if key and objects.pop(key, None) is not None)

    monkeypatch.setattr(xarita_router, "upload_file", fake_upload)
    monkeypatch.setattr(xarita_router, "delete_files_quietly", fake_delete)
    monkeypatch.setattr(xarita_router, "presigned_url", lambda key: f"https://s3.test/{key}?sig=1")
    return objects


@pytest.fixture
async def building(db_session, seeded) -> Building:
    row = (await db_session.execute(select(Building).order_by(Building.name))).scalars().first()
    row.floors = 3
    await db_session.commit()
    return row


@pytest.fixture
async def other_building(db_session, building) -> Building:
    rows = (await db_session.execute(select(Building).order_by(Building.name))).scalars().all()
    return next(b for b in rows if b.id != building.id)


async def _camera(db_session, name, building, floor, *, live=True, video=True, **extra) -> Camera:
    now = datetime.now(timezone.utc)
    row = Camera(
        name=name,
        ip=f"10.30.0.{abs(hash(name)) % 240 + 1}",
        building_id=building.id if building else None,
        zone="Koridor",
        floor=floor,
        resolution="1080p",
        status="faol" if live else "nofaol",
        last_seen_at=now if live else None,
        last_frame_at=now if (live and video) else None,
        stream_url=f"/s0/cam-{abs(hash(name)):08x}/index.m3u8",
        **extra,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest.fixture
async def admin(client: AsyncClient, seeded):
    return await auth_headers(client, "admin", "admin123")


@pytest.fixture
async def steward(client: AsyncClient, db_session, seeded):
    """Kamera mas'uli: editCameraLocation bor, viewLive yo'q."""
    db_session.add(
        User(login="xarita-masul", password_hash=hash_password("xarita-parol-1"), full_name="Xarita", role="kamera-masuli")
    )
    await db_session.commit()
    return await auth_headers(client, "xarita-masul", "xarita-parol-1")


async def _upload(client, headers, building_id, floor, data, filename="plan.png"):
    return await client.put(
        f"/api/xarita/{building_id}/{floor}/rasm",
        files={"file": (filename, data, "application/octet-stream")},
        headers=headers,
    )


class TestUpload:
    async def test_creates_then_replaces_and_audits(self, client, db_session, admin, building, storage):
        resp = await _upload(client, admin, building.id, 2, _png(64, 48))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body["width"], body["height"]) == (64, 48)
        assert body["imageUrl"].startswith("https://s3.test/floor-plans/")
        assert body["updatedAt"]
        first_key = next(iter(storage))

        resp = await _upload(client, admin, building.id, 2, _png(100, 50))
        assert resp.status_code == 200, resp.text
        assert resp.json()["width"] == 100
        # Eski rasm ombordan o'chiriladi, reja bitta qoladi.
        assert first_key not in storage and len(storage) == 1
        plans = (await db_session.execute(select(FloorPlan).where(FloorPlan.building_id == building.id))).scalars().all()
        assert len(plans) == 1 and plans[0].width == 100

        actions = (await db_session.execute(select(AuditLog.action).where(AuditLog.module == "Xarita"))).scalars().all()
        assert any("yukladi" in a for a in actions) and any("almashtirdi" in a for a in actions)

    async def test_rejects_webp_garbage_and_too_big(self, client, admin, building, storage, monkeypatch):
        assert (await _upload(client, admin, building.id, 1, _webp())).status_code == 400
        assert (await _upload(client, admin, building.id, 1, b"not an image")).status_code == 400
        monkeypatch.setattr(xarita_router, "MAX_MAP_BYTES", 100)
        resp = await _upload(client, admin, building.id, 1, _png())
        assert resp.status_code == 400 and "10 MB" in resp.json()["detail"]
        assert storage == {}

    async def test_floor_beyond_building(self, client, admin, building, storage):
        assert (await _upload(client, admin, building.id, 9, _png())).status_code == 400

    async def test_steward_can_upload(self, client, steward, building, storage):
        assert (await _upload(client, steward, building.id, 1, _png())).status_code == 200


class TestRead:
    async def test_buildings_list_floors(self, client, admin, building, other_building, db_session, storage):
        await _camera(db_session, "B2 kamera", other_building, 5)
        await _upload(client, admin, building.id, 2, _png())
        resp = await client.get("/api/xarita/binolar", headers=admin)
        assert resp.status_code == 200, resp.text
        by_id = {b["id"]: b for b in resp.json()}
        # Admin tahrir qila oladi — binoning e'lon qilingan qavatlari ham chiqadi.
        floors = {f["floor"]: f for f in by_id[str(building.id)]["floors"]}
        assert set(floors) == {1, 2, 3}
        assert floors[2]["hasPlan"] and not floors[1]["hasPlan"]
        other = by_id[str(other_building.id)]["floors"]
        assert [f["floor"] for f in other if f["cameraCount"]] == [5]

    async def test_floor_view_status_events_and_placement(self, client, db_session, admin, building, storage):
        await _upload(client, admin, building.id, 1, _png())
        green = await _camera(db_session, "Yashil", building, 1, plan_x=0.2, plan_y=0.3, plan_rotation=90, plan_fov=60)
        await _camera(db_session, "Sariq", building, 1, video=False)
        await _camera(db_session, "Qizil", building, 1, live=False)
        await _camera(db_session, "Boshqa qavat", building, 2)
        await _camera(db_session, "Yetim", None, None)

        module_code = (await db_session.execute(select(AIModuleConfig.code))).scalars().first()
        now = datetime.now(timezone.utc)

        def event(status, *, is_trial=False, age=timedelta(minutes=5)):
            return Event(
                camera_id=green.id,
                camera_name=green.name,
                building=building.name,
                module_code=module_code,
                module_name="Test",
                group="xavfsizlik",
                confidence=90,
                severity="yuqori",
                status=status,
                is_trial=is_trial,
                occurred_at=now - age,
            )

        db_session.add_all(
            [
                event("yangi"),
                event("jarayonda"),
                event("tasdiqlangan"),
                event("yangi", is_trial=True),
                event("yangi", age=timedelta(hours=30)),
            ]
        )
        await db_session.commit()

        resp = await client.get(f"/api/xarita/{building.id}/1", headers=admin)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["plan"]["width"] == 64
        by_name = {c["name"]: c for c in body["cameras"]}
        assert set(by_name) == {"Yashil", "Sariq", "Qizil"}
        g = by_name["Yashil"]
        assert (g["x"], g["y"], g["angle"], g["fov"]) == (0.2, 0.3, 90, 60)
        assert g["openEvents"] == 2
        assert g["status"] == "online"
        assert by_name["Sariq"]["status"] == "novideo"
        assert by_name["Qizil"]["status"] == "offline"
        assert by_name["Sariq"]["x"] is None and by_name["Sariq"]["fov"] == 70
        assert [c["name"] for c in body["candidates"]] == ["Yetim"]

    async def test_floor_without_plan(self, client, admin, building):
        resp = await client.get(f"/api/xarita/{building.id}/3", headers=admin)
        assert resp.status_code == 200
        assert resp.json()["plan"] is None

    async def test_unknown_building(self, client, admin, seeded):
        resp = await client.get("/api/xarita/00000000-0000-0000-0000-000000000000/1", headers=admin)
        assert resp.status_code == 404

    async def test_view_requires_view_live(self, client, steward, building):
        assert (await client.get("/api/xarita/binolar", headers=steward)).status_code == 403


class TestPlace:
    async def test_move_rotate_and_unplace(self, client, db_session, admin, building):
        cam = await _camera(db_session, "Joy", building, 1)
        resp = await client.put(f"/api/xarita/kamera/{cam.id}/joy", json={"x": 0.5, "y": 0.25, "angle": 180, "fov": 90}, headers=admin)
        assert resp.status_code == 200, resp.text
        assert (resp.json()["x"], resp.json()["angle"], resp.json()["fov"]) == (0.5, 180, 90)
        await db_session.refresh(cam)
        assert (cam.plan_x, cam.plan_y, cam.plan_rotation, cam.plan_fov) == (0.5, 0.25, 180, 90)

        resp = await client.put(f"/api/xarita/kamera/{cam.id}/joy", json={"x": None, "y": None}, headers=admin)
        assert resp.status_code == 200
        await db_session.refresh(cam)
        assert (cam.plan_x, cam.plan_rotation, cam.plan_fov) == (None, None, 90)

        actions = (await db_session.execute(select(AuditLog.action).where(AuditLog.module == "Xarita"))).scalars().all()
        assert len(actions) == 2

    async def test_assigns_unassigned_camera(self, client, db_session, admin, building):
        cam = await _camera(db_session, "Yangi", None, None)
        resp = await client.put(
            f"/api/xarita/kamera/{cam.id}/joy",
            json={"x": 0.1, "y": 0.9, "angle": 45, "buildingId": str(building.id), "floor": 2},
            headers=admin,
        )
        assert resp.status_code == 200, resp.text
        await db_session.refresh(cam)
        assert (cam.building_id, cam.floor, cam.plan_x, cam.plan_rotation) == (building.id, 2, 0.1, 45)

    async def test_refuses_camera_of_other_floor(self, client, db_session, admin, building):
        cam = await _camera(db_session, "Uzoq", building, 3)
        resp = await client.put(
            f"/api/xarita/kamera/{cam.id}/joy",
            json={"x": 0.1, "y": 0.1, "buildingId": str(building.id), "floor": 1},
            headers=admin,
        )
        assert resp.status_code == 409
        await db_session.refresh(cam)
        assert cam.floor == 3 and cam.plan_x is None

    async def test_validation(self, client, db_session, admin, building):
        cam = await _camera(db_session, "Tekshir", building, 1)
        url = f"/api/xarita/kamera/{cam.id}/joy"
        assert (await client.put(url, json={"x": 0.5}, headers=admin)).status_code == 422
        assert (await client.put(url, json={"x": 1.5, "y": 0.5}, headers=admin)).status_code == 422
        assert (await client.put(url, json={"x": 0.5, "y": 0.5, "angle": 400}, headers=admin)).status_code == 422

    async def test_requires_edit_permission(self, client, db_session, building, seeded):
        cam = await _camera(db_session, "Huquq", building, 1)
        db_session.add(User(login="oddiy-op", password_hash=hash_password("oddiy-parol-1"), full_name="Op", role="admin"))
        await db_session.commit()
        # Admin rolining matritsadagi huquqi o'chirilsa — 403.
        from app.models import Permission

        perm = (await db_session.execute(select(Permission).where(Permission.key == "editCameraLocation"))).scalar_one()
        perm.admin = False
        await db_session.commit()
        headers = await auth_headers(client, "oddiy-op", "oddiy-parol-1")
        resp = await client.put(f"/api/xarita/kamera/{cam.id}/joy", json={"x": 0.5, "y": 0.5}, headers=headers)
        assert resp.status_code == 403


async def test_floor_view_counts_people_seen_in_last_ten_minutes(client, db_session, admin, building):
    """Xarita: kamera oldida so'nggi 10 daqiqada tanilgan turli odamlar soni."""
    from app.models import PresenceVisit, StudentStaff

    cam = await _camera(db_session, "Zal", building, 1)
    quiet = await _camera(db_session, "Bo'sh", building, 1)
    people = [StudentStaff(full_name=f"Soxta {i}", type="xodim", group_or_position="X") for i in range(3)]
    db_session.add_all(people)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    db_session.add_all([
        PresenceVisit(student_staff_id=people[0].id, camera_id=cam.id, first_seen_at=now - timedelta(minutes=3),
                      last_seen_at=now - timedelta(minutes=1), sightings=4),
        PresenceVisit(student_staff_id=people[1].id, camera_id=cam.id, first_seen_at=now - timedelta(minutes=8),
                      last_seen_at=now - timedelta(minutes=5), sightings=2),
        # Eski tashrif (1 soat oldin) — "hozir" hisobiga kirmaydi.
        PresenceVisit(student_staff_id=people[2].id, camera_id=cam.id, first_seen_at=now - timedelta(hours=1),
                      last_seen_at=now - timedelta(minutes=50), sightings=2),
    ])
    await db_session.commit()

    body = (await client.get(f"/api/xarita/{building.id}/1", headers=admin)).json()
    by_name = {c["name"]: c for c in body["cameras"]}
    assert by_name["Zal"]["peopleNow"] == 2
    assert by_name["Bo'sh"]["peopleNow"] == 0


async def test_building_scoped_user_cannot_open_other_buildings(client, db_session, building, other_building):
    """Bitta binoga cheklangan foydalanuvchi boshqa binoning xaritasini (va
    kameralarining jonli oqim havolalarini) ololmaydi."""
    await _camera(db_session, "Begona bino kamerasi", other_building, 1)
    user = User(login="scoped_map", password_hash=hash_password("scoped-pass-123"), full_name="Doirali",
                role="admin", allowed_building_ids=[str(building.id)])
    db_session.add(user)
    await db_session.commit()
    headers = await auth_headers(client, "scoped_map", "scoped-pass-123")

    assert (await client.get(f"/api/xarita/{other_building.id}/1", headers=headers)).status_code == 404
    listed = (await client.get("/api/xarita/binolar", headers=headers)).json()
    assert all(b["id"] != str(other_building.id) for b in listed)
