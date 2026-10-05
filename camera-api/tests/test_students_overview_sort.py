"""Talabalar va Xodimlar: qamrov bitta so'rovda va ro'yxatni saralash.

Barcha shaxsiy ma'lumotlar SOXTA."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Faculty, StudentStaff
from tests.conftest import auth_headers


@pytest.fixture
async def people(db_session, seeded):
    faculty = (await db_session.execute(select(Faculty).where(Faculty.name == "Davolash ishi"))).scalar_one()
    now = datetime.now(timezone.utc)
    db_session.add_all([
        StudentStaff(full_name="Alimov Birinchi", type="xodim", faculty_id=faculty.id, group_or_position="Kafedra",
                     biometrics_status="tasdiqlangan", biometrics_confirmed_at=now - timedelta(days=3)),
        StudentStaff(full_name="Boboyev Ikkinchi", type="xodim", faculty_id=faculty.id, group_or_position="Kafedra",
                     biometrics_status="tasdiqlangan", biometrics_confirmed_at=now - timedelta(hours=1)),
        StudentStaff(full_name="Valiyev Uchinchi", type="xodim", group_or_position="Xo'jalik bo'limi",
                     biometrics_status="yoq"),
        StudentStaff(full_name="Soxtaova Talaba", type="talaba", faculty_id=faculty.id,
                     group_or_position="2-kurs, DI-1", biometrics_status="kutilmoqda"),
    ])
    await db_session.commit()


async def search(client: AsyncClient, **body):
    headers = await auth_headers(client, "admin", "admin123")
    resp = await client.post("/api/students-staff/search", headers=headers, json={"pageSize": 50, **body})
    assert resp.status_code == 200, resp.text
    return [item["fullName"] for item in resp.json()["items"]]


class TestOverview:
    async def test_both_types_in_one_response(self, client: AsyncClient, people):
        headers = await auth_headers(client, "admin", "admin123")
        body = (await client.get("/api/students-staff/overview", headers=headers)).json()
        assert body["xodim"]["total"] == 3 and body["xodim"]["confirmed"] == 2 and body["xodim"]["missing"] == 1
        assert body["talaba"]["total"] == 1 and body["talaba"]["pending"] == 1
        assert body["talaba"]["byCourse"][0]["courseNumber"] == 2
        assert body["xodim"]["byCourse"] == []


class TestSort:
    async def test_default_is_name(self, client: AsyncClient, people):
        assert await search(client, type="xodim") == ["Alimov Birinchi", "Boboyev Ikkinchi", "Valiyev Uchinchi"]

    async def test_recently_confirmed_first_unconfirmed_last(self, client: AsyncClient, people):
        assert await search(client, type="xodim", sort="confirmed") == [
            "Boboyev Ikkinchi", "Alimov Birinchi", "Valiyev Uchinchi",
        ]

    async def test_faculty_keeps_people_without_faculty_at_the_end(self, client: AsyncClient, people):
        names = await search(client, type="xodim", sort="faculty")
        assert names[-1] == "Valiyev Uchinchi" and len(names) == 3
        # Fakultet filtri bilan birga ham ishlaydi (join ikki marta qo'shilmaydi).
        assert await search(client, type="xodim", sort="faculty", faculty="Davolash ishi") == [
            "Alimov Birinchi", "Boboyev Ikkinchi",
        ]

    async def test_unknown_sort_is_rejected(self, client: AsyncClient, people):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post("/api/students-staff/search", headers=headers, json={"sort": "salary"})
        assert resp.status_code == 422
