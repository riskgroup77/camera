"""HEMIS dars jadvali (app/services/integrations/hemis_schedule.py) va rasmdan
tanitish (app/jobs/hemis_photos.py)."""

import json
import uuid
from datetime import date, datetime

import numpy as np
import pytest
from sqlalchemy import select

from app.config import settings
from app.jobs import hemis_photos
from app.models import Building, Camera, FaceGalleryEmbedding, LessonSession, StudentStaff
from app.services.integrations import hemis_schedule as hs
from app.timezone import INSTITUTE_TZ

pytestmark = pytest.mark.anyio


def test_building_and_room_are_read_from_hemis_names():
    assert hs.building_number("1-Oʻquv bino") == 1
    assert hs.building_number("4- Oʻquv binosi") == 4
    assert hs.building_number("2-Bino (Asosiy korpus)") == 2
    assert hs.building_number("Oq uy binosi") is None
    assert hs.room_code("212-xona Ma'ruza") == "212"
    assert hs.room_code("21S-xona") == "21s"
    assert hs.room_code("Multi-Med klinikasi") is None


def _epoch(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=INSTITUTE_TZ).timestamp())


def _item(lesson_id: int, day: date, room: str = "212-xona", building: str = "1-Oʻquv bino", teacher_id: int = 77):
    return {
        "id": lesson_id,
        "subject": {"id": 1, "name": "Anatomiya", "code": "A1"},
        "group": {"id": 5, "name": "101", "educationLang": {}},
        "faculty": {"id": 2, "name": "Davolash ishi"},
        "auditorium": {"code": 9, "name": room, "building": {"id": 3, "name": building}},
        "lessonPair": {"code": "11", "name": "1", "start_time": "08:00", "end_time": "09:20"},
        "employee": {"id": teacher_id, "name": "KARIMOV A. B."},
        "lesson_date": _epoch(day),
    }


async def _setup(db_session):
    building = Building(id=uuid.uuid4(), name="1-Bino (Asosiy korpus)")
    db_session.add(building)
    await db_session.commit()
    camera = Camera(id=uuid.uuid4(), name="212-xona", ip="10.1.0.9", zone="Z", resolution="1080p", status="faol",
                    building_id=building.id, room_code="212")
    teacher = StudentStaff(id=uuid.uuid4(), full_name="Karimov Anvar", type="xodim", group_or_position="Anatomiya",
                           hemis_id="E-555")
    ids = camera.id, teacher.id
    db_session.add_all([camera, teacher])
    await db_session.commit()
    return ids


def test_lesson_mapping_uses_institute_time():
    lesson = hs.map_lesson(_item(1, date(2026, 9, 28)))
    assert lesson.date == date(2026, 9, 28)
    assert lesson.start.astimezone(INSTITUTE_TZ).hour == 8 and lesson.end.astimezone(INSTITUTE_TZ).minute == 20
    assert lesson.group_name == "101" and lesson.teacher_hemis_id == "77"


async def test_schedule_links_camera_and_teacher_and_is_idempotent(db_session):
    camera_id, teacher_id = await _setup(db_session)
    first, last = date(2026, 9, 28), date(2026, 10, 5)
    items = [_item(1, date(2026, 9, 28)), _item(2, date(2026, 9, 29), room="213 (Oq uy)", building="Oq uy binosi")]
    stats = await hs.sync_schedule(db_session, items, {"77": "E-555"}, first=first, last=last)
    await db_session.commit()
    assert stats["created"] == 2 and stats["with_camera"] == 1 and stats["with_teacher"] == 2
    rows = {r.hemis_id: r for r in (await db_session.execute(select(LessonSession))).unique().scalars()}
    assert rows["1"].camera_id == camera_id and rows["1"].teacher_id == teacher_id
    assert rows["1"].auditorium == "212-xona" and rows["2"].camera_id is None

    again = await hs.sync_schedule(db_session, items, {"77": "E-555"}, first=first, last=last)
    assert again["created"] == 0 and again["unchanged"] == 2


async def test_future_lesson_removed_from_hemis_is_deleted(db_session, monkeypatch):
    await _setup(db_session)
    monkeypatch.setattr(hs, "local_now", lambda: datetime(2026, 9, 27, 9, 0, tzinfo=INSTITUTE_TZ))
    first, last = date(2026, 9, 27), date(2026, 10, 5)
    await hs.sync_schedule(db_session, [_item(1, date(2026, 9, 28)), _item(2, date(2026, 9, 29))], {}, first=first, last=last)
    await db_session.commit()
    stats = await hs.sync_schedule(db_session, [_item(1, date(2026, 9, 28))], {}, first=first, last=last)
    await db_session.commit()
    assert stats["deactivated"] == 1
    remaining = [r.hemis_id for r in (await db_session.execute(select(LessonSession))).unique().scalars()]
    assert remaining == ["1"]


# ── Rasmdan tanitish ─────────────────────────────────────────────────────────

