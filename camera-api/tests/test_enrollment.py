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

    async def test_submit_rejects_too_few_frames(self, client: AsyncClient, an_enrollable_record):
        with open(FACE_IMAGE_PATH, "rb") as f1:
            resp = await client.post(
                f"/api/public/enrollment/{an_enrollable_record.id}/submit",
                data={"passportSeries": "AD", "passportNumber": "1234567"},
                files=[("photos", ("a.jpg", f1, "image/jpeg"))],
            )
        assert resp.status_code == 422
