"""Yuz tekshiruvi navbati ("kulrang zona") va o'lchangan aniqlik.

Ssenariy: ro'yxatdagi odamning CCTV kadri 0.42-0.50 o'xshashlikda qoladi —
davomat yozilmaydi, lekin navbatga tushadi; operator "Ha, u" desa davomat
yoziladi va yuz galereyaga qo'shiladi, "Yo'q" desa rad etiladi.
"""

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.jobs.attendance_ai import process_camera_frame
from app.models import AttendanceRecord, Camera, Event, FaceGalleryEmbedding, FaceReviewItem, StudentStaff, User
from app.security import hash_password
from app.services import face_review as svc
from app.services import recognition_stats
from app.services.face_matching import CandidateMatrix
from app.timezone import INSTITUTE_TZ
from tests.conftest import auth_headers

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 9, 24, 6, 0, tzinfo=timezone.utc)  # Toshkentda 11:00
DAY = date(2026, 9, 24)


def _axis(i: int) -> np.ndarray:
    v = np.zeros(512)
    v[i] = 1.0
    return v


def _face_vec(sim: float, second: float = 0.0) -> np.ndarray:
    """0-o'q (odam) bilan `sim`, 1-o'q (boshqa odam) bilan `second` kosinus."""
    rest = np.sqrt(max(0.0, 1 - sim**2 - second**2))
    return sim * _axis(0) + second * _axis(1) + rest * _axis(7)


def _face(vec, height=110):
    return SimpleNamespace(embedding=np.asarray(vec), bbox=np.array([100.0, 80.0, 190.0, 80.0 + height]))


def _frame() -> bytes:
    ok, buf = cv2.imencode(".jpg", np.full((480, 640, 3), 128, dtype=np.uint8))
    assert ok
    return buf.tobytes()


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    counter = {"n": 0}

    async def upload(_data):
        counter["n"] += 1
        return f"tekshiruv/test-{counter['n']}.jpg"

    monkeypatch.setattr(svc, "_upload_crop", upload)
    # Yumshoq moslik o'chiq: kulrang zona faqat navbatga borsin (aks holda
    # ikkinchi kadr uni davomatga o'zi yozadi — bu alohida testlangan).
    monkeypatch.setattr(settings, "attendance_ai_relaxed_threshold", 0.0)
    recognition_stats.reset_for_tests()
    yield counter
    recognition_stats.reset_for_tests()


@pytest.fixture
async def world(db_session, seeded):
    camera = Camera(name="Kirish-1", ip="10.9.0.1", zone="Kirish", resolution="1080p", status="faol", is_entrance=True)
    person = StudentStaff(
        full_name="Karimov Aziz", type="talaba", group_or_position="DI-2301",
        biometrics_status="tasdiqlangan", biometric_embedding=json.dumps(list(_axis(0))),
        biometric_photo_key="biometrika/aziz.jpg",
    )
    other = StudentStaff(
        full_name="Boshqa Odam", type="talaba", group_or_position="DI-2302",
        biometrics_status="tasdiqlangan", biometric_embedding=json.dumps(list(_axis(1))),
    )
    db_session.add_all([camera, person, other])
    await db_session.commit()
    candidates = CandidateMatrix(
        ids=[str(person.id), str(other.id)],
        matrix=np.array([_axis(0), _axis(1)]),
        person_types={str(person.id): "talaba", str(other.id): "talaba"},
    )
    return SimpleNamespace(camera=camera, person=person, other=other, candidates=candidates)


async def _run(db_session, world, face, at=NOW):
    return await process_camera_frame(
        _frame(), db_session, world.camera, occurred_at=at, candidates=world.candidates, faces=[face], allow_zoom=False
    )


async def _items(db_session):
    return (await db_session.execute(select(FaceReviewItem))).scalars().all()


# ─────────────────────────────────────────────── hook