def test_photo_host_must_be_the_hemis_domain(monkeypatch):
    monkeypatch.setattr(settings, "hemis_base_url", "https://student.fjsti.uz/rest")
    assert hemis_photos.allowed_photo_host("https://hemis.fjsti.uz/static/crop/a.jpg")
    assert not hemis_photos.allowed_photo_host("http://hemis.fjsti.uz/static/a.jpg")
    assert not hemis_photos.allowed_photo_host("https://evil.example/fjsti.uz.jpg")


def _vec(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=512)
    return v / np.linalg.norm(v)


async def test_person_without_a_face_is_enrolled_from_the_photo(db_session, seeded, monkeypatch):
    person_id = uuid.uuid4()
    db_session.add(StudentStaff(id=person_id, full_name="Rasmsiz Talaba", type="talaba", group_or_position="101"))
    await db_session.commit()

    async def fake_embed(data):
        return _vec(1), 120

    async def fake_upload(data):
        return "biometrika/hemis.jpg"

    monkeypatch.setattr(hemis_photos, "_embed_photo", fake_embed)
    monkeypatch.setattr(hemis_photos, "_upload", fake_upload)
    person = await db_session.get(StudentStaff, person_id)
    # Bitta HEMIS surati bilan yuz "tasdiqlangan" bo'lmaydi — 3 tomon shart.
    with pytest.raises(ValueError, match="3 tomondan"):
        await hemis_photos.enroll_person(db_session, person, b"jpg")


async def test_photo_of_someone_else_is_not_added_to_an_existing_face(db_session, seeded, monkeypatch):
    person_id = uuid.uuid4()
    db_session.add(StudentStaff(id=person_id, full_name="Yuzi Bor", type="talaba", group_or_position="101",
                                biometrics_status="tasdiqlangan", biometric_embedding=json.dumps(list(_vec(2)))))
    await db_session.commit()

    async def other_face(data):
        return _vec(3), 120

    monkeypatch.setattr(hemis_photos, "_embed_photo", other_face)
    person = await db_session.get(StudentStaff, person_id)
    with pytest.raises(ValueError):
        await hemis_photos.enroll_person(db_session, person, b"jpg")

    async def same_face(data):
        v = _vec(2) + np.random.default_rng(9).normal(scale=0.02, size=512)
        return v / np.linalg.norm(v), 120

    monkeypatch.setattr(hemis_photos, "_embed_photo", same_face)
    assert await hemis_photos.enroll_person(db_session, person, b"jpg") == "galereya"
    await db_session.commit()
    gallery = (await db_session.execute(select(FaceGalleryEmbedding).where(FaceGalleryEmbedding.student_staff_id == person_id))).scalars().all()
    assert len(gallery) == 1


async def test_portrait_filling_the_frame_is_retried_with_a_border(monkeypatch):
    """HEMIS portreti: yuz butun kadrni egallaydi — detektor faqat chegara
    qo'shilgandan keyin topadi."""
    import cv2

    image = np.full((200, 160, 3), 200, dtype=np.uint8)
    ok, buffer = cv2.imencode(".jpg", image)
    calls: list[tuple] = []

    class Face:
        def __init__(self):
            self.bbox = np.array([10.0, 10.0, 150.0, 190.0])
            self.embedding = np.ones(512) / np.sqrt(512)
            self.det_score = 0.8

    async def fake_detect(data, **kwargs):
        shape = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR).shape[:2]
        calls.append(shape)
        return [] if shape == (200, 160) else [Face()]

    monkeypatch.setattr(hemis_photos, "detect_faces", fake_detect)
    vector, height = await hemis_photos._embed_photo(buffer.tobytes())
    assert calls == [(200, 160), (400, 320)] and height == 180


def test_transient_download_errors_count_attempts_then_give_up():
    first = hemis_photos.transient_message(None, "504")
    assert first.endswith("[1]") and first.startswith(hemis_photos.TRANSIENT)
    second = hemis_photos.transient_message(first, "ReadTimeout")
    assert second.endswith("[2]")
    message = first
    for _ in range(hemis_photos.RETRY_LIMIT):
        message = hemis_photos.transient_message(message, "504")
    assert not message.startswith(hemis_photos.TRANSIENT)  # endi qayta urinilmaydi


async def test_full_size_portrait_is_analysed_at_640(monkeypatch):
    """993x1275 HEMIS portreti 1280 da emas, 640 da tahlil qilinadi (4 marta tezroq)."""
    import cv2

    ok, buffer = cv2.imencode(".jpg", np.full((1275, 993, 3), 200, dtype=np.uint8))
    shapes: list[tuple] = []

    async def fake_detect(data, **kwargs):
        shapes.append(cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR).shape[:2])
        return []

    monkeypatch.setattr(hemis_photos, "detect_faces", fake_detect)
    with pytest.raises(hemis_photos.NoFaceDetectedError):
        await hemis_photos._embed_photo(buffer.tobytes())
    assert shapes == [(640, 498), (640, 498)]
