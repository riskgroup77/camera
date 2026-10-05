"""Jadval bo'yicha kim qayerda bo'lishi kerak va kamera uni qayerda ko'rdi.

HEMIS dars jadvali (lesson_sessions) + kunlik davomat (attendance_records) +
kameradagi ko'rinishlar (presence_visits) bitta ko'rinishda:

  * o'qituvchi: "xonada" (dars kamerasida dars vaqtida ko'rindi), "binoda"
    (bugun kelgan, lekin dars xonasida ko'rinmadi yoki xonada kamera yo'q),
    "kelmagan" (bugun hech bir kamera ko'rmagan), None — o'qituvchi
    bog'lanmagan;
  * guruh: ro'yxatdagi faol talabalar, bugun binoga kelganlar va dars
    xonasida (kamerasi bo'lsa) ko'ringanlar.

"Kelmagan" — kamera KO'RMAGANI, kelmagani degani emas: yuzi bazada bo'lmasa
yoki kamera burchagi yomon bo'lsa, odam kelgan bo'lsa ham ko'rinmaydi.
Shuning uchun bu hisobot ota-onaga avtomatik yuborilmaydi.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from io import BytesIO

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AttendanceRecord, Camera, LessonSession, StudentStaff
from app.models.presence_visit import PresenceVisit
from app.services.room_inference import group_of
from app.timezone import INSTITUTE_TZ
from app.timezone import day_start

DEFAULT_LESSON = timedelta(minutes=80)
PRESENT = ("keldi", "kech_keldi")


@dataclass
class LessonPresence:
    id: uuid.UUID
    start: datetime | None
    end: datetime | None
    group: str
    subject: str
    faculty: str
    teacher: str
    teacher_id: uuid.UUID | None
    auditorium: str | None
    building: str | None
    camera_id: uuid.UUID | None
    camera_name: str | None
    teacher_status: str | None
    students_expected: int
    students_arrived: int
    students_in_room: int | None


def _end(lesson: LessonSession) -> datetime | None:
    if lesson.scheduled_end_time is not None:
        return lesson.scheduled_end_time
    return lesson.scheduled_start_time + DEFAULT_LESSON if lesson.scheduled_start_time else None


async def day_board(db: AsyncSession, day: date, *, at: datetime | None = None) -> list[LessonPresence]:
    """Kun darslari (at berilsa — faqat shu paytda davom etayotganlari)."""
    lessons = list(
        (
            await db.execute(
                select(LessonSession)
                .where(LessonSession.date == day)
                .order_by(LessonSession.scheduled_start_time.asc().nulls_last(), LessonSession.group_name)
            )
        ).unique().scalars()
    )
    if at is not None:
        lessons = [
            lesson for lesson in lessons
            if lesson.scheduled_start_time is not None and lesson.scheduled_start_time <= at <= (_end(lesson) or at)
        ]
    if not lessons:
        return []

    students = (
        await db.execute(
            select(StudentStaff.id, StudentStaff.group_or_position).where(
                StudentStaff.active.is_(True), StudentStaff.type == "talaba"
            )
        )
    ).all()
    members: dict[str, set[uuid.UUID]] = defaultdict(set)
    for person_id, group in students:
        members[group_of(group)].add(person_id)

    arrived = set(
        (
            await db.execute(
                select(AttendanceRecord.student_staff_id).where(
                    AttendanceRecord.date == day, AttendanceRecord.status.in_(PRESENT)
                )
            )
        ).scalars()
    )
    start_utc = day_start(day)
    end_utc = start_utc + timedelta(days=1)
    visits: dict[uuid.UUID, list[tuple[uuid.UUID, datetime, datetime]]] = defaultdict(list)
    seen_today: set[uuid.UUID] = set()
    for person_id, camera_id, first, last in (
        await db.execute(
            select(
                PresenceVisit.student_staff_id, PresenceVisit.camera_id, PresenceVisit.first_seen_at,
                PresenceVisit.last_seen_at,
            ).where(PresenceVisit.first_seen_at >= start_utc, PresenceVisit.first_seen_at < end_utc)
        )
    ).all():
        seen_today.add(person_id)
        if camera_id is not None:
            visits[camera_id].append((person_id, first, last))
    camera_names = {}
    camera_ids = {lesson.camera_id for lesson in lessons if lesson.camera_id}
    if camera_ids:
        camera_names = dict((await db.execute(select(Camera.id, Camera.name).where(Camera.id.in_(camera_ids)))).all())

    board: list[LessonPresence] = []
    for lesson in lessons:
        start, end = lesson.scheduled_start_time, _end(lesson)
        in_room: set[uuid.UUID] = set()
        if lesson.camera_id and start and end:
            for person_id, first, last in visits.get(lesson.camera_id, ()):
                if first <= end and last >= start - timedelta(minutes=10):
                    in_room.add(person_id)
        group = members.get(group_of(lesson.group_name), set())
        teacher_status = None
        if lesson.teacher_id:
            if lesson.teacher_id in in_room:
                teacher_status = "xonada"
            elif lesson.teacher_id in arrived or lesson.teacher_id in seen_today:
                teacher_status = "binoda"
            else:
                teacher_status = "kelmagan"
        board.append(
            LessonPresence(
                id=lesson.id,
                start=start,
                end=end,
                group=lesson.group_name,
                subject=lesson.subject,
                faculty=lesson.faculty,
                teacher=lesson.teacher,
                teacher_id=lesson.teacher_id,
                auditorium=lesson.auditorium,
                building=lesson.building,
                camera_id=lesson.camera_id,
                camera_name=camera_names.get(lesson.camera_id),
                teacher_status=teacher_status,
                students_expected=len(group),
                students_arrived=len(group & (arrived | seen_today)),
                students_in_room=len(group & in_room) if lesson.camera_id else None,
            )
        )
    return board


TEACHER_LABELS = {"xonada": "Xonada", "binoda": "Binoda (xonada ko'rinmadi)", "kelmagan": "Kamera ko'rmadi", None: "—"}


def board_workbook(day: date, board: list[LessonPresence]) -> bytes:
    from openpyxl import Workbook

    from app.services.report_export import _header, _widths

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Darslar"
    sheet.append([f"Jadval bo'yicha davomat — {day:%d.%m.%Y}"])
    sheet.append([
        "Kamera ko'rmagani kelmagani degani emas: yuzi bazada yo'q yoki kamera burchagi yomon bo'lsa, odam ko'rinmaydi."
    ])
    sheet.append([])
    _header(sheet, [
        "Boshlanish", "Tugash", "Guruh", "Fan", "O'qituvchi", "O'qituvchi holati", "Bino", "Xona", "Kamera",
        "Guruhda talaba", "Binoga kelgan", "Xonada ko'ringan",
    ])
    for row in board:
        sheet.append([
            row.start.astimezone(INSTITUTE_TZ).strftime("%H:%M") if row.start else "",
            row.end.astimezone(INSTITUTE_TZ).strftime("%H:%M") if row.end else "",
            row.group, row.subject, row.teacher, TEACHER_LABELS.get(row.teacher_status, "—"),
            row.building or "", row.auditorium or "", row.camera_name or "",
            row.students_expected, row.students_arrived,
            row.students_in_room if row.students_in_room is not None else "—",
        ])
    _widths(sheet, [11, 9, 14, 34, 28, 24, 24, 20, 22, 14, 14, 16])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
