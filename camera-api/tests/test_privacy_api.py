"""Maxfiylik: rozilik, faolsizlantirish, biometrikani o'chirish, eksport.

Obyekt ombori soxta — gap MinIO haqida emas, bazada nima qolishi, kim
tanilishi va har bir amal audit jurnaliga tushishi haqida.
"""

import json
import uuid
from datetime import date, datetime, time, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.models import (
    AccessEvent,
    AttendanceRecord,
    AuditLog,
    Event,
    FaceGalleryEmbedding,
    LessonAttendance,
    LessonSession,
    PresenceVisit,
    StudentStaff,
    UnknownSighting,
)
from app.routers import enrollment
from app.services import privacy as privacy_service
from app.services.face_matching import load_candidate_matrix, load_candidate_matrix_cached
from tests.conftest import ENROLL_CODE, auth_headers

EMBEDDING = json.dumps([0.1] * 512)
FRAMES = [("photos", (f"{step}.jpg", b"jpeg", "image/jpeg")) for step in ("front", "left", "right")]


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch):
    """Ombor chaqiruvlari yoziladi, tarmoqqa chiqilmaydi."""
    deleted: list[str] = []

    async def delete_quietly(keys):
        collected = [k for k in keys if k]
        deleted.extend(collected)
        return len(collected)

    monkeypatch.setattr(privacy_service, "delete_files_quietly", delete_quietly)
    monkeypatch.setattr(privacy_service, "presigned_url", lambda key: f"https://storage.test/{key}")
    return deleted


@pytest.fixture
def fake_enrollment_pipeline(monkeypatch):
    async def no_liveness_check(frames):
        return None

    async def embedding(frames):
        return [0.2] * 512

    async def delete_quietly(keys):
        return 0

    monkeypatch.setattr(enrollment, "_verify_liveness", no_liveness_check)
    monkeypatch.setattr(enrollment, "extract_enrollment_embedding", embedding)
    monkeypatch.setattr(enrollment, "upload_file", lambda data, name, ctype, prefix: ("1", f"{prefix}/1-{name}"))
    monkeypatch.setattr(enrollment, "delete_files_quietly", delete_quietly)


async def _person(db_session, **overrides) -> StudentStaff:
    values = {
        "full_name": "Karimov Aziz",
        "type": "talaba",
        "group_or_position": "DI-101",
        "biometrics_status": "tasdiqlangan",
        "biometric_embedding": EMBEDDING,
        "biometric_photo_key": "biometrics/aziz.jpg",
    }
    values.update(overrides)
    person = StudentStaff(**values)
    db_session.add(person)
    await db_session.commit()
    await db_session.refresh(person)
    return person


async def _admin(client: AsyncClient) -> dict[str, str]:
    return await auth_headers(client, "admin", "admin123")


async def _audit_actions(db_session) -> list[str]:
    return list((await db_session.execute(select(AuditLog.action).where(AuditLog.module == "Maxfiylik"))).scalars())


@pytest.mark.usefixtures("seeded")
class TestConsentText:
    async def test_consent_text_is_public_and_names_the_controller(self, client: AsyncClient):
        resp = await client.get("/api/public/consent-text")
        assert resp.status_code == 200
        body = resp.json()
        assert body["version"] == settings.consent_version
        assert body["controller"] == settings.org_name
        assert body["required"] is settings.consent_required_for_enrollment
        text = " ".join(s["body"] for s in body["sections"])
        assert settings.org_name in text
        # Nima yig'ilishi, maqsad, muddat va huquqlar — matnda bo'lishi shart.
        assert "yuz" in text.lower()
        assert "davomat" in text.lower()
        assert f"{settings.biometric_retention_days_after_inactive} kun" in text
        assert "qaytarib olish" in text
        assert body["statement"]