async def test_grey_match_is_queued_once_and_merged(db_session, world):
    assert await _run(db_session, world, _face(_face_vec(0.45), height=60)) == []
    assert await _run(db_session, world, _face(_face_vec(0.47), height=120)) == []

    items = await _items(db_session)
    assert len(items) == 1
    item = items[0]
    assert item.person_id == world.person.id and item.day == DAY and item.status == "kutilmoqda"
    assert item.hits == 2
    # Yirikroq/o'xshashroq yuz rasmni almashtiradi.
    assert item.face_px == 120 and item.crop_key.endswith("2.jpg")
    assert item.similarity == pytest.approx(0.47, abs=1e-3)
    assert (await db_session.execute(select(AttendanceRecord))).scalars().all() == []


async def test_strict_match_is_not_queued(db_session, world):
    records = await _run(db_session, world, _face(_face_vec(0.7)))
    assert len(records) == 1
    assert await _items(db_session) == []


async def test_small_face_is_not_queued(db_session, world):
    await _run(db_session, world, _face(_face_vec(0.46), height=settings.attendance_min_face_px - 5))
    assert await _items(db_session) == []


async def test_too_low_or_ambiguous_is_not_queued(db_session, world):
    await _run(db_session, world, _face(_face_vec(0.35)))
    # 0.46 va 0.44 — ikki nomzod deyarli barobar, kimligi noaniq.
    await _run(db_session, world, _face(_face_vec(0.46, 0.44)))
    assert await _items(db_session) == []


async def test_person_already_present_today_is_skipped(db_session, world):
    db_session.add(AttendanceRecord(student_staff_id=world.person.id, date=DAY, status="keldi", source="turniket"))
    await db_session.commit()
    await _run(db_session, world, _face(_face_vec(0.46)))
    assert await _items(db_session) == []


async def test_daily_cap(db_session, world, monkeypatch):
    monkeypatch.setattr(settings, "face_review_daily_cap", 0)
    await _run(db_session, world, _face(_face_vec(0.46)))
    assert await _items(db_session) == []


# ─────────────────────────────────────────────── API

