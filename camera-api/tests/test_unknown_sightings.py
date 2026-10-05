"""Kunduzgi notanish yuzlar: yozish, birlashtirish va operator qarori.

Ssenariy: begona shaxs moduli kunduzi signal bermaydi (talabalarning
ko'pchiligining yuzi tizimda yo'q), notanish yuz ro'yxatga tushadi,
operator uni "talaba" / "begona" / "o'tkazish" qiladi.
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.models import Camera, Event, FaceGalleryEmbedding, StudentStaff, UnknownSighting
from app.services import unknown_sightings as svc
from tests.conftest import auth_headers

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 9, 24, 6, 0, tzinfo=timezone.utc)  # Toshkentda 11:00 — kunduz


def _vec(seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=512)
    return list(v / np.linalg.norm(v))


def _near(base: list[float], noise: float, seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    v = np.asarray(base) + rng.normal(scale=noise, size=512)
    return list(v / np.linalg.norm(v))


def _face(embedding, height=120):
    return SimpleNamespace(bbox=np.array([100.0, 80.0, 200.0, 80.0 + height]), embedding=np.asarray(embedding))


def _frame() -> bytes:
    image = np.full((480, 640, 3), 128, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", image)
    assert ok
    return buf.tobytes()


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch):
    """Haqiqiy MinIO yo'q — kesilgan rasm "saqlandi" deb hisoblanadi."""
    counter = {"n": 0}

    async def upload(_data):
        counter["n"] += 1
        return f"notanishlar/test-{counter['n']}.jpg"

    monkeypatch.setattr(svc, "_upload_crop", upload)
    return counter


@pytest.fixture
async def camera(db_session, seeded):
    cam = Camera(name="Hovli", ip="10.9.0.1", zone="Z", resolution="1080p", status="faol", is_perimeter=True)
    db_session.add(cam)
    await db_session.commit()
    return cam


async def test_same_face_merges_into_one_row(db_session, camera):
    base = _vec(1)
    await svc.record_unknown_faces(db_session, camera, _frame(), [_face(base)], now=NOW)
    await svc.record_unknown_faces(db_session, camera, _frame(), [_face(_near(base, 0.02, 2))], now=NOW)

    rows = (await db_session.execute(select(UnknownSighting))).scalars().all()
    # Bitta odam kun davomida ko'p kadrga tushadi — bitta qator bo'lishi shart.
    assert len(rows) == 1
    assert rows[0].hits == 2
    assert rows[0].status == "kutilmoqda"


async def test_different_faces_make_separate_rows(db_session, camera):
    created = await svc.record_unknown_faces(db_session, camera, _frame(), [_face(_vec(1)), _face(_vec(2))], now=NOW)
    assert created == 2
    assert len((await db_session.execute(select(UnknownSighting))).scalars().all()) == 2


async def test_bigger_face_replaces_the_picture(db_session, camera):
    base = _vec(3)
    await svc.record_unknown_faces(db_session, camera, _frame(), [_face(base, height=60)], now=NOW)
    await svc.record_unknown_faces(db_session, camera, _frame(), [_face(_near(base, 0.02, 4), height=150)], now=NOW)
    row = (await db_session.execute(select(UnknownSighting))).scalar_one()
    assert row.face_px == 150
    assert row.crop_key.endswith("2.jpg")


async def test_daily_cap_stops_new_rows(db_session, camera, monkeypatch):
    monkeypatch.setattr(settings, "unknown_daily_cap", 2)
    created = await svc.record_unknown_faces(
        db_session, camera, _frame(), [_face(_vec(10)), _face(_vec(11)), _face(_vec(12))], now=NOW
    )
    assert created == 2


async def _sighting(db_session, camera, embedding) -> UnknownSighting:
    await svc.record_unknown_faces(db_session, camera, _frame(), [_face(embedding)], now=NOW)
    return (await db_session.execute(select(UnknownSighting))).scalars().all()[-1]


async def test_assign_to_person_without_face_enrolls_them(db_session, camera):
    """Yuzi yo'q talaba — kamera rasmi uning asosiy yuzi bo'ladi (qamrov o'sadi)."""
    student = StudentStaff(full_name="Muhammadjonov Shoxruh", type="talaba", group_or_position="DI-2301")
    db_session.add(student)
    await db_session.commit()
    row = await _sighting(db_session, camera, _vec(20))

    # Yuzi yo'q odamga kamera kadridan yuz kiritilmaydi — faqat 3 tomonlama ro'yxatdan o'tish.
    with pytest.raises(svc.ResolveError, match="3 tomondan"):
        await svc.assign_to_person(db_session, row, student, None, can_enroll=True)
    assert row.status == "kutilmoqda"


