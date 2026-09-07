from pathlib import Path

import insightface
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Faculty, StudentStaff

# Same fixtures test_biometrics.py uses — a real detectable face (t1.jpg)
# and a different real person (Tom Hanks) to exercise the multi-frame
# consistency check with a genuine mismatch, not a synthetic one.
FACE_IMAGE_PATH = Path(insightface.__file__).parent / "data" / "images" / "t1.jpg"
OTHER_FACE_IMAGE_PATH = Path(insightface.__file__).parent / "data" / "images" / "Tom_Hanks_54745.png"


@pytest.fixture
async def an_enrollable_record(db_session: AsyncSession, seeded) -> StudentStaff:
    faculty = (await db_session.execute(select(Faculty).limit(1))).scalar_one()
    record = StudentStaff(
        full_name="Soyibnazarov Hojiakbar",
        type="xodim",
        faculty_id=faculty.id,
        group_or_position="Xavfsizlik bo'limi",
        passport_series="AD",
        passport_number="1234567",
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    return record


@pytest.mark.usefixtures("seeded")
class TestEnrollmentLookup:
    async def test_lookup_finds_record_by_passport(self, client: AsyncClient, an_enrollable_record):
        resp = await client.post(
            "/api/public/enrollment/lookup", json={"passportSeries": "AD", "passportNumber": "1234567"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["fullName"] == "Soyibnazarov Hojiakbar"
        assert body["typeLabel"] == "Xodim"
        assert body["alreadyEnrolled"] is False

    async def test_lookup_is_case_and_space_insensitive_on_series(self, client: AsyncClient, an_enrollable_record):
        resp = await client.post(
            "/api/public/enrollment/lookup", json={"passportSeries": " ad ", "passportNumber": "1234567"}
        )
        assert resp.status_code == 200

    async def test_lookup_unknown_passport_is_404(self, client: AsyncClient, seeded):
        resp = await client.post(
            "/api/public/enrollment/lookup", json={"passportSeries": "ZZ", "passportNumber": "9999999"}
        )
        assert resp.status_code == 404


@pytest.mark.usefixtures("seeded")
class TestEnrollmentSubmit:
    async def test_submit_persists_averaged_embedding(self, client: AsyncClient, an_enrollable_record):
        with open(FACE_IMAGE_PATH, "rb") as f1, open(FACE_IMAGE_PATH, "rb") as f2:
            resp = await client.post(
                f"/api/public/enrollment/{an_enrollable_record.id}/submit",
                data={"passportSeries": "AD", "passportNumber": "1234567"},
                files=[("photos", ("a.jpg", f1, "image/jpeg")), ("photos", ("b.jpg", f2, "image/jpeg"))],
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["biometricsStatus"] == "tasdiqlangan"

    async def test_submit_rejects_mismatched_passport(self, client: AsyncClient, an_enrollable_record):
        with open(FACE_IMAGE_PATH, "rb") as f1, open(FACE_IMAGE_PATH, "rb") as f2:
            resp = await client.post(
                f"/api/public/enrollment/{an_enrollable_record.id}/submit",
                data={"passportSeries": "AD", "passportNumber": "0000000"},
                files=[("photos", ("a.jpg", f1, "image/jpeg")), ("photos", ("b.jpg", f2, "image/jpeg"))],
            )
        assert resp.status_code == 403

    async def test_submit_rejects_inconsistent_frames(self, client: AsyncClient, an_enrollable_record):
        with open(FACE_IMAGE_PATH, "rb") as f1, open(OTHER_FACE_IMAGE_PATH, "rb") as f2:
            resp = await client.post(
                f"/api/public/enrollment/{an_enrollable_record.id}/submit",
                data={"passportSeries": "AD", "passportNumber": "1234567"},
                files=[("photos", ("a.jpg", f1, "image/jpeg")), ("photos", ("b.png", f2, "image/png"))],
            )
        assert resp.status_code == 422

    async def test_submit_blocks_already_confirmed(
        self, client: AsyncClient, db_session: AsyncSession, an_enrollable_record
    ):
        an_enrollable_record.biometrics_status = "tasdiqlangan"
        await db_session.commit()

        with open(FACE_IMAGE_PATH, "rb") as f1, open(FACE_IMAGE_PATH, "rb") as f2:
            resp = await client.post(
                f"/api/public/enrollment/{an_enrollable_record.id}/submit",
                data={"passportSeries": "AD", "passportNumber": "1234567"},
                files=[("photos", ("a.jpg", f1, "image/jpeg")), ("photos", ("b.jpg", f2, "image/jpeg"))],
            )
        assert resp.status_code == 409

    async def test_a_single_uploaded_photo_is_enough(self, client: AsyncClient, an_enrollable_record):
        """This used to be rejected. The flow only knew how to capture
        several angles from a camera, so two frames were the minimum;
        now a person can upload one photo they already have, where a
        "second angle" does not exist."""
        with open(FACE_IMAGE_PATH, "rb") as f1:
            resp = await client.post(
                f"/api/public/enrollment/{an_enrollable_record.id}/submit",
                data={"passportSeries": "AD", "passportNumber": "1234567"},
                files=[("photos", ("a.jpg", f1, "image/jpeg"))],
            )
        assert resp.status_code == 200
        assert resp.json()["biometricsStatus"] == "tasdiqlangan"

    async def test_a_photo_without_a_face_is_still_rejected(
        self, client: AsyncClient, an_enrollable_record
    ):
        """Accepting one photo must not mean accepting any photo — the
        whole point of the step is that a face goes into the database."""
        resp = await client.post(
            f"/api/public/enrollment/{an_enrollable_record.id}/submit",
            data={"passportSeries": "AD", "passportNumber": "1234567"},
            files=[("photos", ("blank.jpg", b"not an image at all", "image/jpeg"))],
        )
        assert resp.status_code == 422

    async def test_no_photo_at_all_is_rejected(self, client: AsyncClient, an_enrollable_record):
        resp = await client.post(
            f"/api/public/enrollment/{an_enrollable_record.id}/submit",
            data={"passportSeries": "AD", "passportNumber": "1234567"},
        )
        assert resp.status_code == 422


@pytest.mark.usefixtures("seeded")
class TestSelfRegistration:
    """Before this, a passport the system did not know ended the flow:
    lookup answered 404 and the person had to wait for an administrator
    to type their details in. They can now enter them themselves and go
    straight on to the photo step."""

    async def test_registering_creates_a_record_ready_for_a_photo(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        resp = await client.post(
            "/api/public/enrollment/register",
            json={
                "fullName": "Yangi Talaba",
                "type": "talaba",
                "groupOrPosition": "301-guruh",
                "passportSeries": "AB",
                "passportNumber": "7654321",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["fullName"] == "Yangi Talaba"
        assert body["typeLabel"] == "Talaba"
        assert body["alreadyEnrolled"] is False

        record = (
            await db_session.execute(
                select(StudentStaff).where(StudentStaff.passport_number == "7654321")
            )
        ).scalar_one()
        # The face comes in the NEXT step; registration only records who
        # the person is.
        assert record.biometrics_status == "yoq"
        assert record.biometric_embedding is None

    async def test_the_new_record_can_be_found_by_lookup_afterwards(self, client: AsyncClient):
        await client.post(
            "/api/public/enrollment/register",
            json={
                "fullName": "Qaytgan Talaba",
                "type": "talaba",
                "groupOrPosition": "302-guruh",
                "passportSeries": "AB",
                "passportNumber": "1112223",
            },
        )
        resp = await client.post(
            "/api/public/enrollment/lookup",
            json={"passportSeries": "AB", "passportNumber": "1112223"},
        )
        assert resp.status_code == 200
        assert resp.json()["fullName"] == "Qaytgan Talaba"

    async def test_an_existing_passport_returns_that_record_instead_of_a_duplicate(
        self, client: AsyncClient, an_enrollable_record, db_session: AsyncSession
    ):
        """Two records for one person would split their attendance in
        half, and nothing downstream could tell they were the same
        human."""
        resp = await client.post(
            "/api/public/enrollment/register",
            json={
                "fullName": "Boshqa Ism",
                "type": "talaba",
                "groupOrPosition": "999-guruh",
                "passportSeries": "AD",
                "passportNumber": "1234567",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["recordId"] == str(an_enrollable_record.id)

        count = len(
            (
                await db_session.execute(
                    select(StudentStaff).where(StudentStaff.passport_number == "1234567")
                )
            ).scalars().all()
        )
        assert count == 1

    async def test_the_series_is_normalised_the_same_way_lookup_normalises_it(
        self, client: AsyncClient
    ):
        """Registering as "ab" and looking up as "AB" has to find the
        same person, or someone registers and is then told they do not
        exist."""
        await client.post(
            "/api/public/enrollment/register",
            json={
                "fullName": "Kichik Harf",
                "type": "xodim",
                "groupOrPosition": "Laborant",
                "passportSeries": " ab ",
                "passportNumber": " 5556667 ",
            },
        )
        resp = await client.post(
            "/api/public/enrollment/lookup",
            json={"passportSeries": "AB", "passportNumber": "5556667"},
        )
        assert resp.status_code == 200

    async def test_an_unknown_faculty_is_rejected(self, client: AsyncClient):
        resp = await client.post(
            "/api/public/enrollment/register",
            json={
                "fullName": "Fakultetsiz Talaba",
                "type": "talaba",
                "groupOrPosition": "303-guruh",
                "facultyId": "00000000-0000-0000-0000-000000000000",
                "passportSeries": "AC",
                "passportNumber": "9998887",
            },
        )
        assert resp.status_code == 422

    async def test_faculties_are_listed_for_the_form(self, client: AsyncClient):
        resp = await client.get("/api/public/enrollment/faculties")
        assert resp.status_code == 200
        rows = resp.json()
        assert rows
        assert set(rows[0]) == {"id", "name"}
