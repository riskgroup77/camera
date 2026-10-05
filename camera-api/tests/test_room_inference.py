"""Kamera -> xona takliflari (app/services/room_inference.py, /api/xona-takliflari)."""

import uuid
from datetime import date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Building, Camera, LessonSession
from app.services.room_inference import group_of, vote
from app.timezone import INSTITUTE_TZ
from tests.conftest import auth_headers

pytestmark = pytest.mark.anyio

DAY = date(2026, 9, 28)


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=INSTITUTE_TZ)


def _lesson(group: str, room: str, hour: int, teacher=None, building="3-Oʻquv bino"):
    return LessonSession(
        id=uuid.uuid4(), date=DAY, group_name=group, faculty="F", teacher="T", subject="S", teacher_id=teacher,
        scheduled_start_time=_at(hour), scheduled_end_time=_at(hour) + timedelta(minutes=80),
        auditorium=room, building=building,
    )


def test_group_is_read_from_group_or_position():
    assert group_of("2-kurs, DI-2301") == "di-2301"
    assert group_of("DI-2301") == "di-2301"


def test_students_seen_during_their_lesson_vote_for_its_room():
    camera = uuid.uuid4()
    teacher = uuid.uuid4()
    lessons = [_lesson("DI-2301", "5-xona", 8, teacher=teacher), _lesson("DI-2301", "7-xona", 10)]
    visits = [
        (uuid.uuid4(), camera, _at(8, 5), _at(8, 30), "talaba", "2-kurs, DI-2301"),
        (uuid.uuid4(), camera, _at(8, 7), _at(8, 40), "talaba", "2-kurs, DI-2301"),
        (teacher, camera, _at(7, 55), _at(9, 0), "xodim", "Anatomiya"),
        (uuid.uuid4(), camera, _at(12, 0), _at(12, 5), "talaba", "2-kurs, DI-2301"),  # darsdan tashqari
    ]
    rooms = vote(visits, lessons)[camera]
    assert list(rooms) == [(3, "5")]
    assert len(rooms[(3, "5")].people) == 3


async def test_suggestion_is_applied_and_lessons_are_relinked(client: AsyncClient, db_session, seeded, monkeypatch):
    from app.services import room_inference

    building = Building(id=uuid.uuid4(), name="3-Bino (Asosiy korpus)")
    db_session.add(building)
    await db_session.commit()
    camera = Camera(id=uuid.uuid4(), name="IPC (192.168.0.12)", ip="10.3.0.12", zone="Z", resolution="1080p",
                    status="faol", building_id=building.id)
    lesson = LessonSession(id=uuid.uuid4(), date=date.today() + timedelta(days=1), group_name="101", faculty="F",
                           teacher="T", subject="S", hemis_id="H1", auditorium="5-xona", building="3-Oʻquv bino",
                           scheduled_start_time=datetime.now(INSTITUTE_TZ) + timedelta(days=1))
    camera_id, lesson_id = camera.id, lesson.id
    db_session.add_all([camera, lesson])
    await db_session.commit()
    monkeypatch.setattr(room_inference, "local_now", lambda: datetime.now(INSTITUTE_TZ))
    headers = await auth_headers(client, "admin", "admin123")

    res = await client.post(f"/api/xona-takliflari/{camera_id}/qollash", headers=headers, json={"roomCode": "5-xona"})
    assert res.status_code == 200, res.text
    assert res.json()["relinkedLessons"] == 1
    db_session.expire_all()
    stored = await db_session.get(Camera, camera_id)
    assert stored.room_code == "5"
    linked = (await db_session.execute(select(LessonSession.camera_id).where(LessonSession.id == lesson_id))).scalar_one()
    assert linked == camera_id


async def test_listing_requires_camera_permission(client: AsyncClient):
    assert (await client.get("/api/xona-takliflari")).status_code in (401, 403)
