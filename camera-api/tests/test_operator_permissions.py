"""Hodisalar, davomat, tashkiliy tuzilma va dars jadvali huquqlari.

Bu bo'limlar ilgari faqat "tizimga kirgan" bo'lishni talab qilardi —
kamera mas'uli ham hodisalarni o'chira, davomatni tuzata va
fakultetlarni o'chira olardi. Testlar uch tomonni tekshiradi: kamera
mas'uli to'xtatiladi, admin avvalgidek ishlaydi (hodisani o'chirishdan
tashqari), super-admin hammasini qila oladi.
"""

import importlib.util
from datetime import date
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Building, Camera, Faculty, StudentStaff, User
from app.routers.events import WS_CLOSE_FORBIDDEN, WS_CLOSE_UNAUTHORIZED, authorize_events_socket
from app.seed import DEFAULT_PERMISSIONS
from app.security import hash_password
from tests.conftest import TestSessionLocal, auth_headers, login

STEWARD_LOGIN = "kamera2"
STEWARD_PASSWORD = "kamera-parol-456"
NEW_KEYS = ("reviewEvents", "deleteEvents", "manageAttendance", "manageOrgStructure", "manageLessons")


@pytest.fixture
async def steward(db_session, seeded) -> User:
    user = User(
        login=STEWARD_LOGIN,
        password_hash=hash_password(STEWARD_PASSWORD),
        full_name="Kamera Mas'uli Ikkinchi",
        role="kamera-masuli",
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.fixture
async def camera(db_session, seeded) -> Camera:
    building = (await db_session.execute(select(Building))).scalars().first()
    row = Camera(name="Huquq kamerasi", ip="10.0.0.9", building_id=building.id, zone="Z", resolution="1080p")
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest.fixture
async def person(db_session, seeded) -> StudentStaff:
    faculty = (await db_session.execute(select(Faculty))).scalars().first()
    row = StudentStaff(full_name="Huquq Sinovchi", type="xodim", faculty_id=faculty.id, group_or_position="Laborant")
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


async def _create_event(client: AsyncClient, camera: Camera) -> str:
    headers = await auth_headers(client, "admin", "admin123")
    resp = await client.post(
        "/api/events",
        headers=headers,
        json={
            "cameraId": str(camera.id),
            "moduleCode": 17,
            "moduleName": "Tartib-intizom buzilishi",
            "group": "D",
            "confidence": 80,
            "severity": "o'rta",
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.mark.usefixtures("seeded")
class TestStewardIsStopped:
    async def test_events(self, client: AsyncClient, steward, camera):
        event_id = await _create_event(client, camera)
        headers = await auth_headers(client, STEWARD_LOGIN, STEWARD_PASSWORD)

        assert (await client.get("/api/events", headers=headers)).status_code == 403
        assert (await client.get("/api/events/summary", headers=headers)).status_code == 403
        assert (
            await client.patch(f"/api/events/{event_id}/review", headers=headers, json={"status": "rad_etilgan"})
        ).status_code == 403
        assert (
            await client.post(
                "/api/events/review-bulk", headers=headers, json={"ids": [event_id], "status": "rad_etilgan"}
            )
        ).status_code == 403
        assert (await client.delete(f"/api/events/{event_id}", headers=headers)).status_code == 403
        assert (
            await client.post(
                "/api/events",
                headers=headers,
                json={
                    "cameraId": str(camera.id),
                    "moduleCode": 1,
                    "moduleName": "Soxta signal",
                    "group": "A",
                    "confidence": 99,
                    "severity": "yuqori",
                },
            )
        ).status_code == 403

    async def test_attendance_and_presence(self, client: AsyncClient, steward, person):
        headers = await auth_headers(client, STEWARD_LOGIN, STEWARD_PASSWORD)
        pid = str(person.id)

        assert (await client.get(f"/api/attendance/{pid}", headers=headers, params={"month": "2026-09"})).status_code == 403
        assert (await client.get(f"/api/attendance/{pid}/summary", headers=headers)).status_code == 403
        assert (
            await client.post(
                "/api/attendance",
                headers=headers,
                json={"studentStaffId": pid, "date": "2026-09-01", "status": "keldi"},
            )
        ).status_code == 403
        assert (await client.delete(f"/api/attendance/{pid}/2026-09-01", headers=headers)).status_code == 403
        assert (await client.get("/api/presence/teachers", headers=headers)).status_code == 403
        assert (await client.get("/api/presence/cameras", headers=headers)).status_code == 403
        assert (await client.get(f"/api/presence/people/{pid}/day", headers=headers)).status_code == 403

    async def test_org_structure_is_read_only(self, client: AsyncClient, db_session, steward):
        headers = await auth_headers(client, STEWARD_LOGIN, STEWARD_PASSWORD)
        building = (await db_session.execute(select(Building))).scalars().first()
        faculty = (await db_session.execute(select(Faculty))).scalars().first()

        for path in ("/api/buildings", "/api/faculties", "/api/student-groups", "/api/departments"):
            assert (await client.get(path, headers=headers)).status_code == 200, path

        assert (await client.post("/api/buildings", headers=headers, json={"name": "Yangi bino"})).status_code == 403
        assert (
            await client.patch(f"/api/buildings/{building.id}", headers=headers, json={"name": "Boshqa nom"})
        ).status_code == 403
        assert (await client.delete(f"/api/buildings/{building.id}", headers=headers)).status_code == 403
        assert (await client.post("/api/faculties", headers=headers, json={"name": "Yangi fakultet"})).status_code == 403
        assert (await client.delete(f"/api/faculties/{faculty.id}", headers=headers)).status_code == 403
        assert (
            await client.post(
                "/api/student-groups",
                headers=headers,
                json={"name": "G-1", "facultyId": str(faculty.id), "course": 1},
            )
        ).status_code == 403
        assert (await client.post("/api/departments", headers=headers, json={"name": "Kafedra"})).status_code == 403

        # Hech narsa o'chmagan.
        assert await db_session.get(Faculty, faculty.id) is not None
        assert await db_session.get(Building, building.id) is not None

    async def test_lessons_face_system_ai(self, client: AsyncClient, steward):
        headers = await auth_headers(client, STEWARD_LOGIN, STEWARD_PASSWORD)

        assert (await client.get("/api/lesson-sessions", headers=headers)).status_code == 403
        assert (
            await client.post(
                "/api/lesson-sessions",
                headers=headers,
                json={"date": date.today().isoformat(), "group": "G", "faculty": "F", "subject": "S", "teacher": "T"},
            )
        ).status_code == 403
        assert (
            await client.post(
                "/api/face/compare",
                headers=headers,
                files={"image_a": ("a.jpg", b"x", "image/jpeg"), "image_b": ("b.jpg", b"x", "image/jpeg")},
            )
        ).status_code == 403
        for path in (
            "/api/system/resources",
            "/api/system/ai-status",
            "/api/system/stream-status",
            "/api/system/camera-network",
            "/api/ai-modules/suppressions",
            "/api/ai-modules/17/trial-sample",
        ):
            assert (await client.get(path, headers=headers)).status_code == 403, path

    async def test_still_reads_the_permission_matrix(self, client: AsyncClient, steward):
        headers = await auth_headers(client, STEWARD_LOGIN, STEWARD_PASSWORD)
        resp = await client.get("/api/permissions", headers=headers)
        assert resp.status_code == 200


@pytest.mark.usefixtures("seeded")
class TestAdminKeepsItsWork:
    async def test_reviews_events_but_cannot_delete_them(self, client: AsyncClient, camera):
        event_id = await _create_event(client, camera)
        headers = await auth_headers(client, "operator", "operator123")

        assert (await client.get("/api/events", headers=headers)).status_code == 200
        assert (await client.get("/api/events/summary", headers=headers)).status_code == 200
        reviewed = await client.patch(
            f"/api/events/{event_id}/review", headers=headers, json={"status": "tasdiqlangan"}
        )
        assert reviewed.status_code == 200
        assert (await client.get("/api/ai-modules/17/trial-sample", headers=headers)).status_code == 200
        assert (await client.delete(f"/api/events/{event_id}", headers=headers)).status_code == 403

    async def test_super_admin_deletes_events(self, client: AsyncClient, camera):
        event_id = await _create_event(client, camera)
        headers = await auth_headers(client, "admin", "admin123")
        assert (await client.delete(f"/api/events/{event_id}", headers=headers)).status_code == 204

    async def test_attendance_org_lessons_presence_system(self, client: AsyncClient, person):
        headers = await auth_headers(client, "operator", "operator123")
        pid = str(person.id)

        recorded = await client.post(
            "/api/attendance",
            headers=headers,
            json={"studentStaffId": pid, "date": "2026-09-01", "status": "keldi", "checkIn": "08:30"},
        )
        assert recorded.status_code == 201
        assert (await client.get(f"/api/attendance/{pid}", headers=headers, params={"month": "2026-09"})).status_code == 200
        assert (await client.get(f"/api/presence/people/{pid}/day", headers=headers)).status_code == 200
        assert (await client.get("/api/presence/teachers", headers=headers)).status_code == 200
        assert (await client.post("/api/buildings", headers=headers, json={"name": "Operator binosi"})).status_code == 201
        assert (await client.get("/api/lesson-sessions", headers=headers)).status_code == 200
        assert (await client.get("/api/system/camera-network", headers=headers)).status_code == 200

    async def test_revoking_a_permission_takes_effect(self, client: AsyncClient):
        super_headers = await auth_headers(client, "admin", "admin123")
        toggled = await client.patch(
            "/api/permissions/manageOrgStructure", headers=super_headers, json={"role": "admin"}
        )
        assert toggled.status_code == 200 and toggled.json()["admin"] is False

        headers = await auth_headers(client, "operator", "operator123")
        assert (await client.post("/api/buildings", headers=headers, json={"name": "Taqiqlangan"})).status_code == 403
        assert (await client.get("/api/buildings", headers=headers)).status_code == 200


@pytest.mark.usefixtures("seeded")
class TestPermissionMatrix:
    async def test_new_keys_have_the_agreed_defaults(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        matrix = (await client.get("/api/permissions", headers=headers)).json()
        for key in NEW_KEYS:
            assert matrix[key]["superAdmin"] is True, key
            assert matrix[key]["cameraSteward"] is False, key
        assert matrix["deleteEvents"]["admin"] is False
        for key in ("reviewEvents", "manageAttendance", "manageOrgStructure", "manageLessons"):
            assert matrix[key]["admin"] is True, key

    async def test_toggle_response_keeps_the_steward_column(self, client: AsyncClient):
        """Javobda cameraSteward bo'lmasa, frontend uni false deb yozib
        qo'yardi va keyingi bosish bazaga teskari qiymat yuborardi."""
        headers = await auth_headers(client, "admin", "admin123")

        on = await client.patch("/api/permissions/viewReports", headers=headers, json={"role": "cameraSteward"})
        assert on.status_code == 200 and on.json()["cameraSteward"] is True

        # Boshqa ustunni o'zgartirish steward qiymatini "unutmasligi" kerak.
        other = await client.patch("/api/permissions/editCameraLocation", headers=headers, json={"role": "admin"})
        assert other.status_code == 200
        assert other.json()["cameraSteward"] is True
        assert other.json()["admin"] is False

    def test_migration_matches_seed(self):
        path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "n7b8c9d0e1f2_operator_permissions.py"
        spec = importlib.util.spec_from_file_location("operator_permissions_migration", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert set(module.NEW_PERMISSIONS) == set(NEW_KEYS)
        for key, values in module.NEW_PERMISSIONS.items():
            assert DEFAULT_PERMISSIONS[key] == values, key


@pytest.mark.usefixtures("seeded")
class TestEventsSocketAuthorization:
    async def test_missing_or_garbage_token(self):
        assert await authorize_events_socket(None, TestSessionLocal) == WS_CLOSE_UNAUTHORIZED
        assert await authorize_events_socket("not-a-token", TestSessionLocal) == WS_CLOSE_UNAUTHORIZED

    async def test_steward_is_forbidden(self, client: AsyncClient, steward):
        token = await login(client, STEWARD_LOGIN, STEWARD_PASSWORD)
        assert await authorize_events_socket(token, TestSessionLocal) == WS_CLOSE_FORBIDDEN

    async def test_operator_connects(self, client: AsyncClient):
        token = await login(client, "operator", "operator123")
        assert await authorize_events_socket(token, TestSessionLocal) is None

    async def test_logged_out_token_is_rejected(self, client: AsyncClient):
        """Ilgari WebSocket faqat JWT imzosini tekshirardi — chiqib ketgan
        foydalanuvchi signallarni olishda davom etardi."""
        token = await login(client, "operator", "operator123")
        logout = await client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert logout.status_code == 204
        assert await authorize_events_socket(token, TestSessionLocal) == WS_CLOSE_UNAUTHORIZED