@pytest.mark.usefixtures("seeded", "fake_enrollment_pipeline")
class TestEnrollmentConsent:
    async def test_submit_without_consent_is_rejected_before_any_processing(self, client: AsyncClient, db_session):
        person = await _person(
            db_session, pinfl="31234567890123", biometrics_status="yoq", biometric_embedding=None,
            biometric_photo_key=None,
        )
        resp = await client.post(f"/api/public/enrollment/{person.id}/submit", data={"code": ENROLL_CODE, "pinfl": person.pinfl}, files=FRAMES)
        assert resp.status_code == 422
        assert "rozilik" in resp.json()["detail"]
        await db_session.refresh(person)
        assert person.biometric_embedding is None
        assert person.consent_given_at is None

    async def test_submit_with_consent_records_it(self, client: AsyncClient, db_session):
        person = await _person(
            db_session, pinfl="31234567890123", biometrics_status="yoq", biometric_embedding=None,
            biometric_photo_key=None,
        )
        resp = await client.post(
            f"/api/public/enrollment/{person.id}/submit",
            data={"code": ENROLL_CODE, "pinfl": person.pinfl, "consent": "true"},
            files=FRAMES,
        )
        assert resp.status_code == 200, resp.text
        await db_session.refresh(person)
        assert person.biometric_embedding is not None
        assert person.consent_given_at is not None
        assert person.consent_version == settings.consent_version
        assert person.consent_source == "royxatdan_otish"
        # Uch tomonlama rasm ham saqlanadi: to'g'ri, chap, o'ng.
        assert person.biometric_photo_key == "biometrics/1-face.jpg"
        assert person.biometric_photo_left_key == "biometrics/1-face-left.jpg"
        assert person.biometric_photo_right_key == "biometrics/1-face-right.jpg"

    async def test_consent_can_be_made_optional(self, client: AsyncClient, db_session, monkeypatch):
        monkeypatch.setattr(settings, "consent_required_for_enrollment", False)
        person = await _person(
            db_session, pinfl="31234567890123", biometrics_status="yoq", biometric_embedding=None,
            biometric_photo_key=None,
        )
        resp = await client.post(f"/api/public/enrollment/{person.id}/submit", data={"code": ENROLL_CODE, "pinfl": person.pinfl}, files=FRAMES)
        assert resp.status_code == 200, resp.text
        await db_session.refresh(person)
        assert person.consent_given_at is None

    async def test_inactive_person_cannot_self_enroll(self, client: AsyncClient, db_session):
        person = await _person(
            db_session, pinfl="31234567890123", biometrics_status="yoq", biometric_embedding=None,
            biometric_photo_key=None, active=False, deactivated_at=datetime.now(timezone.utc),
        )
        resp = await client.post(
            f"/api/public/enrollment/{person.id}/submit",
            data={"code": ENROLL_CODE, "pinfl": person.pinfl, "consent": "true"},
            files=FRAMES,
        )
        assert resp.status_code == 403


@pytest.mark.usefixtures("seeded")
class TestAccess:
    async def test_requires_login(self, client: AsyncClient):
        assert (await client.get("/api/privacy/overview")).status_code == 401

    async def test_requires_manage_privacy(self, client: AsyncClient, db_session):
        person = await _person(db_session)
        headers = await auth_headers(client, "operator", "operator123")
        assert (await client.get("/api/privacy/overview", headers=headers)).status_code == 403
        assert (await client.get("/api/privacy/people", headers=headers)).status_code == 403
        resp = await client.post(f"/api/privacy/people/{person.id}/erase-biometrics", headers=headers)
        assert resp.status_code == 403
        await db_session.refresh(person)
        assert person.biometric_embedding is not None

    async def test_unknown_or_malformed_id_is_404(self, client: AsyncClient):
        headers = await _admin(client)
        assert (await client.post(f"/api/privacy/people/{uuid.uuid4()}/deactivate", headers=headers)).status_code == 404
        assert (await client.get("/api/privacy/people/not-a-uuid/export", headers=headers)).status_code == 404