async def test_assign_without_enroll_right_goes_to_review(db_session, camera):
    """Faqat hodisalarni ko'radigan operator istalgan yuzni istalgan odam
    nomiga "tasdiqlangan" qilib yoza olmasin — registrga tekshiruvga tushadi."""
    student = StudentStaff(full_name="Tekshiruv Talabasi", type="talaba", group_or_position="DI-2301")
    db_session.add(student)
    await db_session.commit()
    row = await _sighting(db_session, camera, _vec(21))

    with pytest.raises(svc.ResolveError):
        await svc.assign_to_person(db_session, row, student, None)
    await db_session.refresh(student)
    assert student.biometrics_status == "yoq"


async def test_inactive_person_gets_no_face(db_session, camera):
    student = StudentStaff(full_name="Ketgan Talaba", type="talaba", group_or_position="DI-2301", active=False)
    db_session.add(student)
    await db_session.commit()
    row = await _sighting(db_session, camera, _vec(22))
    with pytest.raises(svc.ResolveError):
        await svc.assign_to_person(db_session, row, student, None, can_enroll=True)


async def test_assign_to_person_with_face_adds_gallery_sample(db_session, camera):
    base = _vec(30)
    student = StudentStaff(
        full_name="Fozilov Muhriddin", type="talaba", group_or_position="DI-2302",
        biometrics_status="tasdiqlangan", biometric_embedding=json.dumps(base),
    )
    db_session.add(student)
    await db_session.commit()
    row = await _sighting(db_session, camera, _near(base, 0.03, 31))

    kind = await svc.assign_to_person(db_session, row, student, None)
    await db_session.commit()

    assert kind == "galereya"
    gallery = (await db_session.execute(select(FaceGalleryEmbedding))).scalars().all()
    assert len(gallery) == 1 and gallery[0].student_staff_id == student.id


async def test_wrong_person_is_refused(db_session, camera):
    """Operator adashib boshqa odamni tanlasa — begona yuz uning nomidan tanilib qolmasin."""
    student = StudentStaff(
        full_name="Aliyev Anvar", type="talaba", group_or_position="DI-2301",
        biometrics_status="tasdiqlangan", biometric_embedding=json.dumps(_vec(40)),
    )
    db_session.add(student)
    await db_session.commit()
    row = await _sighting(db_session, camera, _vec(41))  # umuman boshqa yuz

    with pytest.raises(svc.ResolveError, match="o'xshamaydi"):
        await svc.assign_to_person(db_session, row, student, None)
    assert row.status == "kutilmoqda"


async def test_lookalike_of_another_person_is_refused(db_session, camera):
    other_face = _vec(50)
    other = StudentStaff(
        full_name="Boshqa Odam", type="talaba", group_or_position="DI-2301",
        biometrics_status="tasdiqlangan", biometric_embedding=json.dumps(other_face),
    )
    chosen = StudentStaff(full_name="Tanlangan Odam", type="talaba", group_or_position="DI-2301")
    db_session.add_all([other, chosen])
    await db_session.commit()
    row = await _sighting(db_session, camera, _near(other_face, 0.02, 51))

    with pytest.raises(svc.ResolveError, match="Boshqa Odam"):
        await svc.assign_to_person(db_session, row, chosen, None)


async def test_resolved_row_cannot_be_resolved_again(db_session, camera):
    row = await _sighting(db_session, camera, _vec(60))
    svc.dismiss(row, None)
    with pytest.raises(svc.ResolveError, match="allaqachon"):
        svc.dismiss(row, None)


# ─────────────────────────────────────────────── API

