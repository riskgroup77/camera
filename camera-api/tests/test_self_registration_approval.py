"""O'zini o'zi ro'yxatdan o'tkazganlar tasdiqlanguncha tanilmaydi.

Ilgari ochiq sahifada istalgan odam o'ziga yozuv yaratib, yuzini qo'shib,
darhol "tasdiqlangan" bo'lardi: kameralar uni tanish deb hisoblar,
"begona shaxs" tekshiruvi esa o'tkazib yuborardi. Endi institut
ro'yxatida bo'lmagan odamning yuzi administrator qaroriga qadar kutadi.

Yuz modeli va obyekt ombori bu yerda soxta: gap vektor sifatida emas,
kim tanish ro'yxatiga qachon kirishi haqida.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import AuditLog, StudentStaff
from app.routers import enrollment, students_staff
from app.services.face_matching import load_candidate_matrix
from tests.conftest import ENROLL_CODE, auth_headers

PINFL = "31234567890123"
FRAMES = [("photos", (f"{step}.jpg", b"jpeg", "image/jpeg")) for step in ("front", "left", "right")]


@pytest.fixture(autouse=True)
def fake_face_pipeline(monkeypatch, request):
    from app.config import settings

    # Qo'lda tasdiqlash rejimi (self_enrollment_auto_approve=False) testlari;
    # avtomatik rejim — TestAutoApprove.
    auto = request.cls in (TestAutoApprove, TestImpersonationOfAnImportedPerson)
    monkeypatch.setattr(settings, "self_enrollment_auto_approve", auto)
    async def no_liveness_check(frames):
        return None

    async def embedding(frames):
        return [0.1] * 512

    uploaded: list[str] = []

    def upload(data, filename, content_type, prefix):
        key = f"{prefix}/{len(uploaded)}-{filename}"
        uploaded.append(key)
        return str(len(uploaded)), key

    deleted: list[str] = []

    async def delete_quietly(keys):
        deleted.extend(k for k in keys if k)
        return len(deleted)

    monkeypatch.setattr(enrollment, "_verify_liveness", no_liveness_check)
    monkeypatch.setattr(enrollment, "extract_enrollment_embedding", embedding)
    monkeypatch.setattr(enrollment, "upload_file", upload)
    monkeypatch.setattr(enrollment, "delete_files_quietly", delete_quietly)
    monkeypatch.setattr(students_staff, "delete_files_quietly", delete_quietly)
    monkeypatch.setattr(students_staff, "presigned_url", lambda key: f"https://storage.test/{key}")
    return deleted


async def _register_and_submit(client: AsyncClient) -> dict:
    resp = await client.post(
        "/api/public/enrollment/register",
        json={"code": ENROLL_CODE, "fullName": "Begona Odam Aliyevich", "type": "talaba", "groupOrPosition": "1-kurs, DI-101", "pinfl": PINFL},
    )
    assert resp.status_code == 201, resp.text
    record_id = resp.json()["recordId"]
    resp = await client.post(f"/api/public/enrollment/{record_id}/submit", data={"code": ENROLL_CODE, "pinfl": PINFL, "consent": "true"}, files=FRAMES)
    assert resp.status_code == 200, resp.text
    return {"id": record_id, **resp.json()}


async def _known_ids(db_session) -> set[str]:
    return set((await load_candidate_matrix(db_session)).ids)


@pytest.mark.usefixtures("seeded")
class TestSelfRegisteredFaceWaits:
    async def test_the_face_is_kept_but_not_recognised(self, client: AsyncClient, db_session):
        result = await _register_and_submit(client)

        assert result["biometricsStatus"] == "kutilmoqda"
        assert result["awaitingApproval"] is True
        record = await db_session.get(StudentStaff, result["id"])
        assert record.self_registered is True
        assert record.biometric_embedding is not None
        assert record.biometrics_confirmed_at is None
        assert result["id"] not in await _known_ids(db_session)

    async def test_lookup_says_it_is_waiting_and_a_new_scan_is_allowed(self, client: AsyncClient):
        await _register_and_submit(client)

        resp = await client.post("/api/public/enrollment/lookup", json={"code": ENROLL_CODE, "pinfl": PINFL})
        assert resp.json()["alreadyEnrolled"] is False
        assert resp.json()["awaitingApproval"] is True
        record_id = resp.json()["recordId"]
        again = await client.post(f"/api/public/enrollment/{record_id}/submit", data={"code": ENROLL_CODE, "pinfl": PINFL, "consent": "true"}, files=FRAMES)
        assert again.status_code == 200
        assert again.json()["biometricsStatus"] == "kutilmoqda"

    async def test_people_from_the_institute_list_are_still_confirmed_at_once(self, client: AsyncClient, db_session):
        record = StudentStaff(full_name="Ro'yxatdagi Xodim", type="xodim", group_or_position="Kafedra",
                              pinfl="30000000000001")
        db_session.add(record)
        await db_session.commit()

        resp = await client.post(
            f"/api/public/enrollment/{record.id}/submit",
            data={"code": ENROLL_CODE, "pinfl": "30000000000001", "consent": "true"},
            files=FRAMES,
        )

        assert resp.json()["biometricsStatus"] == "tasdiqlangan"
        assert resp.json()["awaitingApproval"] is False
        assert str(record.id) in await _known_ids(db_session)


@pytest.mark.usefixtures("seeded")
class TestAdminDecides:
    async def test_the_page_counts_and_lists_who_is_waiting(self, client: AsyncClient):
        result = await _register_and_submit(client)
        headers = await auth_headers(client, "admin", "admin123")

        overview = (await client.get("/api/students-staff/overview", headers=headers)).json()
        assert overview["talaba"]["awaitingApproval"] == 1
        assert overview["xodim"]["awaitingApproval"] == 0

        resp = await client.post(
            "/api/students-staff/search",
            headers=headers,
            json={"type": "talaba", "biometricsStatus": "tasdiq_kutmoqda", "page": 1, "pageSize": 10},
        )
        items = resp.json()["items"]
        assert [(item["id"], item["awaitingApproval"], item["selfRegistered"]) for item in items] == [
            (result["id"], True, True)
        ]

    async def test_approval_makes_the_person_known(self, client: AsyncClient, db_session):
        result = await _register_and_submit(client)
        headers = await auth_headers(client, "admin", "admin123")

        resp = await client.post(f"/api/students-staff/{result['id']}/biometrics/approve", headers=headers)

        assert resp.status_code == 200, resp.text
        assert resp.json()["biometricsStatus"] == "tasdiqlangan"
        assert resp.json()["awaitingApproval"] is False
        assert result["id"] in await _known_ids(db_session)
        actions = (await db_session.execute(select(AuditLog.action))).scalars().all()
        assert any("tasdiqladi" in action and "Begona Odam" in action for action in actions)

        again = await client.post(f"/api/students-staff/{result['id']}/biometrics/approve", headers=headers)
        assert again.status_code == 409

    async def test_rejection_removes_the_face(self, client: AsyncClient, db_session, fake_face_pipeline):
        result = await _register_and_submit(client)
        headers = await auth_headers(client, "admin", "admin123")
        record = await db_session.get(StudentStaff, result["id"])
        photo_key = record.biometric_photo_key

        resp = await client.post(f"/api/students-staff/{result['id']}/biometrics/reject", headers=headers)

        assert resp.status_code == 200, resp.text
        assert resp.json()["biometricsStatus"] == "yoq"
        await db_session.refresh(record)
        assert record.biometric_embedding is None
        assert record.biometric_photo_key is None
        assert photo_key in fake_face_pipeline
        assert result["id"] not in await _known_ids(db_session)

    async def test_only_waiting_records_can_be_decided(self, client: AsyncClient, db_session):
        record = StudentStaff(full_name="Oddiy Xodim Karimov", type="xodim", group_or_position="Kafedra")
        db_session.add(record)
        await db_session.commit()
        headers = await auth_headers(client, "admin", "admin123")

        for decision in ("approve", "reject"):
            resp = await client.post(f"/api/students-staff/{record.id}/biometrics/{decision}", headers=headers)
            assert resp.status_code == 409

    async def test_a_decision_needs_a_login(self, client: AsyncClient):
        result = await _register_and_submit(client)
        resp = await client.post(f"/api/students-staff/{result['id']}/biometrics/approve")
        assert resp.status_code == 401


@pytest.mark.usefixtures("seeded")
class TestAutoApprove:
    async def test_a_self_registered_stranger_always_waits_for_an_admin(self, client: AsyncClient, db_session):
        # Avtomatik tasdiqlash yoqilgan bo'lsa ham: institut ro'yxatida yo'q
        # odamni hech kim tasdiqlamagan — u "begona shaxs" tekshiruvidan
        # o'zini o'zi chiqarib yubora olmasin.
        result = await _register_and_submit(client)
        assert result["biometricsStatus"] == "kutilmoqda"
        assert result["id"] not in await _known_ids(db_session)

    async def test_a_face_like_someone_already_known_waits_for_review(self, client: AsyncClient, db_session):
        import json

        db_session.add(StudentStaff(full_name="Tanish Odam", type="talaba", group_or_position="DI-101",
                                    biometrics_status="tasdiqlangan", biometric_embedding=json.dumps([0.1] * 512)))
        await db_session.commit()
        result = await _register_and_submit(client)
        assert result["biometricsStatus"] == "kutilmoqda"

    async def test_startup_approves_listed_people_except_duplicates(self, db_session):
        import json

        from app.services.self_enrollment import approve_pending

        a = StudentStaff(full_name="Kutuvchi Bir", type="talaba", group_or_position="DI-101", self_registered=False, biometrics_status="kutilmoqda", biometric_photo_key="a", biometric_photo_left_key="b", biometric_photo_right_key="c",
                         biometric_embedding=json.dumps([1.0] + [0.0] * 511))
        b = StudentStaff(full_name="Kutuvchi Ikki", type="talaba", group_or_position="DI-101", self_registered=False, biometrics_status="kutilmoqda", biometric_photo_key="a", biometric_photo_left_key="b", biometric_photo_right_key="c",
                         biometric_embedding=json.dumps([1.0, 0.01] + [0.0] * 510))
        c = StudentStaff(full_name="Kutuvchi Uch", type="talaba", group_or_position="DI-101", self_registered=False, biometrics_status="kutilmoqda", biometric_photo_key="a", biometric_photo_left_key="b", biometric_photo_right_key="c",
                         biometric_embedding=json.dumps([0.0, 1.0] + [0.0] * 510))
        stranger = StudentStaff(full_name="Begona Kutuvchi", type="talaba", group_or_position="DI-101", self_registered=True,
                                biometrics_status="kutilmoqda", biometric_embedding=json.dumps([0.0, 0.0, 1.0] + [0.0] * 509))
        db_session.add_all([a, b, c, stranger])
        await db_session.commit()
        approved, held = await approve_pending(db_session)
        assert (approved, held) == (2, 1)
        # O'zini o'zi qo'shgan odamga ishga tushishdagi tasdiqlash tegmaydi.
        assert stranger.biometrics_status == "kutilmoqda"
        # a va b — bitta yuz: bittasi tasdiqlanadi, takrori tekshiruvda qoladi.
        assert sorted([a.biometrics_status, b.biometrics_status]) == ["kutilmoqda", "tasdiqlangan"]
        assert c.biometrics_status == "tasdiqlangan"


@pytest.mark.usefixtures("seeded")
class TestImpersonationOfAnImportedPerson:
    """JSHSHIR sir emas: u bilan birovning yozuviga o'z yuzini bog'lab
    bo'lmaydi — yuz boshqa tanilgan odamnikiga o'xshasa, tekshiruvga qoladi."""

    async def test_a_face_that_belongs_to_someone_else_is_held(self, client: AsyncClient, db_session):
        import json

        victim = StudentStaff(full_name="Ro'yxatdagi Xodim", type="xodim", group_or_position="Assistent",
                              pinfl="51234567890123", biometrics_status="yoq")
        impostor_owner = StudentStaff(full_name="Begona Yuz Egasi", type="xodim", group_or_position="Assistent",
                                      biometrics_status="tasdiqlangan", biometric_embedding=json.dumps([0.1] * 512))
        db_session.add_all([victim, impostor_owner])
        await db_session.commit()

        resp = await client.post(
            f"/api/public/enrollment/{victim.id}/submit",
            data={"code": ENROLL_CODE, "pinfl": "51234567890123", "consent": "true"},
            files=FRAMES,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["biometricsStatus"] == "kutilmoqda"
        assert resp.json()["awaitingApproval"] is True
        assert str(victim.id) not in await _known_ids(db_session)

        # Ro'yxatdagi odam ham administrator navbatida: tasdiqlash ishlaydi
        # (ilgari faqat o'zi qo'shilganlar uchun edi — bu odam osilib qolardi).
        headers = await auth_headers(client, "admin", "admin123")
        listed = await client.post(
            "/api/students-staff/search", json={"biometricsStatus": "tasdiq_kutmoqda"}, headers=headers
        )
        assert [p["id"] for p in listed.json()["items"]] == [str(victim.id)]
        approved = await client.post(f"/api/students-staff/{victim.id}/biometrics/approve", headers=headers)
        assert approved.status_code == 200, approved.text
        assert approved.json()["biometricsStatus"] == "tasdiqlangan"

    async def test_an_ordinary_first_enrollment_still_works(self, client: AsyncClient, db_session):
        person = StudentStaff(full_name="Oddiy Xodim", type="xodim", group_or_position="Assistent",
                              pinfl="61234567890123", biometrics_status="yoq")
        db_session.add(person)
        await db_session.commit()
        resp = await client.post(
            f"/api/public/enrollment/{person.id}/submit",
            data={"code": ENROLL_CODE, "pinfl": "61234567890123", "consent": "true"},
            files=FRAMES,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["biometricsStatus"] == "tasdiqlangan"
        assert str(person.id) in await _known_ids(db_session)


@pytest.mark.usefixtures("seeded")
class TestRegistrationUsesHemisStructure:
    async def test_student_group_gets_course_prefix(self, client: AsyncClient, db_session):
        from app.models import Faculty, StudentGroup

        faculty = Faculty(name="Pediatriya fakulteti", course_count=6)
        db_session.add(faculty)
        await db_session.flush()
        db_session.add(StudentGroup(name="PE-2401", faculty_id=faculty.id, course=2))
        await db_session.commit()

        groups = (await client.get("/api/public/enrollment/groups")).json()
        assert {"name": "PE-2401", "course": 2, "facultyId": str(faculty.id)} in groups

        resp = await client.post(
            "/api/public/enrollment/register",
            json={"fullName": "Yangi Talaba Aliyevich", "type": "talaba", "groupOrPosition": "pe-2401", "pinfl": "41234567890123"},
        )
        assert resp.status_code == 201, resp.text
        record = await db_session.get(StudentStaff, resp.json()["recordId"])
        await db_session.refresh(record)
        assert record.group_or_position == "2-kurs, PE-2401"
        assert record.faculty_id == faculty.id

    async def test_staff_picks_org_unit(self, client: AsyncClient, db_session):
        from app.models import OrgUnit

        unit = OrgUnit(name="Anatomiya kafedrasi", kind="kafedra")
        db_session.add(unit)
        await db_session.commit()
        units = (await client.get("/api/public/enrollment/units")).json()
        assert any(u["id"] == str(unit.id) and u["kind"] == "kafedra" for u in units)

        resp = await client.post(
            "/api/public/enrollment/register",
            json={"fullName": "Yangi Xodim Karimovich", "type": "xodim", "groupOrPosition": "Assistent",
                  "orgUnitId": str(unit.id), "pinfl": "71234567890123"},
        )
        assert resp.status_code == 201, resp.text
        record = await db_session.get(StudentStaff, resp.json()["recordId"])
        await db_session.refresh(record)
        assert record.org_unit_id == unit.id
        assert record.position == "Assistent"


async def test_approve_all_confirms_only_three_angle_faces(client, db_session, seeded):
    from app.models import StudentStaff
    from tests.conftest import auth_headers

    full = StudentStaff(full_name="Uch Tomonli", type="talaba", group_or_position="DI-1", biometrics_status="kutilmoqda",
                        biometric_embedding="[1]", biometric_photo_key="a", biometric_photo_left_key="b",
                        biometric_photo_right_key="c")
    partial = StudentStaff(full_name="Bir Tomonli", type="talaba", group_or_position="DI-1",
                           biometrics_status="kutilmoqda", biometric_embedding="[1]", biometric_photo_key="a")
    db_session.add_all([full, partial])
    await db_session.commit()
    headers = await auth_headers(client, "admin", "admin123")
    res = await client.post("/api/students-staff/biometrics/approve-all?type=talaba", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json() == {"approved": 1, "skippedAngles": 1}
    await db_session.refresh(full)
    await db_session.refresh(partial)
    assert full.biometrics_status == "tasdiqlangan" and partial.biometrics_status == "kutilmoqda"
