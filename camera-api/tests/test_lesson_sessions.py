import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Building, Camera, StudentStaff
from tests.conftest import auth_headers


@pytest.mark.usefixtures("seeded")
class TestLessonSessionScheduling:
    async def _teacher_and_camera(self, db_session) -> tuple[str, str]:
        building = (await db_session.execute(select(Building))).scalars().first()
        teacher = StudentStaff(
            full_name="Aziza Karimova", type="xodim", group_or_position="Dotsent", biometrics_status="yoq"
        )
        camera = Camera(
            name="Sinf xona kamerasi", ip="10.0.5.5", building_id=building.id,
            zone="201-xona", resolution="1080p", status="faol",
        )
        db_session.add_all([teacher, camera])
        await db_session.commit()
        return str(teacher.id), str(camera.id)

    async def test_create_with_teacher_id_fills_in_display_name(self, client: AsyncClient, db_session):
        headers = await auth_headers(client, "admin", "admin123")
        teacher_id, camera_id = await self._teacher_and_camera(db_session)

        resp = await client.post(
            "/api/lesson-sessions",
            headers=headers,
            json={
                "date": "2026-08-13",
                "group": "IT-21",
                "faculty": "Kompyuter injiniringi",
                "subject": "Ma'lumotlar bazasi",
                "teacherId": teacher_id,
                "cameraId": camera_id,
                "scheduledStartTime": "2026-08-13T09:00:00",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["teacher"] == "Aziza Karimova"
        assert body["teacherId"] == teacher_id
        assert body["cameraId"] == camera_id
        assert body["scheduledStartTime"] is not None

    async def test_create_without_teacher_or_teacher_id_is_rejected(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/lesson-sessions",
            headers=headers,
            json={"date": "2026-08-13", "group": "IT-21", "faculty": "Kompyuter injiniringi", "subject": "Fizika"},
        )
        assert resp.status_code == 422

    async def test_create_with_unknown_teacher_id_is_404(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/lesson-sessions",
            headers=headers,
            json={
                "date": "2026-08-13",
                "group": "IT-21",
                "faculty": "Kompyuter injiniringi",
                "subject": "Fizika",
                "teacherId": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert resp.status_code == 404

    async def test_schedule_endpoint_attaches_teacher_and_camera_to_existing_session(
        self, client: AsyncClient, db_session
    ):
        headers = await auth_headers(client, "admin", "admin123")
        teacher_id, camera_id = await self._teacher_and_camera(db_session)

        created = (
            await client.post(
                "/api/lesson-sessions",
                headers=headers,
                json={
                    "date": "2026-08-13",
                    "group": "IT-22",
                    "faculty": "Kompyuter injiniringi",
                    "subject": "Tarmoqlar",
                    "teacher": "Vaqtinchalik o'qituvchi",
                },
            )
        ).json()
        assert created["teacherId"] is None

        resp = await client.patch(
            f"/api/lesson-sessions/{created['id']}/schedule",
            headers=headers,
            json={"teacherId": teacher_id, "cameraId": camera_id, "scheduledStartTime": "2026-08-13T10:30:00"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["teacherId"] == teacher_id
        assert body["teacher"] == "Aziza Karimova"
        assert body["cameraId"] == camera_id
        assert body["scheduledStartTime"] is not None

    async def test_schedule_unknown_session_is_404(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.patch(
            "/api/lesson-sessions/00000000-0000-0000-0000-000000000000/schedule",
            headers=headers,
            json={},
        )
        assert resp.status_code == 404


@pytest.mark.usefixtures("seeded")
class TestLessonSessionImport:
    async def test_csv_import_creates_rows(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        csv_body = (
            "date,group,faculty,subject\n"
            "2026-09-01,101-guruh,Davolash ishi,Anatomiya\n"
            "2026-09-02,102-guruh,Davolash ishi,Fiziologiya\n"
        ).encode("utf-8")
        resp = await client.post(
            "/api/lesson-sessions/import",
            headers=headers,
            files={"file": ("lessons.csv", csv_body, "text/csv")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["imported"] == 2
        assert body["skipped"] == 0

    async def test_csv_import_skips_duplicate(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        csv_body = (
            "date,group,faculty,subject\n"
            "2026-09-03,103-guruh,Davolash ishi,Bioximiya\n"
        ).encode("utf-8")
        await client.post(
            "/api/lesson-sessions/import",
            headers=headers,
            files={"file": ("lessons.csv", csv_body, "text/csv")},
        )
        resp = await client.post(
            "/api/lesson-sessions/import",
            headers=headers,
            files={"file": ("lessons.csv", csv_body, "text/csv")},
        )
        assert resp.status_code == 200
        assert resp.json()["imported"] == 0
        assert resp.json()["skipped"] == 1