@pytest.mark.usefixtures("seeded")
class TestOverviewAndList:
    async def test_overview_counts(self, client: AsyncClient, db_session):
        now = datetime.now(timezone.utc)
        await _person(db_session, full_name="A", consent_given_at=now, consent_version=settings.consent_version)
        await _person(db_session, full_name="B")  # biometrika bor, rozilik yo'q
        await _person(db_session, full_name="C", consent_given_at=now, consent_version="v0")  # eskirgan
        await _person(db_session, full_name="D", biometric_embedding=None, biometric_photo_key=None, biometrics_status="yoq")
        deactivated = now - timedelta(days=5)
        await _person(db_session, full_name="E", active=False, deactivated_at=deactivated)
        long_ago = now - timedelta(days=400)
        await _person(db_session, full_name="F", active=False, deactivated_at=long_ago)
        db_session.add(Event(
            camera_name="K", building="B", module_code=1, module_name="M", group="G", confidence=80,
            severity="past", status="yangi", snapshot_key="events/1.jpg",
        ))
        await db_session.commit()

        resp = await client.get("/api/privacy/overview", headers=await _admin(client))
        assert resp.status_code == 200
        body = resp.json()
        assert body["peopleTotal"] == 6
        assert body["peopleActive"] == 4
        assert body["peopleInactive"] == 2
        assert body["withBiometrics"] == 5
        assert body["biometricsWithoutConsent"] == 3  # B, E, F
        assert body["consentOutdated"] == 1
        assert body["inactiveWithBiometrics"] == 2
        assert body["biometricPurgeOverdue"] == 1
        expected = long_ago + timedelta(days=settings.biometric_retention_days_after_inactive)
        assert abs(datetime.fromisoformat(body["nextBiometricPurgeAt"]) - expected) < timedelta(seconds=5)
        assert body["snapshotCount"] == 1
        assert body["retention"]["biometricRetentionDaysAfterInactive"] == settings.biometric_retention_days_after_inactive
        assert body["retention"]["notificationLogRetentionDays"] == settings.notification_log_retention_days

    async def test_filters_and_search(self, client: AsyncClient, db_session):
        now = datetime.now(timezone.utc)
        await _person(db_session, full_name="Rozi Bor", consent_given_at=now, consent_version="v1")
        await _person(db_session, full_name="Rozi Yoq", pinfl="30303030303030")
        await _person(db_session, full_name="Faol Emas", active=False, deactivated_at=now)
        await _person(
            db_session, full_name="Yuzi Yoq", biometric_embedding=None, biometric_photo_key=None, biometrics_status="yoq"
        )
        headers = await _admin(client)

        async def names(query: str) -> list[str]:
            resp = await client.get(f"/api/privacy/people{query}", headers=headers)
            assert resp.status_code == 200, resp.text
            return [p["fullName"] for p in resp.json()["items"]]

        assert await names("") == ["Faol Emas", "Rozi Bor", "Rozi Yoq", "Yuzi Yoq"]
        assert await names("?filter=no_consent") == ["Faol Emas", "Rozi Yoq"]
        assert await names("?filter=inactive") == ["Faol Emas"]
        assert await names("?filter=with_biometrics") == ["Faol Emas", "Rozi Bor", "Rozi Yoq"]
        assert await names("?search=rozi") == ["Rozi Bor", "Rozi Yoq"]
        assert await names("?search=30303030") == ["Rozi Yoq"]
        assert (await client.get("/api/privacy/people?filter=boshqa", headers=headers)).status_code == 422

        # POST varianti — JSHSHIR URL'ga tushmaydi.
        resp = await client.post(
            "/api/privacy/people/search", json={"search": "30303030", "filter": "no_consent"}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        assert [p["fullName"] for p in resp.json()["items"]] == ["Rozi Yoq"]

        resp = await client.get("/api/privacy/people?filter=inactive", headers=headers)
        item = resp.json()["items"][0]
        assert item["active"] is False
        assert item["hasBiometrics"] is True
        assert item["biometricPurgeAt"] is not None


@pytest.mark.usefixtures("seeded")
class TestConsentManagement:
    async def test_record_paper_consent(self, client: AsyncClient, db_session):
        person = await _person(db_session)
        resp = await client.post(
            f"/api/privacy/people/{person.id}/consent",
            json={"source": "qogoz", "note": "Ariza №15"},
            headers=await _admin(client),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["consentSource"] == "qogoz"
        assert body["consentCurrent"] is True
        await db_session.refresh(person)
        assert person.consent_version == settings.consent_version
        actions = await _audit_actions(db_session)
        assert any("Ariza №15" in a and person.full_name in a for a in actions)

    async def test_unknown_consent_source_is_rejected(self, client: AsyncClient, db_session):
        person = await _person(db_session)
        resp = await client.post(
            f"/api/privacy/people/{person.id}/consent", json={"source": "hemis"}, headers=await _admin(client)
        )
        assert resp.status_code == 422

    async def test_withdrawing_consent_erases_biometrics_immediately(
        self, client: AsyncClient, db_session, fake_storage
    ):
        person = await _person(
            db_session, consent_given_at=datetime.now(timezone.utc), consent_version="v1", consent_source="qogoz"
        )
        resp = await client.delete(f"/api/privacy/people/{person.id}/consent", headers=await _admin(client))
        assert resp.status_code == 200, resp.text
        assert resp.json()["photoDeleted"] is True
        await db_session.refresh(person)
        assert person.consent_given_at is None
        assert person.consent_source is None
        assert person.biometric_embedding is None
        assert person.biometric_photo_key is None
        assert person.biometrics_status == "yoq"
        assert fake_storage == ["biometrics/aziz.jpg"]
        assert str(person.id) not in (await load_candidate_matrix(db_session)).ids


@pytest.mark.usefixtures("seeded")
class TestActivationAndRecognition:
    async def test_inactive_people_are_not_candidates(self, db_session):
        active = await _person(db_session, full_name="Faol")
        inactive = await _person(
            db_session, full_name="Faol emas", active=False, deactivated_at=datetime.now(timezone.utc)
        )
        ids = (await load_candidate_matrix(db_session)).ids
        assert str(active.id) in ids
        assert str(inactive.id) not in ids

    async def test_deactivation_refreshes_the_cached_roster(self, client: AsyncClient, db_session):
        person = await _person(db_session)
        assert str(person.id) in (await load_candidate_matrix_cached(db_session)).ids
        headers = await _admin(client)

        resp = await client.post(f"/api/privacy/people/{person.id}/deactivate", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["active"] is False
        assert resp.json()["biometricPurgeAt"] is not None
        await db_session.refresh(person)
        assert person.deactivated_at is not None
        assert str(person.id) not in (await load_candidate_matrix_cached(db_session)).ids

        resp = await client.post(f"/api/privacy/people/{person.id}/activate", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["active"] is True
        await db_session.refresh(person)
        assert person.deactivated_at is None
        assert str(person.id) in (await load_candidate_matrix_cached(db_session)).ids
        actions = await _audit_actions(db_session)
        assert any(a.startswith("Faolsizlantirildi") for a in actions)
        assert any(a.startswith("Qayta faollashtirildi") for a in actions)


@pytest.mark.usefixtures("seeded")
class TestErase:
    async def test_erase_biometrics(self, client: AsyncClient, db_session, fake_storage):
        person = await _person(
            db_session, biometrics_confirmed_at=datetime.now(timezone.utc),
            consent_given_at=datetime.now(timezone.utc), consent_version="v1", consent_source="admin",
        )
        assert str(person.id) in (await load_candidate_matrix_cached(db_session)).ids

        resp = await client.post(f"/api/privacy/people/{person.id}/erase-biometrics", headers=await _admin(client))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["photoDeleted"] is True
        assert body["person"]["hasBiometrics"] is False
        assert body["person"]["biometricsStatus"] == "yoq"

        await db_session.refresh(person)
        assert person.biometric_embedding is None
        assert person.biometric_photo_key is None
        assert person.biometrics_confirmed_at is None
        # Rozilik qaydi qoladi — faqat biometrika o'chiriladi.
        assert person.consent_given_at is not None
        assert fake_storage == ["biometrics/aziz.jpg"]
        assert str(person.id) not in (await load_candidate_matrix_cached(db_session)).ids
        assert any("Biometrik ma'lumotlar o'chirildi" in a for a in await _audit_actions(db_session))

    async def test_failed_photo_delete_still_erases_the_template(self, client: AsyncClient, db_session, monkeypatch):
        async def storage_down(keys):
            return 0

        monkeypatch.setattr(privacy_service, "delete_files_quietly", storage_down)
        person = await _person(db_session)
        resp = await client.post(f"/api/privacy/people/{person.id}/erase-biometrics", headers=await _admin(client))
        assert resp.status_code == 200
        assert resp.json()["photoDeleted"] is False
        await db_session.refresh(person)
        assert person.biometric_embedding is None


@pytest.mark.usefixtures("seeded")
class TestExport:
    async def test_export_contains_everything_held_about_the_person(self, client: AsyncClient, db_session):
        now = datetime.now(timezone.utc)
        person = await _person(
            db_session, pinfl="31234567890123", telegram_link_code="sirli-kod-123",
            parent_telegram_chat_id="987654", consent_given_at=now, consent_version="v1", consent_source="qogoz",
        )
        other = await _person(db_session, full_name="Boshqa Odam")
        lesson = LessonSession(
            date=date(2026, 9, 1), group_name="DI-101", faculty="Davolash", teacher="Olimov", subject="Anatomiya"
        )
        db_session.add(lesson)
        await db_session.flush()
        db_session.add_all([
            AttendanceRecord(
                student_staff_id=person.id, date=date(2026, 9, 1), status="keldi", check_in=time(8, 5), source="ai"
            ),
            AttendanceRecord(student_staff_id=other.id, date=date(2026, 9, 1), status="kelmadi"),
            LessonAttendance(lesson_session_id=lesson.id, student_staff_id=person.id, sightings=4, status="keldi"),
            PresenceVisit(
                student_staff_id=person.id, first_seen_at=now - timedelta(hours=1), last_seen_at=now, sightings=3,
                best_similarity=0.61234,
            ),
            Event(
                camera_name="Kirish", building="1-bino", module_code=4, module_name="Yuz", group="G", confidence=90,
                severity="past", status="yangi", person_name=person.full_name, snapshot_key="events/a.jpg",
            ),
            Event(
                camera_name="Kirish", building="1-bino", module_code=4, module_name="Yuz", group="G", confidence=90,
                severity="past", status="yangi", person_name="Boshqa Odam",
            ),
            AccessEvent(external_id="x1", occurred_at=now, student_staff_id=person.id, direction="kirish", granted=True),
        ])
        await db_session.commit()

        resp = await client.get(f"/api/privacy/people/{person.id}/export", headers=await _admin(client))
        assert resp.status_code == 200, resp.text
        assert "attachment" in resp.headers["content-disposition"]
        data = resp.json()

        assert data["controller"] == settings.org_name
        assert data["profile"]["fullName"] == "Karimov Aziz"
        assert data["profile"]["pinfl"] == "31234567890123"
        assert data["profile"]["parentTelegramLinked"] is True
        assert data["consent"]["source"] == "qogoz"
        assert data["biometrics"]["faceTemplateStored"] is True
        assert data["biometrics"]["photoUrl"] == "https://storage.test/biometrics/aziz.jpg"
        assert [a["status"] for a in data["attendance"]] == ["keldi"]
        assert data["attendance"][0]["checkIn"] == "08:05:00"
        assert data["lessonAttendance"][0]["subject"] == "Anatomiya"
        assert data["presenceVisits"][0]["sightings"] == 3
        assert [e["hasSnapshot"] for e in data["events"]] == [True]
        assert data["accessEvents"][0]["direction"] == "kirish"
        assert data["truncated"] == []

        raw = resp.text
        # Maxfiy kalitlar va yuz vektori eksportga chiqmaydi.
        assert "sirli-kod-123" not in raw
        assert "987654" not in raw
        assert "0.1, 0.1" not in raw and "0.1,0.1" not in raw

        assert any("eksport" in a and person.full_name in a for a in await _audit_actions(db_session))


async def _gallery_and_sighting(db_session, person, crop_key: str = "unknown/aziz-1.jpg") -> None:
    now = datetime.now(timezone.utc)
    db_session.add_all([
        FaceGalleryEmbedding(
            student_staff_id=person.id, embedding=EMBEDDING, anchor_hash="h" * 64, similarity=0.6, face_px=80
        ),
        FaceGalleryEmbedding(
            student_staff_id=person.id, embedding=EMBEDDING, anchor_hash="h" * 64, similarity=0.55, face_px=70
        ),
        UnknownSighting(
            day=now.date(), first_seen_at=now, last_seen_at=now, hits=2, embedding=EMBEDDING,
            crop_key=crop_key, face_px=60, status="talaba", person_id=person.id,
        ),
    ])
    await db_session.commit()


async def _count(db_session, model, column, value) -> int:
    return len((await db_session.execute(select(model).where(column == value))).scalars().all())


@pytest.mark.usefixtures("seeded")
class TestBiometricSamples:
    async def test_erase_removes_gallery_samples_and_linked_camera_crops(
        self, client: AsyncClient, db_session, fake_storage
    ):
        person = await _person(db_session)
        # Biriktirilgan kadr asosiy rasm ham bo'lgan holat — ikki marta o'chirilmasin.
        await _gallery_and_sighting(db_session, person, crop_key="biometrics/aziz.jpg")
        other = await _person(db_session, full_name="Boshqa Odam", biometric_photo_key="biometrics/b.jpg")
        await _gallery_and_sighting(db_session, other, crop_key="unknown/b.jpg")

        resp = await client.post(f"/api/privacy/people/{person.id}/erase-biometrics", headers=await _admin(client))
        assert resp.status_code == 200, resp.text
        assert resp.json()["photoDeleted"] is True
        assert fake_storage == ["biometrics/aziz.jpg"]
        gallery, sightings = FaceGalleryEmbedding, UnknownSighting
        assert await _count(db_session, gallery, gallery.student_staff_id, person.id) == 0
        assert await _count(db_session, sightings, sightings.person_id, person.id) == 0
        # Boshqa odamning namunalari tegilmaydi.
        assert await _count(db_session, gallery, gallery.student_staff_id, other.id) == 2
        assert await _count(db_session, sightings, sightings.person_id, other.id) == 1

    async def test_withdrawing_consent_also_removes_samples(self, client: AsyncClient, db_session, fake_storage):
        person = await _person(db_session, consent_given_at=datetime.now(timezone.utc), consent_version="v1")
        await _gallery_and_sighting(db_session, person)
        resp = await client.delete(f"/api/privacy/people/{person.id}/consent", headers=await _admin(client))
        assert resp.status_code == 200, resp.text
        assert sorted(fake_storage) == ["biometrics/aziz.jpg", "unknown/aziz-1.jpg"]
        gallery = FaceGalleryEmbedding
        assert await _count(db_session, gallery, gallery.student_staff_id, person.id) == 0

    async def test_partial_storage_failure_is_reported(self, client: AsyncClient, db_session, monkeypatch):
        async def one_of_two(keys):
            return 1

        monkeypatch.setattr(privacy_service, "delete_files_quietly", one_of_two)
        person = await _person(db_session)
        await _gallery_and_sighting(db_session, person)
        resp = await client.post(f"/api/privacy/people/{person.id}/erase-biometrics", headers=await _admin(client))
        assert resp.json()["photoDeleted"] is False

    async def test_biometrics_summary(self, client: AsyncClient, db_session):
        now = datetime.now(timezone.utc)
        person = await _person(db_session, biometrics_confirmed_at=now)
        await _gallery_and_sighting(db_session, person)
        db_session.add_all([
            PresenceVisit(
                student_staff_id=person.id, first_seen_at=now - timedelta(hours=2),
                last_seen_at=now - timedelta(hours=1), sightings=4,
            ),
            PresenceVisit(
                student_staff_id=person.id, first_seen_at=now - timedelta(days=1),
                last_seen_at=now - timedelta(days=1), sightings=2,
            ),
            # 30 kunlik oynadan tashqarida — sanoqqa kirmaydi.
            PresenceVisit(
                student_staff_id=person.id, first_seen_at=now - timedelta(days=90),
                last_seen_at=now - timedelta(days=90), sightings=9,
            ),
        ])
        await db_session.commit()

        resp = await client.get(f"/api/privacy/people/{person.id}/biometrics", headers=await _admin(client))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["person"]["id"] == str(person.id)
        assert body["photoUrl"] == "https://storage.test/biometrics/aziz.jpg"
        assert body["faceTemplateStored"] is True
        assert body["gallerySamples"] == 2
        assert body["linkedSightings"] == 1
        assert body["recentVisits"] == 2
        assert body["recentSightings"] == 6
        assert body["lastSeenAt"] is not None
        assert any("ko'rildi" in a for a in await _audit_actions(db_session))

    async def test_biometrics_summary_requires_login(self, client: AsyncClient, db_session):
        person = await _person(db_session)
        resp = await client.get(f"/api/privacy/people/{person.id}/biometrics")
        assert resp.status_code == 401

    async def test_overview_lists_video_retention(self, client: AsyncClient):
        resp = await client.get("/api/privacy/overview", headers=await _admin(client))
        retention = resp.json()["retention"]
        assert retention["recordingRetentionHours"] == settings.recording_retention_hours
        assert retention["eventClipRetentionDays"] == settings.event_clip_retention_days
