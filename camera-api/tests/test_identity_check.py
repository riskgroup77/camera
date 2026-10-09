"""Ro'yxatdan o'tgan yuz — AYNAN shu odammi (HEMIS surati bilan 1:1)."""

import json

import pytest

from app.config import settings
from app.models import StudentStaff
from app.services import identity_check, self_enrollment


@pytest.fixture(autouse=True)
def _identity_on(monkeypatch):
    monkeypatch.setattr(settings, "self_enrollment_identity_check", True)
    monkeypatch.setattr(settings, "self_enrollment_identity_threshold", 0.35)
    # Shaxs tekshiruvi HEMIS surati bilan — HEMIS ulangan bo'lishi kerak.
    monkeypatch.setattr(settings, "hemis_enabled", True)
    monkeypatch.setattr(settings, "hemis_base_url", "https://student.example.uz/rest")
    monkeypatch.setattr(settings, "hemis_api_token", "t")


def _person(**extra) -> StudentStaff:
    # Uch burchak (old, chap, o'ng) — tasdiqlash sharti.
    fields = {"biometrics_status": "yoq", "biometric_photo_key": "a", "biometric_photo_left_key": "b",
              "biometric_photo_right_key": "c", **extra}
    return StudentStaff(full_name="Ro'yxatdagi Talaba", type="talaba", group_or_position="1-kurs, X",
                        hemis_photo_url="https://student.example.uz/p.jpg", **fields)


async def _decide(db_session, person, monkeypatch, result):
    async def fake(_person, _embedding):
        return result

    monkeypatch.setattr(identity_check, "hemis_similarity", fake)
    db_session.add(person)
    await db_session.commit()
    return await self_enrollment.decide_status(db_session, person, [0.1] * 512)


async def test_matching_hemis_photo_is_approved(db_session, monkeypatch):
    assert await _decide(db_session, _person(), monkeypatch, (0.62, None)) == ("tasdiqlangan", None)


async def test_someone_elses_face_waits_for_an_admin(db_session, monkeypatch):
    status, reason = await _decide(db_session, _person(), monkeypatch, (0.12, None))
    assert status == "kutilmoqda" and "mos kelmadi" in reason


async def test_hemis_disconnected_skips_the_photo_check(db_session, monkeypatch):
    """HEMIS uzilgan (2026-10-09): surat olinmaydi — tekshiruv hammani
    "kutilmoqda"ga tushirmasin."""
    monkeypatch.setattr(settings, "hemis_enabled", False)
    assert await _decide(db_session, _person(), monkeypatch, (None, "HEMIS'da surati yo'q")) == ("tasdiqlangan", None)


async def test_unverifiable_identity_waits_for_an_admin(db_session, monkeypatch):
    status, reason = await _decide(db_session, _person(), monkeypatch, (None, "HEMIS'da surati yo'q"))
    assert status == "kutilmoqda" and "surati yo'q" in reason


async def test_startup_does_not_bypass_the_identity_check(db_session):
    held = _person(biometrics_status="kutilmoqda", biometric_embedding=json.dumps([1.0] + [0.0] * 511))
    db_session.add(held)
    await db_session.commit()
    assert await self_enrollment.approve_pending(db_session) == (0, 0)
    assert held.biometrics_status == "kutilmoqda"


async def test_photo_host_must_be_hemis(monkeypatch):
    monkeypatch.setattr(settings, "hemis_base_url", "https://student.fjsti.uz")
    person = StudentStaff(full_name="X Y", type="talaba", group_or_position="Z",
                          hemis_photo_url="https://evil.example.com/p.jpg")
    assert await identity_check.hemis_similarity(person, [0.1] * 512) == (None, "HEMIS surati manzili HEMIS domenidan emas")
    person.hemis_photo_url = None
    assert (await identity_check.hemis_similarity(person, [0.1] * 512))[0] is None