async def test_confirm_adds_gallery_and_attendance(client: AsyncClient, db_session, world):
    await _run(db_session, world, _face(_face_vec(0.46)))
    headers = await auth_headers(client, "admin", "admin123")

    listed = (await client.get("/api/tekshiruv?sana=2026-09-24", headers=headers)).json()
    assert listed["pending"] == 1
    entry = listed["items"][0]
    assert entry["personName"] == "Karimov Aziz" and entry["group"] == "DI-2301"
    assert entry["cameraName"] == "Kirish-1"
    assert entry["similarity"] == pytest.approx(0.46, abs=1e-3)

    res = await client.post(f"/api/tekshiruv/{entry['id']}/tasdiqlash", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "tasdiqlandi" and body["galleryAdded"] is True

    gallery = (await db_session.execute(select(FaceGalleryEmbedding))).scalars().all()
    assert len(gallery) == 1 and gallery[0].student_staff_id == world.person.id
    record = (await db_session.execute(select(AttendanceRecord))).scalar_one()
    assert record.student_staff_id == world.person.id and record.date == DAY
    assert record.check_in is not None and record.check_in.hour == NOW.astimezone(INSTITUTE_TZ).hour

    again = await client.post(f"/api/tekshiruv/{entry['id']}/tasdiqlash", headers=headers)
    assert again.status_code == 409
    listed = (await client.get("/api/tekshiruv?sana=2026-09-24", headers=headers)).json()
    assert listed["pending"] == 0 and listed["items"] == []


async def test_confirm_refuses_face_unlike_the_anchor(client: AsyncClient, db_session, world):
    await _run(db_session, world, _face(_face_vec(0.46)))
    item = (await _items(db_session))[0]
    # Asl rasm keyinroq almashtirilgan — endi bu yuzga umuman o'xshamaydi.
    world.person.biometric_embedding = json.dumps(list(_axis(9)))
    await db_session.commit()
    headers = await auth_headers(client, "admin", "admin123")
    res = await client.post(f"/api/tekshiruv/{item.id}/tasdiqlash", headers=headers)
    assert res.status_code == 409


async def test_reject(client: AsyncClient, db_session, world):
    await _run(db_session, world, _face(_face_vec(0.46)))
    item = (await _items(db_session))[0]
    headers = await auth_headers(client, "admin", "admin123")
    res = await client.post(f"/api/tekshiruv/{item.id}/rad", headers=headers)
    assert res.status_code == 200 and res.json()["status"] == "rad_etildi"
    assert (await db_session.execute(select(AttendanceRecord))).scalars().all() == []
    assert (await db_session.execute(select(FaceGalleryEmbedding))).scalars().all() == []
    # Rad etilgan odam shu kun qayta ko'rinsa — navbat qayta ochilmaydi.
    await _run(db_session, world, _face(_face_vec(0.46)))
    rows = await _items(db_session)
    assert len(rows) == 1 and rows[0].status == "rad_etildi" and rows[0].hits == 1


async def test_camera_steward_is_forbidden(client: AsyncClient, db_session, seeded):
    db_session.add(
        User(login="kamera1", password_hash=hash_password("kamera-parol-123"), full_name="Kamera Mas'uli",
             role="kamera-masuli")
    )
    await db_session.commit()
    headers = await auth_headers(client, "kamera1", "kamera-parol-123")
    assert (await client.get("/api/tekshiruv", headers=headers)).status_code == 403
    assert (await client.get("/api/tekshiruv/aniqlik", headers=headers)).status_code == 403


async def test_accuracy_metrics(client: AsyncClient, db_session, world, monkeypatch):
    from app.timezone import business_date

    monkeypatch.setattr("app.routers.face_review.business_today", lambda: business_date(NOW))

    def event(code, status, trial=False):
        return Event(camera_name="Kirish-1", building="A", module_code=code, module_name=f"Modul {code}",
                     group="A", confidence=80, severity="o'rta", status=status, is_trial=trial)

    db_session.add_all(
        [event(1, "tasdiqlangan"), event(1, "hal_qilindi"), event(1, "tasdiqlangan"), event(1, "rad_etilgan"),
         event(1, "yangi"), event(1, "rad_etilgan", trial=True), event(7, "rad_etilgan")]
    )
    db_session.add(StudentStaff(full_name="Yuzsiz Talaba", type="talaba", group_or_position="DI-2303"))
    db_session.add(AttendanceRecord(student_staff_id=world.person.id, date=DAY, status="keldi", source="kamera"))
    db_session.add_all(
        [
            FaceReviewItem(day=DAY, camera_id=world.camera.id, person_id=world.other.id, first_seen_at=NOW,
                           last_seen_at=NOW, similarity=0.45, embedding="[]", status="tasdiqlandi"),
            FaceReviewItem(day=DAY, camera_id=None, person_id=world.other.id, first_seen_at=NOW,
                           last_seen_at=NOW, similarity=0.44, embedding="[]", status="rad_etildi"),
        ]
    )
    await db_session.commit()
    headers = await auth_headers(client, "admin", "admin123")

    res = await client.get("/api/tekshiruv/aniqlik?kun=30", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    modules = {m["code"]: m for m in body["modules"]}
    # Sinov rejimidagi hodisa hisobga kirmaydi.
    assert modules[1]["confirmed"] == 3 and modules[1]["rejected"] == 1 and modules[1]["pending"] == 1
    assert modules[1]["precision"] == pytest.approx(0.75)
    assert modules[7]["precision"] == 0
    assert body["queue"]["confirmRate"] == pytest.approx(0.5)
    assert body["students"] == {"enrolled": 2, "total": 3, "ratio": pytest.approx(0.6667)}
    assert body["recognizedToday"] == 1
    assert body["enrolledTodayRatio"] == pytest.approx(0.5)
