from datetime import date

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers


@pytest.fixture
async def a_student(client: AsyncClient, db_session, seeded):
    headers = await auth_headers(client, "admin", "admin123")
    resp = await client.post(
        "/api/students-staff",
        headers=headers,
        json={"fullName": "Test Talabayev Anvar", "type": "talaba", "faculty": "Davolash ishi", "groupOrPosition": "1"},
    )
    return resp.json()


@pytest.mark.usefixtures("seeded")
class TestAttendance:
    async def test_record_and_fetch_calendar(self, client: AsyncClient, a_student):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/attendance",
            headers=headers,
            json={"studentStaffId": a_student["id"], "date": "2026-08-01", "status": "keldi", "checkIn": "08:55"},
        )
        assert resp.status_code == 201
        assert resp.json() == {
            "date": "2026-08-01", "status": "keldi", "checkIn": "08:55", "checkOut": None, "earlyLeave": False,
        }

        calendar = await client.get(f"/api/attendance/{a_student['id']}", headers=headers, params={"month": "2026-08"})
        assert calendar.json() == [
            {"date": "2026-08-01", "status": "keldi", "checkIn": "08:55", "checkOut": None, "earlyLeave": False},
        ]

    async def test_re_recording_same_day_upserts(self, client: AsyncClient, a_student):
        headers = await auth_headers(client, "admin", "admin123")
        await client.post(
            "/api/attendance",
            headers=headers,
            json={"studentStaffId": a_student["id"], "date": "2026-08-01", "status": "keldi", "checkIn": "08:55"},
        )
        resp = await client.post(
            "/api/attendance",
            headers=headers,
            json={
                "studentStaffId": a_student["id"],
                "date": "2026-08-01",
                "status": "keldi",
                "checkIn": "08:55",
                "checkOut": "17:10",
            },
        )
        assert resp.json()["checkOut"] == "17:10"

        calendar = await client.get(f"/api/attendance/{a_student['id']}", headers=headers, params={"month": "2026-08"})
        assert len(calendar.json()) == 1  # still one row, not two

    async def test_unknown_person_is_404(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/attendance",
            headers=headers,
            json={
                "studentStaffId": "00000000-0000-0000-0000-000000000000",
                "date": "2026-08-01",
                "status": "keldi",
            },
        )
        assert resp.status_code == 404

    async def test_delete_attendance_record(self, client: AsyncClient, a_student):
        headers = await auth_headers(client, "admin", "admin123")
        await client.post(
            "/api/attendance",
            headers=headers,
            json={"studentStaffId": a_student["id"], "date": "2026-08-01", "status": "keldi"},
        )

        resp = await client.delete(f"/api/attendance/{a_student['id']}/2026-08-01", headers=headers)
        assert resp.status_code == 204

        calendar = await client.get(f"/api/attendance/{a_student['id']}", headers=headers, params={"month": "2026-08"})
        assert calendar.json() == []

    async def test_delete_unknown_attendance_record_is_404(self, client: AsyncClient, a_student):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.delete(f"/api/attendance/{a_student['id']}/2026-08-01", headers=headers)
        assert resp.status_code == 404

    async def test_check_out_before_cutoff_is_flagged_early_leave(self, client: AsyncClient, a_student):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/attendance",
            headers=headers,
            json={
                "studentStaffId": a_student["id"], "date": "2026-08-01", "status": "keldi",
                "checkIn": "08:00", "checkOut": "14:30",  # default cutoff is 16:00
            },
        )
        assert resp.json()["earlyLeave"] is True

    async def test_check_out_after_cutoff_is_not_early_leave(self, client: AsyncClient, a_student):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/attendance",
            headers=headers,
            json={
                "studentStaffId": a_student["id"], "date": "2026-08-01", "status": "keldi",
                "checkIn": "08:00", "checkOut": "17:00",
            },
        )
        assert resp.json()["earlyLeave"] is False

    async def test_absent_day_is_never_early_leave_regardless_of_check_out(self, client: AsyncClient, a_student):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/attendance",
            headers=headers,
            json={"studentStaffId": a_student["id"], "date": "2026-08-01", "status": "kelmadi"},
        )
        assert resp.json()["earlyLeave"] is False

    async def test_no_check_out_at_all_is_not_early_leave(self, client: AsyncClient, a_student):
        """A day with no check_out is missing data, not evidence someone
        left early — must not be flagged."""
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/attendance",
            headers=headers,
            json={"studentStaffId": a_student["id"], "date": "2026-08-01", "status": "keldi", "checkIn": "08:00"},
        )
        assert resp.json()["earlyLeave"] is False


