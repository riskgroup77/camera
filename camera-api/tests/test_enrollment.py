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
def any_pose(monkeypatch):
    """Burilish tekshiruvini o'tkazib yuboradi.

    Bu yerdagi testlar identifikatsiya, takroriy ro'yxat va vektor
    saqlash haqida — burilish burchagi haqida emas. Uni haqiqiy
    fotosuratlar bilan sinash uchun uch xil burchakdan olingan bir xil
    odamning rasmlari kerak bo'lardi; o'lchov mantig'ining o'zi
    tests/test_head_pose.py da alohida va aniqroq tekshiriladi.
    """
    from app.routers import enrollment

    def fake_direction(_landmarks):
        return fake_direction.expected

    fake_direction.expected = "front"

    original = enrollment._verify_liveness

    async def passthrough(frames):
        # Kadrlar soni va yuz borligi baribir tekshiriladi — faqat
        # burchak sharti olib tashlanadi.
        monkeypatch.setattr(enrollment, "direction_of", lambda lm: None)
        return None

    monkeypatch.setattr(enrollment, "_verify_liveness", passthrough)
    return original


def three_frames():
    """Tiriklik oqimi kutadigan uchta kadr (bir xil rasm)."""
    data = FACE_IMAGE_PATH.read_bytes()
    return [
        ("photos", ("front.jpg", data, "image/jpeg")),
        ("photos", ("left.jpg", data, "image/jpeg")),
        ("photos", ("right.jpg", data, "image/jpeg")),
    ]


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
    async def test_submit_persists_averaged_embedding(
        self, client: AsyncClient, an_enrollable_record, any_pose
    ):
        resp = await client.post(
            f"/api/public/enrollment/{an_enrollable_record.id}/submit",
            data={"passportSeries": "AD", "passportNumber": "1234567"},
            files=three_frames(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["biometricsStatus"] == "tasdiqlangan"

    async def test_submit_rejects_mismatched_passport(self, client: AsyncClient, an_enrollable_record):
        resp = await client.post(
            f"/api/public/enrollment/{an_enrollable_record.id}/submit",
            data={"passportSeries": "AD", "passportNumber": "0000000"},
            files=three_frames(),
        )
        assert resp.status_code == 403

    async def test_submit_rejects_inconsistent_frames(
        self, client: AsyncClient, an_enrollable_record, any_pose
    ):
        """Uch kadr bir xil odamniki bo'lishi shart. Aks holda birinchi
        kadrda bir odam, keyingisida boshqasi turib, o'rtacha vektor
        ikkalasiga ham tegishli bo'lmagan yuzni tasvirlab qolardi."""
        same = FACE_IMAGE_PATH.read_bytes()
        other = OTHER_FACE_IMAGE_PATH.read_bytes()
        resp = await client.post(
            f"/api/public/enrollment/{an_enrollable_record.id}/submit",
            data={"passportSeries": "AD", "passportNumber": "1234567"},
            files=[
                ("photos", ("a.jpg", same, "image/jpeg")),
                ("photos", ("b.png", other, "image/png")),
                ("photos", ("c.jpg", same, "image/jpeg")),
            ],
        )
        assert resp.status_code == 422

    async def test_submit_blocks_already_confirmed(
        self, client: AsyncClient, db_session: AsyncSession, an_enrollable_record
    ):
        an_enrollable_record.biometrics_status = "tasdiqlangan"
        await db_session.commit()

        resp = await client.post(
            f"/api/public/enrollment/{an_enrollable_record.id}/submit",
            data={"passportSeries": "AD", "passportNumber": "1234567"},
            files=three_frames(),
        )
        assert resp.status_code == 409

    async def test_a_single_photo_is_no_longer_accepted(
        self, client: AsyncClient, an_enrollable_record
    ):
        """Bir muddat bitta yuklangan rasm yetarli edi. U bekor qilindi:
        yuklangan rasmni boshqa odamning rasmi, telefon ekranidagi surat
        yoki qog'ozga bosilgan fotosurat bilan almashtirib bo'lardi.
        Endi kameradan uch burchak talab qilinadi."""
        resp = await client.post(
            f"/api/public/enrollment/{an_enrollable_record.id}/submit",
            data={"passportSeries": "AD", "passportNumber": "1234567"},
            files=[("photos", ("a.jpg", FACE_IMAGE_PATH.read_bytes(), "image/jpeg"))],
        )
        assert resp.status_code == 422
        assert "3 ta kadr" in resp.json()["detail"]

    async def test_a_photo_without_a_face_is_still_rejected(
        self, client: AsyncClient, an_enrollable_record
    ):
        """Bosqichning butun ma'nosi — bazaga YUZ tushishi."""
        blank = b"not an image at all"
        resp = await client.post(
            f"/api/public/enrollment/{an_enrollable_record.id}/submit",
            data={"passportSeries": "AD", "passportNumber": "1234567"},
            files=[
                ("photos", ("a.jpg", blank, "image/jpeg")),
                ("photos", ("b.jpg", blank, "image/jpeg")),
                ("photos", ("c.jpg", blank, "image/jpeg")),
            ],
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
