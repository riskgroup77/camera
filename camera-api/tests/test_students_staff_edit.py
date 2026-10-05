"""Tahrirlash: JSHSHIR, pasport, kurs/guruh alohida; qidiruv va eksport
filtri URL'da emas, so'rov tanasida (audit #4, #5, #6).

Barcha shaxsiy ma'lumotlar SOXTA."""

import io

import openpyxl
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import AuditLog, Faculty, StudentStaff
from tests.conftest import auth_headers

FAKE_PINFL = "30000000000017"
OTHER_PINFL = "30000000000025"


@pytest.fixture
async def two_people(db_session, seeded):
    faculty = (await db_session.execute(select(Faculty).where(Faculty.name == "Davolash ishi"))).scalar_one()
    student = StudentStaff(full_name="Soxtaov Talaba Birinchi", type="talaba", faculty_id=faculty.id,
                           group_or_position="2-kurs, DI-1625", biometrics_status="yoq", pinfl=FAKE_PINFL,
                           passport_series="AA", passport_number="1111111")
    other = StudentStaff(full_name="Boshqaov Xodim Ikkinchi", type="xodim", faculty_id=faculty.id,
                         group_or_position="Anatomiya kafedrasi", biometrics_status="yoq", pinfl=OTHER_PINFL,
                         passport_series="BB", passport_number="2222222")
    db_session.add_all([student, other])
    await db_session.commit()
    return student, other


def _base(person: StudentStaff, **extra):
    body = {"fullName": person.full_name, "type": person.type, "faculty": "Davolash ishi"}
    body.update(extra)
    return body


class TestDetails:
    async def test_details_include_identifiers_but_list_does_not(self, client: AsyncClient, two_people):
        student, _ = two_people
        headers = await auth_headers(client, "admin", "admin123")
        detail = (await client.get(f"/api/students-staff/{student.id}/details", headers=headers)).json()
        assert detail["pinfl"] == FAKE_PINFL
        assert detail["passportSeries"] == "AA" and detail["passportNumber"] == "1111111"
        assert detail["course"] == 2 and detail["group"] == "DI-1625"

        listing = (await client.post("/api/students-staff/search", json={"type": "talaba"}, headers=headers)).json()
        assert "pinfl" not in listing["items"][0]


class TestUpdate:
    async def test_course_and_group_are_saved_separately_and_composed(self, client, db_session, two_people):
        student, _ = two_people
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.patch(f"/api/students-staff/{student.id}", headers=headers,
                                  json=_base(student, course=3, group=" DI-1525 "))
        assert resp.status_code == 200, resp.text
        assert resp.json()["groupOrPosition"] == "3-kurs, DI-1525"
        assert resp.json()["course"] == 3 and resp.json()["group"] == "DI-1525"

    async def test_pinfl_and_passport_can_be_changed(self, client, db_session, two_people):
        student, _ = two_people
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.patch(f"/api/students-staff/{student.id}", headers=headers,
                                  json=_base(student, course=2, group="DI-1625", pinfl="3000 0000 0000 33",
                                             passportSeries="ad", passportNumber="7654321"))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["pinfl"] == "30000000000033"
        assert (body["passportSeries"], body["passportNumber"]) == ("AD", "7654321")

        # Audit jurnalida raqamlarning o'zi qolmaydi.
        logs = (await db_session.execute(select(AuditLog.action))).scalars().all()
        assert any("JSHSHIR, pasport yangilandi" in a for a in logs)
        assert not any("30000000000033" in a or "7654321" in a for a in logs)

    async def test_omitted_identifiers_are_left_untouched(self, client, db_session, two_people):
        student, _ = two_people
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.patch(f"/api/students-staff/{student.id}", headers=headers,
                                  json=_base(student, course=2, group="DI-1625"))
        assert resp.json()["pinfl"] == FAKE_PINFL

    async def test_empty_pinfl_clears_it(self, client, two_people):
        student, _ = two_people
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.patch(f"/api/students-staff/{student.id}", headers=headers,
                                  json=_base(student, course=2, group="DI-1625", pinfl=""))
        assert resp.json()["pinfl"] is None

    async def test_pinfl_of_another_person_is_a_conflict(self, client, two_people):
        student, other = two_people
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.patch(f"/api/students-staff/{student.id}", headers=headers,
                                  json=_base(student, course=2, group="DI-1625", pinfl=OTHER_PINFL))
        assert resp.status_code == 409
        assert other.full_name in resp.json()["detail"]

    async def test_passport_of_another_person_is_a_conflict(self, client, two_people):
        student, _ = two_people
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.patch(f"/api/students-staff/{student.id}", headers=headers,
                                  json=_base(student, course=2, group="DI-1625", passportSeries="BB",
                                             passportNumber="2222222"))
        assert resp.status_code == 409

    @pytest.mark.parametrize("field,value", [("pinfl", "123"), ("passportNumber", "12")])
    async def test_malformed_identifiers_are_rejected(self, client, two_people, field, value):
        student, _ = two_people
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.patch(f"/api/students-staff/{student.id}", headers=headers,
                                  json=_base(student, course=2, group="DI-1625", **{field: value}))
        assert resp.status_code == 422

    async def test_staff_keeps_free_text_position(self, client, two_people):
        _, other = two_people
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.patch(f"/api/students-staff/{other.id}", headers=headers,
                                  json=_base(other, groupOrPosition="Fiziologiya kafedrasi"))
        assert resp.status_code == 200
        assert resp.json()["groupOrPosition"] == "Fiziologiya kafedrasi"
        assert resp.json()["course"] is None


class TestSearchAndExportInBody:
    async def test_search_by_pinfl_in_body(self, client, two_people):
        student, _ = two_people
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post("/api/students-staff/search", headers=headers,
                                 json={"search": FAKE_PINFL, "pageSize": 5})
        assert resp.status_code == 200
        assert [item["id"] for item in resp.json()["items"]] == [str(student.id)]

    async def test_export_with_filters_in_body(self, client, two_people):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post("/api/students-staff/export", headers=headers,
                                 json={"kind": "people", "type": "talaba", "search": FAKE_PINFL})
        assert resp.status_code == 200
        ws = openpyxl.load_workbook(io.BytesIO(resp.content)).active
        values = [c for row in ws.iter_rows(values_only=True) for c in row if c]
        assert "Soxtaov Talaba Birinchi" in values


class TestFailedLoginMasking:
    async def test_pinfl_typed_into_login_is_not_logged_in_full(self, client, db_session, seeded):
        resp = await client.post("/api/auth/login", json={"login": FAKE_PINFL, "password": "noto'g'ri"})
        assert resp.status_code == 401
        names = (await db_session.execute(select(AuditLog.user_name))).scalars().all()
        assert FAKE_PINFL not in names
        assert any(n.startswith("30") and n.endswith("17") and "*" in n for n in names)