@pytest.mark.usefixtures("seeded")
class TestLessonSessions:
    async def test_create_and_list(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/lesson-sessions",
            headers=headers,
            json={
                "date": "2026-08-01",
                "group": "302-guruh",
                "faculty": "Davolash ishi",
                "teacher": "Nazarov K.",
                "subject": "Fiziologiya",
                "attentionScore": 78,
                "sleepIncidents": 2,
                "teacherActivityScore": 85,
                "teacherOnTime": True,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["group"] == "302-guruh"

        listed = await client.get("/api/lesson-sessions", headers=headers)
        assert listed.json()["total"] == 1

    async def test_filter_by_group(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        for group in ["101-guruh", "204-guruh"]:
            await client.post(
                "/api/lesson-sessions",
                headers=headers,
                json={
                    "date": "2026-08-01",
                    "group": group,
                    "faculty": "Davolash ishi",
                    "teacher": "X",
                    "subject": "Y",
                    "attentionScore": 50,
                    "teacherActivityScore": 50,
                },
            )
        resp = await client.get("/api/lesson-sessions", headers=headers, params={"group": "101-guruh"})
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["group"] == "101-guruh"

    async def test_delete_lesson_session(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = (
            await client.post(
                "/api/lesson-sessions",
                headers=headers,
                json={
                    "date": "2026-08-01",
                    "group": "302-guruh",
                    "faculty": "Davolash ishi",
                    "teacher": "Nazarov K.",
                    "subject": "Fiziologiya",
                    "attentionScore": 78,
                    "teacherActivityScore": 85,
                    "teacherOnTime": True,
                },
            )
        ).json()

        resp = await client.delete(f"/api/lesson-sessions/{created['id']}", headers=headers)
        assert resp.status_code == 204

        listed = await client.get("/api/lesson-sessions", headers=headers)
        assert listed.json()["total"] == 0

    async def test_delete_unknown_lesson_session_is_404(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.delete("/api/lesson-sessions/00000000-0000-0000-0000-000000000000", headers=headers)
        assert resp.status_code == 404


@pytest.mark.usefixtures("seeded")
class TestReports:
    async def test_generate_with_no_data_is_honest_zeros(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post("/api/reports/generate", headers=headers, json={"period": "Kunlik"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["source"] == "rule"
        stat_values = {s["label"]: s["value"] for s in body["stats"]}
        assert stat_values["Umumiy davomat"] == "0.0%"
        assert stat_values["AI signallar"] == "0"

    async def test_generate_reflects_real_attendance(self, client: AsyncClient, a_student):
        headers = await auth_headers(client, "admin", "admin123")
        # "Kunlik" aggregates over date.today() — record attendance for
        # that exact date so the assertion is a real, deterministic 100%,
        # not a hedge over whichever day the test happens to run on.
        today = date.today().isoformat()
        await client.post(
            "/api/attendance",
            headers=headers,
            json={"studentStaffId": a_student["id"], "date": today, "status": "keldi"},
        )
        resp = await client.post("/api/reports/generate", headers=headers, json={"period": "Kunlik"})
        stat_values = {s["label"]: s["value"] for s in resp.json()["stats"]}
        assert stat_values["Umumiy davomat"] == "100.0%"

    async def test_list_and_get_report(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = (
            await client.post("/api/reports/generate", headers=headers, json={"period": "Haftalik"})
        ).json()

        listed = await client.get("/api/reports", headers=headers)
        assert listed.json()["total"] == 1

        fetched = await client.get(f"/api/reports/{created['id']}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["id"] == created["id"]

    async def test_filter_reports_by_period(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        await client.post("/api/reports/generate", headers=headers, json={"period": "Kunlik"})
        await client.post("/api/reports/generate", headers=headers, json={"period": "Oylik"})

        daily = await client.get("/api/reports?period=Kunlik", headers=headers)
        assert daily.json()["total"] == 1
        assert daily.json()["items"][0]["period"] == "Kunlik"

        monthly = await client.get("/api/reports?period=Oylik", headers=headers)
        assert monthly.json()["total"] == 1
        assert monthly.json()["items"][0]["period"] == "Oylik"

        all_reports = await client.get("/api/reports", headers=headers)
        assert all_reports.json()["total"] == 2

    async def test_missing_report_is_404(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/reports/00000000-0000-0000-0000-000000000000", headers=headers)
        assert resp.status_code == 404

    async def test_operator_without_view_reports_is_forbidden(self, client: AsyncClient):
        super_headers = await auth_headers(client, "admin", "admin123")
        await client.patch("/api/permissions/viewReports", headers=super_headers, json={"role": "admin"})
        admin_headers = await auth_headers(client, "operator", "operator123")
        resp = await client.get("/api/reports", headers=admin_headers)
        assert resp.status_code == 403

    async def test_delete_report(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = (
            await client.post("/api/reports/generate", headers=headers, json={"period": "Kunlik"})
        ).json()

        resp = await client.delete(f"/api/reports/{created['id']}", headers=headers)
        assert resp.status_code == 204

        listed = await client.get("/api/reports", headers=headers)
        assert listed.json()["total"] == 0

    async def test_delete_unknown_report_is_404(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.delete("/api/reports/00000000-0000-0000-0000-000000000000", headers=headers)
        assert resp.status_code == 404
