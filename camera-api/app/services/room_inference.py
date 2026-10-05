"""Kamera qaysi xonada — dars jadvali va tanilgan odamlardan xulosa.

MUAMMO (2026-09-25). 107 kameradan faqat 21 tasida xona raqami bor (qolganlari
"IPC-T280HA-LUF/SL (192.168.0.12)" kabi). HEMIS jadvalidagi 4520 darsdan
faqat 230 tasi kameraga bog'landi — qolgan darslarda dars davomati, diqqat va
"o'qituvchi keldimi" umuman ishlamaydi.

YECHIM. Kamera dars vaqtida kimni tanigan bo'lsa, o'sha odamning shu paytdagi
darsi qayerda ekani jadvalda bor:
  * talaba — guruhining darsi (group_or_position "2-kurs, DI-2301" -> "DI-2301");
  * o'qituvchi — o'zi o'tayotgan dars (lesson_sessions.teacher_id).
Har tanish o'sha dars xonasiga (bino raqami + xona raqami) "ovoz" beradi.
Kamera uchun eng ko'p TURLI ODAM ovoz bergan xona taklif qilinadi — agar u
yetarlicha odam (min_people), kamida ikki xil dars va ovozlarning ko'pchiligi
(min_share) bilan tasdiqlangan bo'lsa. Koridor kamerasi (turli xonalarga
boruvchilar o'tadi) ovozlari tarqoq bo'ladi va taklif chiqmaydi.

Taklif avtomatik YOZILMAYDI — admin tasdiqlaydi (noto'g'ri xona dars
mezonlarida soxta signallarga olib keladi).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Building, Camera, LessonSession, StudentStaff
from app.models.presence_visit import PresenceVisit
from app.services.camera_roles import normalize_room_code
from app.services.integrations.hemis_schedule import building_number, room_code
from app.timezone import INSTITUTE_TZ, local_now

# Dars boshlanishidan shuncha oldin kelgan odam ham shu darsga hisoblanadi.
EARLY = timedelta(minutes=10)


def group_of(group_or_position: str | None) -> str:
    """"2-kurs, DI-2301" -> "di-2301"; "DI-2301" -> "di-2301"."""
    text = (group_or_position or "").split(",")[-1]
    return " ".join(text.strip().lower().split())


@dataclass
class RoomVotes:
    people: set = field(default_factory=set)
    lessons: set = field(default_factory=set)
    building_name: str | None = None
    auditorium: str | None = None


@dataclass
class RoomSuggestion:
    camera_id: uuid.UUID
    camera_name: str
    current_room: str | None
    current_building: str | None
    room_code: str
    building_number: int
    hemis_building: str | None
    auditorium: str | None
    building_id: uuid.UUID | None
    people: int
    lessons: int
    share: float
    agrees: bool
    conflict_camera: str | None


def _key(lesson: LessonSession) -> tuple[int, str] | None:
    number, code = building_number(lesson.building), room_code(lesson.auditorium)
    if number is None or not code:
        return None
    return number, normalize_room_code(code) or code


def vote(
    visits: list[tuple[uuid.UUID, uuid.UUID, datetime, datetime, str, str | None]],
    lessons: list[LessonSession],
) -> dict[uuid.UUID, dict[tuple[int, str], RoomVotes]]:
    """Toza funksiya (sinovlanadi). visits: (odam, kamera, boshi, oxiri,
    turi, guruh/lavozim). Natija: kamera -> xona kaliti -> ovozlar."""
    by_group: dict[tuple[str, object], list[LessonSession]] = defaultdict(list)
    by_teacher: dict[tuple[uuid.UUID, object], list[LessonSession]] = defaultdict(list)
    for lesson in lessons:
        if lesson.scheduled_start_time is None or _key(lesson) is None:
            continue
        by_group[(group_of(lesson.group_name), lesson.date)].append(lesson)
        if lesson.teacher_id:
            by_teacher[(lesson.teacher_id, lesson.date)].append(lesson)

    out: dict[uuid.UUID, dict[tuple[int, str], RoomVotes]] = defaultdict(dict)
    for person_id, camera_id, first, last, kind, group in visits:
        day = first.astimezone(INSTITUTE_TZ).date()
        pool = by_teacher.get((person_id, day), []) if kind == "xodim" else by_group.get((group_of(group), day), [])
        hits = []
        for lesson in pool:
            start = lesson.scheduled_start_time
            end = lesson.scheduled_end_time or start + timedelta(minutes=80)
            if first <= end and last >= start - EARLY:
                hits.append(lesson)
        if len(hits) != 1:
            continue  # darsi yo'q yoki bir vaqtda bir nechta (noaniq)
        lesson = hits[0]
        key = _key(lesson)
        votes = out[camera_id].setdefault(key, RoomVotes(building_name=lesson.building, auditorium=lesson.auditorium))
        votes.people.add(person_id)
        votes.lessons.add(lesson.id)
    return out


async def suggest_rooms(
    db: AsyncSession, *, days: int = 14, min_people: int = 3, min_lessons: int = 2, min_share: float = 0.6
) -> list[RoomSuggestion]:
    since = local_now() - timedelta(days=days)
    lessons = list(
        (
            await db.execute(
                select(LessonSession).where(
                    LessonSession.date >= since.date(), LessonSession.scheduled_start_time.is_not(None)
                )
            )
        ).unique().scalars()
    )
    rows = (
        await db.execute(
            select(
                PresenceVisit.student_staff_id, PresenceVisit.camera_id, PresenceVisit.first_seen_at,
                PresenceVisit.last_seen_at, StudentStaff.type, StudentStaff.group_or_position,
            )
            .join(StudentStaff, StudentStaff.id == PresenceVisit.student_staff_id)
            .where(PresenceVisit.first_seen_at >= since, PresenceVisit.camera_id.is_not(None))
        )
    ).all()
    votes = vote([tuple(row) for row in rows], lessons)

    cameras = {
        camera.id: (camera, building_name)
        for camera, building_name in (
            await db.execute(select(Camera, Building.name).join(Building, Building.id == Camera.building_id, isouter=True))
        ).all()
    }
    buildings = {building_number(b.name): b for b in (await db.execute(select(Building))).scalars()}
    taken: dict[tuple[int, str], str] = {}
    for camera, building_name in cameras.values():
        number = building_number(building_name)
        code = normalize_room_code(camera.room_code) if camera.room_code else None
        if number is not None and code:
            taken.setdefault((number, code), camera.name)

    suggestions: list[RoomSuggestion] = []
    for camera_id, rooms in votes.items():
        if camera_id not in cameras:
            continue
        total = sum(len(v.people) for v in rooms.values())
        key, best = max(rooms.items(), key=lambda item: (len(item[1].people), len(item[1].lessons)))
        share = len(best.people) / total if total else 0.0
        if len(best.people) < min_people or len(best.lessons) < min_lessons or share < min_share:
            continue
        camera, building_name = cameras[camera_id]
        current_key = (building_number(building_name), normalize_room_code(camera.room_code) if camera.room_code else None)
        agrees = current_key == key
        owner = taken.get(key)
        suggestions.append(
            RoomSuggestion(
                camera_id=camera_id,
                camera_name=camera.name,
                current_room=camera.room_code,
                current_building=building_name,
                room_code=key[1],
                building_number=key[0],
                hemis_building=best.building_name,
                auditorium=best.auditorium,
                building_id=buildings[key[0]].id if key[0] in buildings else None,
                people=len(best.people),
                lessons=len(best.lessons),
                share=round(share, 2),
                agrees=agrees,
                conflict_camera=owner if owner and owner != camera.name and not agrees else None,
            )
        )
    suggestions.sort(key=lambda s: (s.agrees, -s.people))
    return suggestions
