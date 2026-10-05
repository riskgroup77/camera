"""Davomat kalendari: oy oralig'i predikati va odamning oylik yig'indisi.

Barcha shaxsiy ma'lumotlar SOXTA."""

import uuid
from datetime import date, time

import pytest
from httpx import AsyncClient

from app.models import AttendanceRecord
from app.routers.attendance import _add_months
from app.timezone import local_now
from tests.conftest import auth_headers


@pytest.fixture
async def person(client: AsyncClient, db_session, seeded):
    headers = await auth_headers(client, "admin", "admin123")
    resp = await client.post(
        "/api/students-staff",
        headers=headers,
        json={"fullName": "Soxtaov Xodim Birinchi", "type": "xodim", "faculty": "Davolash ishi", "groupOrPosition": "Kafedra"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def record(person_id: str, day: date, status: str, check_in: time | None = None, check_out: time | None = None):
    return AttendanceRecord(
        student_staff_id=uuid.UUID(person_id), date=day, status=status, check_in=check_in, check_out=check_out
    )


class TestCalendarRange:
    async def test_month_bounds_include_first_and_last_day_only(self, client: AsyncClient, db_session, person):
        db_session.add_all([
            record(person["id"], date(2025, 12, 31), "keldi"),
            record(person["id"], date(2026, 1, 1), "keldi"),
            record(person["id"], date(2026, 1, 31), "kech_keldi"),
            record(person["id"], date(2026, 2, 1), "kelmadi"),
        ])
        await db_session.commit()
        headers = await auth_headers(client, "admin", "admin123")

        january = await client.get(f"/api/attendance/{person['id']}", headers=headers, params={"month": "2026-01"})
        assert [d["date"] for d in january.json()] == ["2026-01-01", "2026-01-31"]
        december = await client.get(f"/api/attendance/{person['id']}", headers=headers, params={"month": "2025-12"})
        assert [d["date"] for d in december.json()] == ["2025-12-31"]

    @pytest.mark.parametrize("month", ["2026-13", "2026", "abc", "2026-01-05"])
    async def test_invalid_month_is_422(self, client: AsyncClient, person, month):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get(f"/api/attendance/{person['id']}", headers=headers, params={"month": month})
        assert resp.status_code == 422

    async def test_invalid_person_id_is_404_not_500(self, client: AsyncClient, seeded):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/attendance/not-a-uuid", headers=headers, params={"month": "2026-01"})
        assert resp.status_code == 404


class TestSummary:
    async def test_current_month_totals_and_empty_previous_month(self, client: AsyncClient, db_session, person):
        current = local_now().date().replace(day=1)
        db_session.add_all([
            record(person["id"], current.replace(day=1), "keldi", time(8, 30), time(17, 30)),
            record(person["id"], current.replace(day=2), "kech_keldi", time(9, 30), time(13, 0)),
            record(person["id"], current.replace(day=3), "kelmadi"),
            record(person["id"], current.replace(day=4), "dam_olish"),
        ])
        await db_session.commit()
        headers = await auth_headers(client, "admin", "admin123")

        resp = await client.get(f"/api/attendance/{person['id']}/summary", headers=headers, params={"months": 2})
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["person"]["fullName"] == "Soxtaov Xodim Birinchi"
        assert body["person"]["biometricsStatus"] == "yoq" and body["person"]["biometricPhotoUrl"] is None
        assert body["workingWeekdays"] and set(body["workingWeekdays"]) <= set(range(1, 8))

        previous, this_month = body["months"]
        assert previous["month"] == _add_months(current, -1).strftime("%Y-%m")
        assert previous["recordedDays"] == 0 and previous["rate"] is None and previous["avgArrival"] is None

        calendar = await client.get(
            f"/api/attendance/{person['id']}", headers=headers, params={"month": current.strftime("%Y-%m")}
        )
        assert this_month == {
            "month": current.strftime("%Y-%m"),
            "recordedDays": 3,
            "present": 1,
            "late": 1,
            "absent": 1,
            "earlyLeave": sum(day["earlyLeave"] for day in calendar.json()),
            "rate": 66.7,
            "avgArrival": "09:00",
            "avgPresenceMinutes": 375,
        }

    async def test_default_window_is_six_months_ending_now(self, client: AsyncClient, person):
        headers = await auth_headers(client, "admin", "admin123")
        months = (await client.get(f"/api/attendance/{person['id']}/summary", headers=headers)).json()["months"]
        assert len(months) == 6
        assert months[-1]["month"] == local_now().date().strftime("%Y-%m")

    async def test_unknown_or_invalid_person_and_bad_window(self, client: AsyncClient, person):
        headers = await auth_headers(client, "admin", "admin123")
        assert (await client.get(f"/api/attendance/{uuid.uuid4()}/summary", headers=headers)).status_code == 404
        assert (await client.get("/api/attendance/nope/summary", headers=headers)).status_code == 404
        for months in (0, 13):
            resp = await client.get(f"/api/attendance/{person['id']}/summary", headers=headers, params={"months": months})
            assert resp.status_code == 422
