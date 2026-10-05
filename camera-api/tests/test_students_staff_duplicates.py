"""Admin "Yangi biriktirish" ro'yxatdagi odamni qayta qo'shmasligi kerak.

Real holat: import qilingan 80 dan ortiq xodim shu oyna orqali qayta
qo'shilgan va yuzi yangi, JSHSHIRsiz yozuvda tasdiqlangan — natijada har
biri ikki marta sanalgan. Birlashtirish skripti o'tgandan keyin ham bir
kunda yana 12 tasi qo'shilgan. Manbani yopish shu testlarning maqsadi.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Faculty, StudentStaff
from tests.conftest import auth_headers


@pytest.fixture
async def imported_staff(db_session, seeded) -> StudentStaff:
    faculty = (await db_session.execute(select(Faculty).where(Faculty.name == "Davolash ishi"))).scalar_one()
    record = StudentStaff(full_name="Ismoilov Sanjarbek Saloxiddin o'g'li", type="xodim", pinfl="30000000000048",
                          faculty_id=faculty.id, group_or_position="Raqamli texnologiyalar bo'limi",
                          biometrics_status="yoq")
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    return record


def _body(full_name, **extra):
    return {"fullName": full_name, "type": "xodim", "faculty": "Davolash ishi",
            "groupOrPosition": "Tizim administratori", **extra}


class TestSimilar:
    async def test_finds_the_person_written_differently(self, client: AsyncClient, imported_staff):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/students-staff/similar", headers=headers,
                                params={"fullName": "Ismoilov Sanjarbek Salohiddin o‘g‘li", "type": "xodim"})
        assert resp.status_code == 200
        assert [p["id"] for p in resp.json()] == [str(imported_staff.id)]

    async def test_other_type_is_not_listed(self, client: AsyncClient, imported_staff):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/students-staff/similar", headers=headers,
                                params={"fullName": "Ismoilov Sanjarbek Saloxiddin o'g'li", "type": "talaba"})
        assert resp.json() == []

    async def test_a_different_person_is_not_listed(self, client: AsyncClient, imported_staff):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/students-staff/similar", headers=headers,
                                params={"fullName": "Ismoilov Sanjarbek Botirovich", "type": "xodim"})
        assert resp.json() == []

    async def test_requires_permission(self, client: AsyncClient, imported_staff):
        resp = await client.get("/api/students-staff/similar", params={"fullName": "Ismoilov Sanjarbek"})
        assert resp.status_code in (401, 403)


class TestCreateGuard:
    async def test_re_adding_a_listed_person_is_refused(self, client: AsyncClient, db_session, imported_staff):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post("/api/students-staff", headers=headers,
                                 json=_body("ISMOILOV SANJARBEK SALOHIDDIN O'G'LI"))
        assert resp.status_code == 409
        assert "Ismoilov Sanjarbek Saloxiddin o'g'li" in resp.json()["detail"]
        count = len((await db_session.execute(select(StudentStaff))).scalars().all())
        assert count == 1

    async def test_explicitly_confirmed_new_person_is_created(self, client: AsyncClient, imported_staff):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post("/api/students-staff", headers=headers,
                                 json=_body("Ismoilov Sanjarbek Salohiddin o'g'li", allowDuplicate=True))
        assert resp.status_code == 201

    async def test_an_unrelated_name_is_created_without_questions(self, client: AsyncClient, imported_staff):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post("/api/students-staff", headers=headers, json=_body("Karimova Dildora Anvarovna"))
        assert resp.status_code == 201
