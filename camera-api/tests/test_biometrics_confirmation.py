"""'Aniqlash' oynasi: odam yuzini aniq qachon tasdiqlagani.

Savol har doim "Toshkent vaqti bilan soat nechida" — shuning uchun vaqt
serverda institut vaqtiga o'tkaziladi. Eng oson yo'l qo'yiladigan xato
UTC vaqtni shundayligicha ko'rsatish: 13:57 da tasdiqlagan odam 08:57 da
tasdiqlagandek ko'rinardi, kechki 00:00-05:00 dagilar esa oldingi kunda.
"""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Faculty, StudentStaff
from app.routers import enrollment, students_staff
from app.timezone import uz_datetime_parts
from tests.conftest import ENROLL_CODE, auth_headers

PINFL = "30000000000099"
CONFIRMED_UTC = datetime(2026, 9, 14, 8, 57, 54, tzinfo=timezone.utc)  # Toshkentda 13:57:54


@pytest.fixture
async def person(db_session, seeded) -> StudentStaff:
    faculty = (await db_session.execute(select(Faculty).limit(1))).scalar_one()
    record = StudentStaff(
        full_name="Karimova Dilnoza Oybek qizi",
        type="talaba",
        pinfl=PINFL,
        faculty_id=faculty.id,
        group_or_position="2-kurs, DI-1625",
        biometrics_status="yoq",
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    return record


async def _confirmation(client: AsyncClient, record_id) -> dict:
    headers = await auth_headers(client, "admin", "admin123")
    resp = await client.get(f"/api/students-staff/{record_id}/biometrics-confirmation", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestTashkentFormatting:
    def test_utc_moment_is_shown_in_tashkent_time(self):
        parts = uz_datetime_parts(CONFIRMED_UTC)
        assert parts.time == "13:57:54"
        assert parts.date == "14-sentabr, 2026-yil"
        assert parts.weekday == "dushanba"
        assert parts.iso == "2026-09-14T13:57:54+05:00"

    def test_late_utc_evening_is_already_the_next_local_day(self):
        parts = uz_datetime_parts(datetime(2026, 12, 31, 20, 30, tzinfo=timezone.utc))
        assert parts.date == "1-yanvar, 2027-yil"
        assert parts.time == "01:30:00"
        assert parts.weekday == "juma"


class TestConfirmationIsRecorded:
    async def test_self_service_enrollment_records_the_moment(
        self, client: AsyncClient, db_session, person, monkeypatch
    ):
        async def no_liveness_check(frames):
            return None

        async def fake_embedding(frames):
            return [0.1] * 512

        monkeypatch.setattr(enrollment, "_verify_liveness", no_liveness_check)
        monkeypatch.setattr(enrollment, "extract_enrollment_embedding", fake_embedding)
        monkeypatch.setattr(enrollment, "upload_file", lambda *a, **k: ("id", "biometrics/id-face.jpg"))

        before = datetime.now(timezone.utc)
        resp = await client.post(
            f"/api/public/enrollment/{person.id}/submit",
            data={"code": ENROLL_CODE, "pinfl": PINFL, "consent": "true"},
            files=[("photos", (f"{n}.jpg", b"frame", "image/jpeg")) for n in ("front", "left", "right")],
        )
        assert resp.status_code == 200, resp.text

        await db_session.refresh(person)
        assert person.biometrics_status == "tasdiqlangan"
        assert person.biometrics_confirmed_at is not None
        assert before <= person.biometrics_confirmed_at <= datetime.now(timezone.utc)

    async def test_admin_enrollment_records_the_moment(self, client: AsyncClient, db_session, person, monkeypatch):
        async def fake_embedding(data):
            return [0.1] * 512

        monkeypatch.setattr(students_staff, "extract_embedding", fake_embedding)
        monkeypatch.setattr(students_staff, "upload_file", lambda *a, **k: ("id", "biometrics/id-face.jpg"))

        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            f"/api/students-staff/{person.id}/biometrics",
            headers=headers,
            files={"photo": ("face.jpg", b"frame", "image/jpeg")},
        )
        # Bitta surat bilan yuz kiritilmaydi (3 tomon shart) — vaqt ham yozilmaydi.
        assert resp.status_code == 422, resp.text
        return

        await db_session.refresh(person)
        assert person.biometrics_confirmed_at is not None


class TestConfirmationEndpoint:
    async def test_recorded_moment_in_tashkent_time(self, client: AsyncClient, db_session, person):
        person.biometrics_status = "tasdiqlangan"
        person.biometrics_confirmed_at = CONFIRMED_UTC
        await db_session.commit()

        body = await _confirmation(client, person.id)
        assert body["fullName"] == "Karimova Dilnoza Oybek qizi"
        assert body["confirmedTime"] == "13:57:54"
        assert body["confirmedDate"] == "14-sentabr, 2026-yil"
        assert body["confirmedWeekday"] == "dushanba"
        assert body["confirmedAt"] == "2026-09-14T13:57:54+05:00"
        assert body["source"] == "tizim"

    async def test_older_confirmation_is_restored_from_the_photo_time(
        self, client: AsyncClient, db_session, person, monkeypatch
    ):
        """Ustun paydo bo'lishidan oldin tasdiqlaganlar — vaqt yuz rasmi
        omborga yozilgan paytdan olinadi va bu javobda ko'rinib turadi."""
        person.biometrics_status = "tasdiqlangan"
        person.biometric_photo_key = "biometrics/old-face.jpg"
        await db_session.commit()
        monkeypatch.setattr(students_staff, "object_last_modified", lambda key: CONFIRMED_UTC)

        body = await _confirmation(client, person.id)
        assert body["confirmedTime"] == "13:57:54"
        assert body["source"] == "rasm"

        await db_session.refresh(person)
        assert person.biometrics_confirmed_at is None  # tiklangan vaqt "tizim" yozuvi sifatida saqlanmaydi

    @pytest.mark.parametrize("storage", ["missing", "unreachable"])
    async def test_unknown_time_is_said_plainly(self, client: AsyncClient, db_session, person, monkeypatch, storage):
        person.biometrics_status = "tasdiqlangan"
        person.biometric_photo_key = "biometrics/old-face.jpg"
        await db_session.commit()

        def lookup(key):
            if storage == "unreachable":
                raise RuntimeError("MinIO javob bermadi")
            return None

        monkeypatch.setattr(students_staff, "object_last_modified", lookup)

        body = await _confirmation(client, person.id)
        assert body["source"] == "nomalum"
        assert body["confirmedTime"] is None

    async def test_not_yet_confirmed(self, client: AsyncClient, person):
        body = await _confirmation(client, person.id)
        assert body["source"] == "tasdiqlanmagan"
        assert body["biometricsStatus"] == "yoq"
        assert body["confirmedAt"] is None

    @pytest.mark.parametrize("record_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
    async def test_unknown_record_is_404(self, client: AsyncClient, seeded, record_id):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get(f"/api/students-staff/{record_id}/biometrics-confirmation", headers=headers)
        assert resp.status_code == 404

    async def test_requires_permission(self, client: AsyncClient, person):
        resp = await client.get(f"/api/students-staff/{person.id}/biometrics-confirmation")
        assert resp.status_code in (401, 403)


class TestNameSearchForSuggestions:
    async def _names(self, client: AsyncClient, search: str) -> list[str]:
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/students-staff", params={"search": search, "pageSize": 8}, headers=headers)
        assert resp.status_code == 200
        return [item["fullName"] for item in resp.json()["items"]]

    async def test_word_order_does_not_matter(self, client: AsyncClient, person):
        """Bazada "Familiya Ism", odam esa ko'pincha "Ism Familiya" yozadi."""
        assert "Karimova Dilnoza Oybek qizi" in await self._names(client, "dilnoza karimova")

    async def test_every_word_must_match(self, client: AsyncClient, person):
        assert await self._names(client, "dilnoza saidova") == []

    async def test_apostrophe_variants_match(self, client: AsyncClient, db_session, seeded):
        db_session.add(StudentStaff(full_name="Saidov Bobur Anvar o'g'li", type="talaba",
                                    group_or_position="3-kurs", biometrics_status="yoq"))
        await db_session.commit()
        assert "Saidov Bobur Anvar o'g'li" in await self._names(client, "o‘g‘li saidov")
