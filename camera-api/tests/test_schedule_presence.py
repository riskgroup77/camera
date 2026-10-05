"""Jadval bo'yicha kim qayerda (app/services/schedule_presence.py, /api/jadval)
va o'qituvchi darsga kelmadi (app/jobs/teacher_absence.py)."""

import uuid
from datetime import date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.jobs import teacher_absence
from app.models import AttendanceRecord, Camera, LessonSession, StudentStaff
from app.models.presence_visit import PresenceVisit
from app.services.schedule_presence import board_workbook, day_board
from app.timezone import INSTITUTE_TZ
from tests.conftest import TestSessionLocal, auth_headers

pytestmark = pytest.mark.anyio

DAY = date(2026, 9, 28)


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=INSTITUTE_TZ)


async def _world(db_session):
    camera = Camera(id=uuid.uuid4(), name="5-xona", ip="10.5.0.5", zone="Z", resolution="1080p", status="faol")
    teacher = StudentStaff(id=uuid.uuid4(), full_name="Karimov Anvar", type="xodim", group_or_position="Kafedra",
                           biometrics_status="tasdiqlangan")
    absent_teacher = StudentStaff(id=uuid.uuid4(), full_name="Olimova Nigora", type="xodim", group_or_position="Kafedra",
                                  biometrics_status="tasdiqlangan")
    students = [StudentStaff(id=uuid.uuid4(), full_name=f"Talaba {i}", type="talaba", group_or_position="2-kurs, DI-2301")
                for i in range(3)]
    ids = {"camera": camera.id, "teacher": teacher.id, "absent": absent_teacher.id, "students": [s.id for s in students]}
    db_session.add_all([camera, teacher, absent_teacher, *students])
    await db_session.commit()
    with_camera = LessonSession(id=uuid.uuid4(), date=DAY, group_name="DI-2301", faculty="F", teacher="Karimov A.",
                                subject="Anatomiya", teacher_id=ids["teacher"], camera_id=ids["camera"],
                                scheduled_start_time=_at(8), scheduled_end_time=_at(9, 20), auditorium="5-xona",
                                building="3-Oʻquv bino")
    no_camera = LessonSession(id=uuid.uuid4(), date=DAY, group_name="DI-2301", faculty="F", teacher="Olimova N.",
                              subject="Lotin tili", teacher_id=ids["absent"], scheduled_start_time=_at(9, 30),
                              scheduled_end_time=_at(10, 50), auditorium="12-xona", building="3-Oʻquv bino")
    ids["lesson_camera"], ids["lesson_plain"] = with_camera.id, no_camera.id
    db_session.add_all([
        with_camera, no_camera,
        AttendanceRecord(student_staff_id=ids["students"][0], date=DAY, status="keldi"),
        AttendanceRecord(student_staff_id=ids["students"][1], date=DAY, status="kech_keldi"),
        PresenceVisit(student_staff_id=ids["teacher"], camera_id=ids["camera"], first_seen_at=_at(7, 58), last_seen_at=_at(9, 0)),
        PresenceVisit(student_staff_id=ids["students"][0], camera_id=ids["camera"], first_seen_at=_at(8, 5), last_seen_at=_at(8, 40)),
    ])
    await db_session.commit()
    return ids


async def test_board_shows_where_teacher_and_students_were(db_session):
    ids = await _world(db_session)
    board = {row.id: row for row in await day_board(db_session, DAY)}
    first = board[ids["lesson_camera"]]
    assert first.teacher_status == "xonada"
    assert (first.students_expected, first.students_arrived, first.students_in_room) == (3, 2, 1)
    second = board[ids["lesson_plain"]]
    assert second.teacher_status == "kelmagan" and second.students_in_room is None
    now_only = await day_board(db_session, DAY, at=_at(10, 0))
    assert [row.id for row in now_only] == [ids["lesson_plain"]]
    assert board_workbook(DAY, list(board.values()))[:2] == b"PK"  # xlsx


async def test_board_endpoint(client: AsyncClient, db_session, seeded):
    await _world(db_session)
    headers = await auth_headers(client, "admin", "admin123")
    res = await client.get(f"/api/jadval/kun?sana={DAY.isoformat()}", headers=headers)
    assert res.status_code == 200, res.text
    assert len(res.json()["items"]) == 2
    xlsx = await client.get(f"/api/jadval/kun.xlsx?sana={DAY.isoformat()}", headers=headers)
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    pdf = await client.get(f"/api/jadval/kun.pdf?sana={DAY.isoformat()}", headers=headers)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


async def test_teacher_not_seen_anywhere_is_flagged_once(db_session, monkeypatch):
    ids = await _world(db_session)
    monkeypatch.setattr(teacher_absence, "SessionLocal", TestSessionLocal)
    sent: list[str] = []

    async def fake_dispatch(db, kind, message, **kwargs):
        sent.append(message.lines[0][1])
        return []

    monkeypatch.setattr(teacher_absence.dispatcher, "_dispatch_rules", fake_dispatch)
    assert await teacher_absence.run_teacher_absence_once(now=_at(9, 45)) == 1
    assert sent == ["Olimova Nigora"]
    assert await teacher_absence.run_teacher_absence_once(now=_at(9, 50)) == 0  # bir marta
    db_session.expire_all()
    lesson = (await db_session.execute(select(LessonSession).where(LessonSession.id == ids["lesson_plain"]))).unique().scalar_one()
    assert lesson.teacher_on_time is False and lesson.punctuality_checked_at is not None


async def test_teacher_seen_in_the_building_is_not_flagged(db_session, monkeypatch):
    ids = await _world(db_session)
    db_session.add(PresenceVisit(student_staff_id=ids["absent"], camera_id=ids["camera"],
                                 first_seen_at=_at(9, 0), last_seen_at=_at(9, 5)))
    await db_session.commit()
    monkeypatch.setattr(teacher_absence, "SessionLocal", TestSessionLocal)

    async def fake_dispatch(*args, **kwargs):
        raise AssertionError("xabar yuborilmasligi kerak")

    monkeypatch.setattr(teacher_absence.dispatcher, "_dispatch_rules", fake_dispatch)
    assert await teacher_absence.run_teacher_absence_once(now=_at(9, 45)) == 0
