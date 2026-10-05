"""Kamera joylashuvi: jurnalga faqat haqiqiy o'zgarish yoziladi, kafedra
biriktiriladi va to'liq tahrirlash uni jimgina o'chirmaydi."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import AuditLog, Building, Camera, Department
from tests.conftest import auth_headers


@pytest.fixture
async def place(db_session, seeded):
    building = (await db_session.execute(select(Building).order_by(Building.name))).scalars().first()
    department = Department(name="Biofizika kafedrasi", building_id=building.id)
    db_session.add(department)
    camera = Camera(name="Koridor kamerasi", ip="10.20.0.5", building_id=building.id, zone="Koridor",
                    floor=None, resolution="1080p", status="nofaol")
    db_session.add(camera)
    await db_session.commit()
    return building, department, camera


async def _camera_log(db_session) -> list[str]:
    rows = await db_session.execute(select(AuditLog.action).where(AuditLog.module == "Kameralar"))
    return list(rows.scalars())


class TestOnlyRealChangesAreLogged:
    async def test_clearing_an_empty_floor_writes_nothing(self, client: AsyncClient, db_session, place):
        _building, _department, camera = place
        headers = await auth_headers(client, "admin", "admin123")

        resp = await client.patch(f"/api/cameras/{camera.id}/location", headers=headers, json={"clearFloor": True})
        assert resp.status_code == 200, resp.text
        resp = await client.post(
            "/api/cameras/bulk-location", headers=headers, json={"cameraIds": [str(camera.id)], "clearFloor": True}
        )
        assert resp.status_code == 200, resp.text

        assert await _camera_log(db_session) == []

    async def test_the_same_floor_again_writes_nothing(self, client: AsyncClient, db_session, place):
        _building, _department, camera = place
        headers = await auth_headers(client, "admin", "admin123")

        await client.patch(f"/api/cameras/{camera.id}/location", headers=headers, json={"floor": 2})
        await client.patch(f"/api/cameras/{camera.id}/location", headers=headers, json={"floor": 2})

        log = await _camera_log(db_session)
        assert len(log) == 1 and "qavat: 2" in log[0]

    async def test_bulk_counts_only_the_cameras_that_changed(self, client: AsyncClient, db_session, place):
        building, _department, camera = place
        other = Camera(name="Zina kamerasi", ip="10.20.0.6", building_id=building.id, zone="Zina", floor=3,
                       resolution="1080p", status="nofaol")
        db_session.add(other)
        await db_session.commit()
        headers = await auth_headers(client, "admin", "admin123")

        resp = await client.post(
            "/api/cameras/bulk-location",
            headers=headers,
            json={"cameraIds": [str(camera.id), str(other.id)], "floor": 3},
        )

        assert resp.json()["updated"] == 2
        assert await _camera_log(db_session) == ["1 ta kameraning joylashuvini o'zgartirdi (qavat: 3)"]


class TestDepartment:
    async def test_the_location_window_assigns_and_removes_it(self, client: AsyncClient, db_session, place):
        _building, department, camera = place
        headers = await auth_headers(client, "admin", "admin123")

        resp = await client.patch(
            f"/api/cameras/{camera.id}/location", headers=headers, json={"department": department.name}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["department"] == department.name

        resp = await client.patch(f"/api/cameras/{camera.id}/location", headers=headers, json={"clearDepartment": True})
        assert resp.json()["department"] == ""
        log = await _camera_log(db_session)
        assert any("kafedra: Biofizika kafedrasi" in line for line in log)
        assert any("kafedra: olib tashlandi" in line for line in log)

    async def test_an_unknown_department_is_refused(self, client: AsyncClient, place):
        _building, _department, camera = place
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.patch(
            f"/api/cameras/{camera.id}/location", headers=headers, json={"department": "Yo'q kafedra"}
        )
        assert resp.status_code == 404

    async def test_create_with_a_department_and_a_full_edit_keeps_it(self, client: AsyncClient, place):
        building, department, _camera = place
        headers = await auth_headers(client, "admin", "admin123")
        payload = {
            "name": "Laboratoriya", "ip": "10.20.0.9", "building": building.name, "zone": "Lab",
            "resolution": "1080p", "status": "nofaol",
        }

        created = await client.post("/api/cameras", headers=headers, json={**payload, "department": department.name})
        assert created.status_code == 201, created.text
        assert created.json()["department"] == department.name

        # Tahrirlash formasi kafedrani yubormaydi — u o'chib ketmasligi kerak.
        edited = await client.patch(
            f"/api/cameras/{created.json()['id']}", headers=headers, json={**payload, "zone": "Lab 2"}
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["department"] == department.name
        assert edited.json()["zone"] == "Lab 2"