async def test_api_list_and_resolve_flow(client: AsyncClient, db_session, camera, monkeypatch):
    from app.timezone import business_date

    monkeypatch.setattr("app.routers.unknown_sightings.business_today", lambda: business_date(NOW))
    await svc.record_unknown_faces(db_session, camera, _frame(), [_face(_vec(70)), _face(_vec(71))], now=NOW)
    student = StudentStaff(full_name="Muhammadjonov Shoxruh", type="talaba", group_or_position="DI-2301")
    db_session.add(student)
    await db_session.commit()
    headers = await auth_headers(client, "admin", "admin123")

    listed = (await client.get("/api/notanishlar?sana=2026-09-24", headers=headers)).json()
    assert listed["pending"] == 2 and len(listed["items"]) == 2
    first, second = listed["items"]

    res = await client.post(
        f"/api/notanishlar/{first['id']}/talaba", headers=headers, json={"personId": str(student.id)}
    )
    # Yuzi yo'q odamga kadrdan yuz kiritilmaydi (3 tomon shart) — 409, yozuv navbatda qoladi.
    assert res.status_code == 409, res.text

    res = await client.post(f"/api/notanishlar/{second['id']}/otkazish", headers=headers)
    assert res.status_code == 200

    after = (await client.get("/api/notanishlar?sana=2026-09-24", headers=headers)).json()
    assert after["pending"] == 1

    # Ikkinchi marta hal qilib bo'lmaydi.
    res = await client.post(f"/api/notanishlar/{second['id']}/otkazish", headers=headers)
    assert res.status_code == 409


async def test_api_stranger_raises_event(client: AsyncClient, db_session, camera, monkeypatch):
    async def no_read(_key):
        return None

    monkeypatch.setattr("app.storage.read_file", lambda _key: b"")
    await svc.record_unknown_faces(db_session, camera, _frame(), [_face(_vec(80))], now=NOW)
    row = (await db_session.execute(select(UnknownSighting))).scalar_one()
    headers = await auth_headers(client, "admin", "admin123")

    res = await client.post(f"/api/notanishlar/{row.id}/begona", headers=headers)
    assert res.status_code == 200, res.text

    events = (await db_session.execute(select(Event).where(Event.module_code == 1))).scalars().all()
    assert len(events) == 1
    assert "Operator tasdiqladi" in (events[0].details or {}).get("reason", "")


async def test_api_requires_review_permission(client: AsyncClient):
    res = await client.get("/api/notanishlar")
    assert res.status_code in (401, 403)


# ─────────────── Sinf kameralari: davomat skaneri topgan yuzlardan

class _Match:
    def __init__(self, person_id=None):
        self.person_id = person_id


class _Cands:
    is_empty = False

    def top_two(self, embeddings):
        return None, np.array([0.18] * len(embeddings)), np.zeros(len(embeddings))


async def _review(db_session, camera, monkeypatch, faces, matches, *, night=False, module_on=True, quality=True):
    from app.jobs import attendance_ai, module_status

    monkeypatch.setattr(module_status, "is_unauthorized_alert_time", lambda: night)
    monkeypatch.setattr(attendance_ai, "face_quality_ok", lambda face: quality)

    async def fake_active(db, code):
        return module_on

    monkeypatch.setattr(module_status, "is_module_active", fake_active)
    attendance_ai._review_module_cache.clear()
    await attendance_ai._review_unknown_faces(db_session, camera, _frame(), faces, matches, _Cands())
    return (await db_session.execute(select(UnknownSighting))).scalars().all()


async def test_classroom_unknown_face_goes_to_review(db_session, camera, monkeypatch):
    rows = await _review(db_session, camera, monkeypatch, [_face(_vec(90), height=80)], [_Match()])
    assert len(rows) == 1
    assert rows[0].closest_similarity == 0.18


async def test_recognised_face_is_not_listed(db_session, camera, monkeypatch):
    rows = await _review(db_session, camera, monkeypatch, [_face(_vec(91), height=80)], [_Match("someone")])
    assert rows == []


async def test_small_or_blurry_face_is_not_listed(db_session, camera, monkeypatch):
    """Operator mayda yoki pastga qaragan yuzni baribir taniy olmaydi."""
    assert await _review(db_session, camera, monkeypatch, [_face(_vec(92), height=20)], [_Match()]) == []
    assert await _review(db_session, camera, monkeypatch, [_face(_vec(93), height=80)], [_Match()], quality=False) == []


async def test_night_and_disabled_module_do_not_list(db_session, camera, monkeypatch):
    assert await _review(db_session, camera, monkeypatch, [_face(_vec(94), height=80)], [_Match()], night=True) == []
    assert await _review(db_session, camera, monkeypatch, [_face(_vec(95), height=80)], [_Match()], module_on=False) == []
