"""HEMIS dars jadvali -> lesson_sessions: qaysi guruh va qaysi o'qituvchi
qachon qaysi xonada bo'lishi kerak.

    GET {hemis_base_url}/v1/data/schedule-list?lesson_date_from=..&lesson_date_to=..
    -> subject, group, faculty, employee{id,name}, auditorium{code,name,building},
       lessonPair{start_time,end_time}, lesson_date (epoch)

NEGA KERAK. Dars mezonlari (#8, #19, #21, #22, #26), dars davomati va
"o'qituvchi darsga keldimi" jadvalsiz umuman ishlamaydi — 2026-09-25 da
tizimda 0 ta dars bor edi, HEMIS'da esa 13 823 ta.

MOSLASHTIRISH:
  * xona -> kamera: bino raqami + xona raqami. HEMIS "1-Oʻquv bino" / "212-xona"
    == tizimdagi "1-Bino (Asosiy korpus)" + Camera.room_code "212". Bir xil
    xona raqami turli binolarda takrorlanadi (fjsti: 15 dan ortiq bino), shuning
    uchun faqat xona raqami bo'yicha moslanmaydi. Topilmasa — dars kamerasiz
    saqlanadi (jadval va hisobotlar uchun baribir kerak).
  * o'qituvchi -> xodim: HEMIS employee.id -> employee_id_number (employee-list)
    -> StudentStaff.hemis_id; bo'lmasa — ism bo'yicha (yagona bo'lsa).
  * takror: lesson_sessions.hemis_id — qayta sinxronlashda o'zgargan dars
    yangilanadi, HEMIS'dan olib tashlangan kelajakdagi dars (davomati yo'q
    bo'lsa) o'chiriladi. Mezon natijalari (diqqat, uyqu, punktuallik)
    maydonlariga tegilmaydi.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import and_, delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Building, Camera, LessonSession, StudentStaff
from app.models.lesson_attendance import LessonAttendance
from app.services.camera_roles import normalize_room_code
from app.services.name_matching import name_key
from app.timezone import INSTITUTE_TZ, local_now

logger = logging.getLogger("app.integrations.hemis_schedule")

#: Shu maydonlardan biri o'zgarsa dars punktualligi qayta tekshiriladi.
RECHECK_ATTRS = frozenset({"date", "scheduled_start_time", "camera_id", "teacher_id"})

SCHEDULE_ENDPOINT = "schedule-list"

# "Oʻquv": ʻ (U+02BB) Unicode'da harf hisoblanadi — \W unga mos kelmaydi.
_BUILDING_NUMBER = re.compile(r"(\d+)\s*-?\s*(?:o.?quv\s*)?bino", re.IGNORECASE)
_ROOM_CODE = re.compile(r"^\s*(\d{1,4}[a-z]?)(?![0-9])", re.IGNORECASE)


def building_number(name: str | None) -> int | None:
    """"1-Oʻquv bino" / "4- Oʻquv binosi" / "2-Bino (Asosiy korpus)" -> raqam."""
    match = _BUILDING_NUMBER.search(name or "")
    return int(match.group(1)) if match else None


def room_code(name: str | None) -> str | None:
    """"212-xona Ma'ruza" -> "212", "21S-xona" -> "21s", "Multi-Med" -> None."""
    match = _ROOM_CODE.match(name or "")
    return match.group(1).lower() if match else None


def _ref(value: Any, key: str = "name") -> str:
    if isinstance(value, dict):
        return str(value.get(key) or "").strip()
    return ""


def _clock(value: str | None) -> time | None:
    try:
        hours, minutes = (int(part) for part in str(value or "").split(":")[:2])
        return time(hours, minutes)
    except (TypeError, ValueError):
        return None


@dataclass
class HemisLesson:
    hemis_id: str
    date: date
    start: datetime | None
    end: datetime | None
    group_name: str
    faculty: str
    subject: str
    teacher_name: str
    teacher_hemis_id: str | None
    auditorium: str | None
    building: str | None


def map_lesson(item: dict) -> HemisLesson | None:
    lesson_id = item.get("id")
    group = _ref(item.get("group"))
    raw_date = item.get("lesson_date")
    if lesson_id is None or not group or raw_date in (None, ""):
        return None
    try:
        day = datetime.fromtimestamp(int(raw_date), INSTITUTE_TZ).date()
    except (TypeError, ValueError, OverflowError):
        return None
    pair = item.get("lessonPair") if isinstance(item.get("lessonPair"), dict) else {}
    start_clock, end_clock = _clock(pair.get("start_time")), _clock(pair.get("end_time"))
    auditorium = item.get("auditorium") if isinstance(item.get("auditorium"), dict) else {}
    employee = item.get("employee") if isinstance(item.get("employee"), dict) else {}
    return HemisLesson(
        hemis_id=str(lesson_id),
        date=day,
        start=datetime.combine(day, start_clock, INSTITUTE_TZ) if start_clock else None,
        end=datetime.combine(day, end_clock, INSTITUTE_TZ) if end_clock else None,
        group_name=group,
        faculty=_ref(item.get("faculty")) or _ref(item.get("department")) or "—",
        subject=_ref(item.get("subject")) or "—",
        teacher_name=_ref(employee) or "—",
        teacher_hemis_id=str(employee.get("id")) if employee.get("id") is not None else None,
        auditorium=_ref(auditorium) or None,
        building=_ref(auditorium.get("building")) or None,
    )


async def camera_index(db: AsyncSession) -> dict[tuple[int, str], Camera]:
    """(bino raqami, xona kodi) -> kamera. Bir xonada bir nechta kamera bo'lsa
    — birinchisi (nomi bo'yicha); qolganlari keyin qo'shimcha sifatida kerak bo'lsa ham
    dars bitta kameraga bog'lanadi."""
    rows = (
        await db.execute(
            select(Camera, Building.name)
            .join(Building, Building.id == Camera.building_id, isouter=True)
            .where(Camera.room_code.is_not(None))
            .order_by(Camera.name)
        )
    ).all()
    index: dict[tuple[int, str], Camera] = {}
    for camera, building_name in rows:
        number = building_number(building_name)
        code = normalize_room_code(camera.room_code)
        if number is not None and code:
            index.setdefault((number, code), camera)
    return index


def lesson_camera(lesson: HemisLesson, index: dict[tuple[int, str], Camera]) -> Camera | None:
    number, code = building_number(lesson.building), room_code(lesson.auditorium)
    if number is None or not code:
        return None
    return index.get((number, normalize_room_code(code) or code))


async def teacher_index(db: AsyncSession, employee_numbers: dict[str, str]) -> tuple[dict, dict]:
    """(HEMIS employee.id -> xodim, ism kaliti -> [xodimlar])."""
    rows = (await db.execute(select(StudentStaff).where(StudentStaff.type == "xodim"))).scalars().all()
    by_hemis = {row.hemis_id: row for row in rows if row.hemis_id}
    by_internal = {
        internal: by_hemis[number] for internal, number in employee_numbers.items() if number in by_hemis
    }
    by_name: dict[str, list[StudentStaff]] = {}
    for row in rows:
        by_name.setdefault(name_key(row.full_name), []).append(row)
    return by_internal, by_name


def lesson_teacher(lesson: HemisLesson, by_internal: dict, by_name: dict) -> StudentStaff | None:
    if lesson.teacher_hemis_id and lesson.teacher_hemis_id in by_internal:
        return by_internal[lesson.teacher_hemis_id]
    candidates = by_name.get(name_key(lesson.teacher_name), [])
    return candidates[0] if len(candidates) == 1 else None


def schedule_window(today: date | None = None) -> tuple[date, date]:
    today = today or local_now().date()
    return (
        today - timedelta(days=max(0, settings.hemis_schedule_days_back)),
        today + timedelta(days=max(0, settings.hemis_schedule_days_ahead)),
    )


def _epoch(day: date) -> int:
    return int(datetime.combine(day, time(0, 0), INSTITUTE_TZ).timestamp())


async def fetch_lessons(client, first: date, last: date, on_page=None) -> list[dict]:
    """[first, last] kunlar (ikkalasi ham kiradi)."""
    params = {"lesson_date_from": _epoch(first), "lesson_date_to": _epoch(last + timedelta(days=1)) - 1}
    return await client.fetch_all(SCHEDULE_ENDPOINT, on_page=on_page, params=params)


async def sync_schedule(
    db: AsyncSession,
    items: list[dict],
    employee_numbers: dict[str, str],
    *,
    first: date,
    last: date,
) -> dict[str, int]:
    """HEMIS darslarini lesson_sessions ga yozadi. Commit — chaqiruvchida."""
    stats = {"fetched": len(items), "created": 0, "updated": 0, "unchanged": 0, "deactivated": 0, "skipped": 0,
             "errors": 0, "with_camera": 0, "with_teacher": 0}
    cameras = await camera_index(db)
    by_internal, by_name = await teacher_index(db, employee_numbers)
    lessons: dict[str, HemisLesson] = {}
    for item in items:
        lesson = map_lesson(item)
        if lesson is None or not (first <= lesson.date <= last):
            stats["skipped"] += 1
            continue
        lessons[lesson.hemis_id] = lesson

    existing = {
        row.hemis_id: row
        for row in (
            await db.execute(select(LessonSession).where(LessonSession.hemis_id.in_(list(lessons))))
        ).unique().scalars()
    } if lessons else {}

    for hemis_id, lesson in lessons.items():
        camera = lesson_camera(lesson, cameras)
        teacher = lesson_teacher(lesson, by_internal, by_name)
        stats["with_camera"] += camera is not None
        stats["with_teacher"] += teacher is not None
        values = {
            "date": lesson.date,
            "group_name": lesson.group_name[:300],
            "faculty": lesson.faculty[:300],
            "teacher": lesson.teacher_name[:300],
            "subject": lesson.subject[:300],
            "teacher_id": teacher.id if teacher else None,
            "camera_id": camera.id if camera else None,
            "scheduled_start_time": lesson.start,
            "scheduled_end_time": lesson.end,
            "auditorium": lesson.auditorium,
            "building": lesson.building,
        }
        row = existing.get(hemis_id)
        if row is None:
            db.add(LessonSession(hemis_id=hemis_id, **values))
            stats["created"] += 1
            continue
        changed_attrs = set()
        for attr, value in values.items():
            if getattr(row, attr) != value:
                setattr(row, attr, value)
                changed_attrs.add(attr)
        changed = bool(changed_attrs)
        if changed_attrs & RECHECK_ATTRS and row.punctuality_checked_at is not None:
            # Vaqt, xona yoki o'qituvchi o'zgargan — punktuallik qayta tekshirilsin.
            # Fan nomi yoki guruh matni o'zgarsa — yo'q: aks holda o'sha dars
            # uchun "kelmadi" xabari ikkinchi marta ketardi.
            row.punctuality_checked_at = None
        stats["updated" if changed else "unchanged"] += 1

    # HEMIS'dan olib tashlangan KELAJAKDAGI darslar (davomati yo'q) — o'chiriladi.
    today = local_now().date()
    upcoming = (
        await db.execute(
            select(func.count())
            .select_from(LessonSession)
            .where(
                LessonSession.hemis_id.is_not(None),
                LessonSession.date >= max(first, today),
                LessonSession.date <= last,
            )
        )
    ).scalar_one()
    fetched_upcoming = sum(1 for lesson in lessons.values() if max(first, today) <= lesson.date <= last)
    if upcoming >= 50 and fetched_upcoming < upcoming * 0.5:
        # HEMIS javobi chala kelgan bo'lishi mumkin (bo'sh sahifa, uzilish):
        # bir urinishda kelajakdagi jadvalning yarmidan ko'pini o'chirmaymiz.
        logger.warning(
            "schedule fetch looks partial — stale lessons not deleted",
            extra={"stored": upcoming, "fetched": fetched_upcoming},
        )
        stats["deactivated"] = 0
        return stats
    stale = (
        delete(LessonSession)
        .where(
            LessonSession.hemis_id.is_not(None),
            LessonSession.date >= max(first, today),
            LessonSession.date <= last,
            LessonSession.hemis_id.not_in(list(lessons) or [""]),
            ~exists().where(and_(LessonAttendance.lesson_session_id == LessonSession.id)),
        )
        .execution_options(synchronize_session=False)
    )
    result = await db.execute(stale)
    stats["deactivated"] = int(result.rowcount or 0)
    return stats


async def relink_cameras(db: AsyncSession, since: date | None = None) -> int:
    """Kameraga xona raqami yozilgach: bugungi va kelajakdagi HEMIS darslari
    darhol shu kameraga bog'lanadi (jadvalning navbatdagi yangilanishini
    kutmasdan). Qaytaradi: nechta dars bog'landi. Commit — chaqiruvchida."""
    since = since or local_now().date()
    cameras = await camera_index(db)
    changed = 0
    rows = (
        await db.execute(select(LessonSession).where(LessonSession.hemis_id.is_not(None), LessonSession.date >= since))
    ).unique().scalars()
    for row in rows:
        number, code = building_number(row.building), room_code(row.auditorium)
        camera = cameras.get((number, normalize_room_code(code) or code)) if number is not None and code else None
        camera_id = camera.id if camera else None
        if row.camera_id != camera_id:
            row.camera_id = camera_id
            changed += 1
    return changed
