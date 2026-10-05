"""O'qituvchilar (va istalgan odam) kuzatuvi hamda davomat kameralari holati.

Kunlik davomat (app/routers/attendance.py) "keldimi, soat nechida,
qachon ketdi" degan savolga javob beradi va dars jadvaliga bog'liq emas.
Bu yerdagi savol boshqa: "kun davomida QAYERDA, QACHON bo'lgan va bu
uning darsiga bog'liqmi". Ma'lumot — yuz tanishdan yig'ilgan tashriflar
(app/models/presence_visit.py); darsga bog'liqlik o'qilganda jadvaldan
hisoblanadi, shuning uchun jadval kiritilmagan kunlarda ham tashriflar
ko'rinadi ("jadvalda dars yo'q").
"""

import uuid
from collections import defaultdict
from datetime import date as date_type, datetime, time as time_type, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.jobs.camera_health import is_reachable, is_video_flowing
from app.models import AIModuleConfig, AttendanceRecord, Camera, LessonSession, PresenceVisit, StudentStaff
from app.schemas.presence import (
    AttendanceCameraOut,
    AttendanceCamerasOut,
    LessonLinkOut,
    PersonDayOut,
    ScheduledLessonOut,
    TeacherDaySummaryOut,
    VisitOut,
)
from app.services import runtime_snapshot
from app.services.access_scope import camera_column_filter, camera_filter
from app.services.camera_module_mapping import camera_allows_module_code
from app.services.camera_roles import role_allows
from app.services.staff_export import split_course
from app.timezone import INSTITUTE_TZ, local_now, to_local
from app.timezone import business_today, day_start

router = APIRouter(prefix="/api/presence", tags=["presence"])

# Kim qayerda va qachon bo'lgani — shaxsiy ma'lumot. Davomat sahifasi
# (kun oynasi) va hisobot (odam kartasi) ikkalasi ham shu yerdan o'qiydi.
ReadDep = Annotated[CurrentUser, Depends(require_permission("manageAttendance", "viewReports"))]

STAFF_ATTENDANCE_CODE = 6
STUDENT_ATTENDANCE_CODE = 7
_APOSTROPHES = "‘’`ʻʼ´"


def _parse_day(value: str | None) -> date_type:
    if not value:
        return business_today()
    try:
        return date_type.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "date 'YYYY-MM-DD' formatida bo'lishi kerak") from exc


def _day_bounds(day: date_type) -> tuple[datetime, datetime]:
    start = day_start(day)
    return start, start + timedelta(days=1)


def _hm(moment: datetime | None) -> str | None:
    return to_local(moment).strftime("%H:%M") if moment else None


def _hms(moment: datetime) -> str:
    return to_local(moment).strftime("%H:%M:%S")


def _camera_role(camera: Camera | None) -> str:
    if camera is None:
        return "Kamera o'chirilgan"
    if camera.is_entrance and camera.is_exit:
        return "Kirish/chiqish"
    if camera.is_entrance:
        return "Kirish"
    if camera.is_exit:
        return "Chiqish"
    return "Xona/koridor"


def _lesson_window(lesson: LessonSession) -> tuple[datetime, datetime]:
    start = lesson.scheduled_start_time
    return start, start + timedelta(minutes=settings.lesson_duration_minutes)


def _overlaps(visit: PresenceVisit, start: datetime, end: datetime) -> bool:
    return visit.first_seen_at <= end and visit.last_seen_at >= start


def _student_group(person: StudentStaff) -> str:
    _course, group = split_course(person.group_or_position)
    return group or person.group_or_position


def _is_own_lesson(person: StudentStaff, lesson: LessonSession) -> bool:
    if person.type == "talaba":
        return lesson.group_name == _student_group(person)
    return lesson.teacher_id == person.id


def _link(lesson: LessonSession, relation: str, label: str) -> LessonLinkOut:
    start, end = _lesson_window(lesson)
    return LessonLinkOut(
        relation=relation, label=label, subject=lesson.subject, group_name=lesson.group_name,
        teacher=lesson.teacher, starts_at=_hm(start), ends_at=_hm(end),
    )


def lesson_link(person: StudentStaff, visit: PresenceVisit, lessons: list[LessonSession]) -> LessonLinkOut:
    """Tashrif paytidagi darsga bog'liqlik:

    oz_darsi           — shu xonada, shu vaqtda o'z darsi (o'qituvchi yoki guruhi)
    boshqa_dars        — shu xonada shu vaqtda BOSHQA dars ketayotgan
    darsi_boshqa_joyda — shu vaqtda o'z darsi bor, lekin boshqa xonada
    darsdan_tashqari   — shu kunda darslar bor, lekin bu tashrif hech biriga to'g'ri kelmaydi
    jadval_yoq         — shu kun uchun dars jadvali kiritilmagan"""
    if not lessons:
        return LessonLinkOut(relation="jadval_yoq", label="Dars jadvali kiritilmagan")
    timed = [(lesson, *_lesson_window(lesson)) for lesson in lessons]
    here = [lesson for lesson, s, e in timed if lesson.camera_id == visit.camera_id and _overlaps(visit, s, e)]
    own_here = [lesson for lesson in here if _is_own_lesson(person, lesson)]
    if own_here:
        lesson = own_here[0]
        return _link(lesson, "oz_darsi", f"O'z darsi: {lesson.subject} ({lesson.group_name})")
    if here:
        lesson = here[0]
        return _link(lesson, "boshqa_dars", f"Boshqa dars: {lesson.subject}, {lesson.teacher}")
    elsewhere = [
        lesson for lesson, s, e in timed
        if _is_own_lesson(person, lesson) and lesson.camera_id != visit.camera_id and _overlaps(visit, s, e)
    ]
    if elsewhere:
        lesson = elsewhere[0]
        room = lesson.camera.name if lesson.camera else "boshqa xonada"
        return _link(lesson, "darsi_boshqa_joyda", f"Shu paytda darsi boshqa joyda: {lesson.subject} — {room}")
    return LessonLinkOut(relation="darsdan_tashqari", label="Darsdan tashqari")


def scheduled_lessons(person: StudentStaff, visits: list[PresenceVisit], lessons: list[LessonSession]) -> list[ScheduledLessonOut]:
    """Shu kunning o'z darslari — kirdimi, soat nechida, kechikdimi."""
    grace = timedelta(minutes=settings.attendance_late_to_lesson_grace_minutes)
    out: list[ScheduledLessonOut] = []
    for lesson in sorted((l for l in lessons if _is_own_lesson(person, l)), key=lambda l: l.scheduled_start_time):
        start, end = _lesson_window(lesson)
        in_room = [v for v in visits if lesson.camera_id and v.camera_id == lesson.camera_id and _overlaps(v, start, end)]
        arrived = min((v.first_seen_at for v in in_room), default=None)
        out.append(
            ScheduledLessonOut(
                subject=lesson.subject,
                group_name=lesson.group_name,
                starts_at=_hm(start),
                ends_at=_hm(end),
                camera=lesson.camera.name if lesson.camera else None,
                building=lesson.camera.building.name if lesson.camera and lesson.camera.building else None,
                attended=bool(in_room),
                arrived_at=_hm(arrived),
                late=bool(arrived and arrived > start + grace),
            )
        )
    return out


async def _lessons_on(db: AsyncSession, day: date_type) -> list[LessonSession]:
    rows = await db.execute(
        select(LessonSession)
        .where(LessonSession.date == day)
        .where(LessonSession.scheduled_start_time.is_not(None))
    )
    return list(rows.scalars().unique().all())


async def _visits_between(
    db: AsyncSession, start: datetime, end: datetime, person_ids=None, user: CurrentUser | None = None
) -> list[PresenceVisit]:
    stmt = (
        select(PresenceVisit)
        .where(PresenceVisit.first_seen_at < end)
        .where(PresenceVisit.last_seen_at >= start)
        # Bino doirasi — cheklangan foydalanuvchi boshqa binodagi kuzatuvni ko'rmaydi.
        .where(camera_column_filter(user, PresenceVisit.camera_id))
        .order_by(PresenceVisit.first_seen_at)
    )
    if person_ids is not None:
        stmt = stmt.where(PresenceVisit.student_staff_id.in_(list(person_ids)))
    return list((await db.execute(stmt)).scalars().unique().all())


def _visit_out(person: StudentStaff, visit: PresenceVisit, lessons: list[LessonSession]) -> VisitOut:
    camera = visit.camera
    return VisitOut(
        camera=camera.name if camera else "O'chirilgan kamera",
        building=camera.building.name if camera and camera.building else "—",
        zone=camera.zone if camera else "—",
        camera_role=_camera_role(camera),
        first_seen=_hms(visit.first_seen_at),
        last_seen=_hms(visit.last_seen_at),
        duration_minutes=max(0, round((visit.last_seen_at - visit.first_seen_at).total_seconds() / 60)),
        sightings=visit.sightings,
        lesson=lesson_link(person, visit, lessons),
    )


def _buildings(visits: list[PresenceVisit]) -> list[str]:
    names: list[str] = []
    for visit in visits:
        name = visit.camera.building.name if visit.camera and visit.camera.building else None
        if name and name not in names:
            names.append(name)
    return names


@router.get("/people/{person_id}/day", response_model=PersonDayOut)
async def person_day(
    person_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReadDep,
    date: Annotated[str | None, Query()] = None,
) -> PersonDayOut:
    """Bir odamning bir kuni: davomat, barcha tashriflari (qayerda, qachon)
    va har tashrifning darsga bog'liqligi, jadvaldagi darslariga kirgani."""
    try:
        person_uuid = uuid.UUID(person_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi") from None
    person = (
        await db.execute(select(StudentStaff).options(selectinload(StudentStaff.faculty)).where(StudentStaff.id == person_uuid))
    ).scalar_one_or_none()
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")

    day = _parse_day(date)
    start, end = _day_bounds(day)
    visits = await _visits_between(db, start, end, [person.id], current_user)
    lessons = await _lessons_on(db, day)
    record = (
        await db.execute(
            select(AttendanceRecord).where(AttendanceRecord.student_staff_id == person.id).where(AttendanceRecord.date == day)
        )
    ).scalar_one_or_none()

    return PersonDayOut(
        id=str(person.id),
        full_name=person.full_name,
        type=person.type,
        faculty=person.faculty.name if person.faculty else "Fakultetsiz",
        unit=person.group_or_position,
        date=day.isoformat(),
        attendance_status=record.status if record else None,
        check_in=record.check_in.strftime("%H:%M") if record and record.check_in else None,
        check_out=record.check_out.strftime("%H:%M") if record and record.check_out else None,
        first_seen=_hm(visits[0].first_seen_at) if visits else None,
        last_seen=_hm(max(v.last_seen_at for v in visits)) if visits else None,
        buildings=_buildings(visits),
        visits=[_visit_out(person, v, lessons) for v in visits],
        lessons=scheduled_lessons(person, visits, lessons),
    )


@router.get("/teachers", response_model=list[TeacherDaySummaryOut])
async def teachers_day(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReadDep,
    date: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> list[TeacherDaySummaryOut]:
    """Kun bo'yicha xodimlar: kameralar tanigan yoki shu kuni darsi bor
    har bir xodim — birinchi/oxirgi ko'rinish, binolar, darslarga kirgani."""
    day = _parse_day(date)
    start, end = _day_bounds(day)
    lessons = await _lessons_on(db, day)

    visit_rows = await db.execute(
        select(PresenceVisit.student_staff_id)
        .join(StudentStaff, StudentStaff.id == PresenceVisit.student_staff_id)
        .where(StudentStaff.type == "xodim")
        .where(PresenceVisit.first_seen_at < end)
        .where(PresenceVisit.last_seen_at >= start)
        .distinct()
    )
    ids = set(visit_rows.scalars().all()) | {l.teacher_id for l in lessons if l.teacher_id}
    if not ids:
        return []

    stmt = (
        select(StudentStaff)
        .options(selectinload(StudentStaff.faculty))
        .where(StudentStaff.id.in_(ids))
        .where(StudentStaff.type == "xodim")
    )
    text = search or ""
    for ch in _APOSTROPHES:
        text = text.replace(ch, "'")
    for word in text.split():
        stmt = stmt.where(StudentStaff.full_name.ilike(f"%{word}%"))
    people = list((await db.execute(stmt)).scalars().all())
    if not people:
        return []

    visits_by_person: dict = defaultdict(list)
    for visit in await _visits_between(db, start, end, [p.id for p in people], current_user):
        visits_by_person[visit.student_staff_id].append(visit)
    statuses = dict(
        (await db.execute(
            select(AttendanceRecord.student_staff_id, AttendanceRecord.status)
            .where(AttendanceRecord.date == day)
            .where(AttendanceRecord.student_staff_id.in_([p.id for p in people]))
        )).all()
    )

    out: list[TeacherDaySummaryOut] = []
    for person in people:
        visits = visits_by_person.get(person.id, [])
        own_lessons = scheduled_lessons(person, visits, lessons)
        out.append(
            TeacherDaySummaryOut(
                id=str(person.id),
                full_name=person.full_name,
                faculty=person.faculty.name if person.faculty else "Fakultetsiz",
                unit=person.group_or_position,
                attendance_status=statuses.get(person.id),
                first_seen=_hm(visits[0].first_seen_at) if visits else None,
                last_seen=_hm(max(v.last_seen_at for v in visits)) if visits else None,
                visits=len(visits),
                buildings=_buildings(visits),
                lessons_scheduled=len(own_lessons),
                lessons_attended=sum(1 for l in own_lessons if l.attended),
            )
        )
    return sorted(out, key=lambda t: (t.first_seen is None, t.first_seen or "", t.full_name))


PARTIAL_MIN_FACES = 50
PARTIAL_SMALL_SHARE = 0.6


def _partial_diagnosis(live) -> str | None:
    """Kamera kimnidir taniyapti, lekin ko'pchilik yuzni o'tkazib yubormoqda
    (production, 2026-09-24: yuzlarning 96% 40 px dan kichik). Bu ham
    tuzatiladigan holat — kamera o'rni yoki linza."""
    if live.faces < PARTIAL_MIN_FACES:
        return None
    share = live.small_faces / live.faces
    if share >= PARTIAL_SMALL_SHARE:
        median_px = live.face_px_median
        size = f", o'rtacha {median_px} px" if median_px else ""
        return (
            f"Yuzlarning {round(share * 100)}% tanish uchun juda kichik{size} — kamerani eshikka "
            "yaqinroq yoki yuz balandligiga (2-2.5 m) tushiring, yoki torroq burchakli linza qo'ying"
        )
    return None


def _diagnose(enabled: bool, online: bool, live, recognized: int, enrolled: int) -> str | None:
    """Kamera nima uchun hech kimni davomatga yozmayotganini oddiy tilda."""
    if not enabled:
        return None
    if enrolled == 0:
        return "Bazada yuzi saqlangan odam yo'q — tanish uchun namuna yo'q"
    if not online:
        return "Kamera tarmoqda emas"
    if live is None or live.frames == 0:
        return "Bugun hali tekshirilmadi (AI navbati yetib kelmagan yoki kadr olinmayapti)"
    if live.stream == "substream (zaxira)":
        # Tanish bo'lsa ham aytiladi: past sifatli oqimda yuzlar 3-6 barobar
        # kichik va ko'pchilik o'tganlar tanilmay qoladi.
        return (
            "Asosiy oqim kadr bermadi — vaqtincha past sifatli substream ishlatilmoqda "
            "(yuzlar kichik). Kameraning asosiy oqimini tekshiring"
        )
    if recognized > 0 or live.strict or live.relaxed_confirmed:
        return _partial_diagnosis(live)
    cycle = live.last_cycle_seconds or 0
    if cycle > 60:
        return (
            f"Kamera juda siyrak tekshirilyapti: bir aylanish {round(cycle)} s "
            f"(shundan kadr olish {round(live.last_grab_seconds or 0)} s) — server yuklamasi yuqori"
        )
    if live.faces == 0:
        return "Kadrlarda yuz topilmayapti — kamera burchagi/masofasi yuzni ko'rsatmaydi"
    median_px = live.face_px_median or 0
    if median_px and median_px < settings.attendance_min_face_px:
        return f"Yuzlar juda kichik (o'rtacha {median_px} px) — kamerani yaqinroq/pastroq o'rnating"
    near = live.buckets.get("0.47-0.55", 0) + live.buckets.get("0.40-0.47", 0)
    if near and live.relaxed_pending:
        return "Yuzlar chegaraga yaqin o'xshash, lekin ikkinchi ko'rinish bilan tasdiqlanmadi"
    if near:
        return "Yuzlar ko'rinmoqda, o'xshashlik chegaradan past — odamlar yuzini qayta (jonli) tasdiqlashi kerak"
    return "Yuzlar ko'rinmoqda, lekin ro'yxatdagi hech kimga o'xshamayapti (ro'yxatdan o'tmagan odamlar)"


@router.get("/cameras", response_model=AttendanceCamerasOut)
async def attendance_cameras(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ReadDep,
) -> AttendanceCamerasOut:
    """Qaysi kameralar davomatda ishlaydi va hozir haqiqatan ishlayaptimi."""
    modules = dict(
        (await db.execute(
            select(AIModuleConfig.code, AIModuleConfig.active)
            .where(AIModuleConfig.code.in_([STAFF_ATTENDANCE_CODE, STUDENT_ATTENDANCE_CODE]))
        )).all()
    )
    staff_active = bool(modules.get(STAFF_ATTENDANCE_CODE))
    student_active = bool(modules.get(STUDENT_ATTENDANCE_CODE))

    cameras = list((await db.execute(select(Camera).where(camera_filter(current_user)))).scalars().unique().all())
    today_start, _today_end = _day_bounds(business_today())
    stats = {
        camera_id: (people, last)
        for camera_id, people, last in (
            await db.execute(
                select(
                    PresenceVisit.camera_id,
                    func.count(func.distinct(PresenceVisit.student_staff_id)),
                    func.max(PresenceVisit.last_seen_at),
                )
                .where(PresenceVisit.last_seen_at >= today_start)
                .group_by(PresenceVisit.camera_id)
            )
        ).all()
    }
    people_today = await db.scalar(
        select(func.count(func.distinct(PresenceVisit.student_staff_id))).where(PresenceVisit.last_seen_at >= today_start)
    )

    enrolled = await db.scalar(
        select(func.count()).select_from(StudentStaff).where(StudentStaff.biometric_embedding.is_not(None))
    ) or 0

    # AI ishlayotgan (leader) jarayonning statistikasi — so'rov boshqa API
    # jarayoniga tushgan bo'lsa ham (app/services/runtime_snapshot.py).
    live_views = await runtime_snapshot.load_recognition_views()

    rows: list[AttendanceCameraOut] = []
    for camera in cameras:
        allows_staff = camera_allows_module_code(camera.excluded_module_codes, STAFF_ATTENDANCE_CODE)
        allows_student = camera_allows_module_code(camera.excluded_module_codes, STUDENT_ATTENDANCE_CODE)
        # Kelish istalgan kamerada birinchi ishonchli ko'rinishda yoziladi
        # (attendance_any_camera, app/jobs/unified_face_sweep.py); o'chirilgan
        # bo'lsa — faqat kirish kameralarida (app/services/camera_roles.py).
        at_door = settings.attendance_any_camera or role_allows(camera, STAFF_ATTENDANCE_CODE)
        enabled = (
            camera.status == "faol"
            and at_door
            and ((staff_active and allows_staff) or (student_active and allows_student))
        )
        if camera.status != "faol":
            reason = "Kamera faol emas"
        elif not staff_active and not student_active:
            reason = "Davomat modullari (#6, #7) o'chirilgan"
        elif not at_door:
            reason = "Kunlik davomat faqat kirish kameralarida — bu kamera darslarni jadval orqali tekshiradi"
        elif not (allows_staff or allows_student):
            reason = "Bu kamerada davomat moduli o'chirilgan"
        else:
            reason = None
        people, last = stats.get(camera.id, (0, None))
        security = camera.is_entrance or camera.is_exit or settings.attendance_all_cameras
        live = live_views.get(str(camera.id))
        rows.append(
            AttendanceCameraOut(
                id=str(camera.id),
                name=camera.name,
                building=camera.building.name if camera.building else "—",
                zone=camera.zone,
                role=_camera_role(camera),
                check_interval_seconds=(
                    settings.entrance_exit_attendance_interval_seconds if security else settings.unified_face_sweep_interval_seconds
                ) if enabled else None,
                attendance_enabled=enabled,
                disabled_reason=reason,
                online=is_reachable(camera.last_seen_at),
                # AI yuzi kichik kamerani kamdan-kam ochadi (face_blind) va
                # uning ffmpeg o'quvchisi yopiladi — bugun kadr olingan bo'lsa,
                # tasvir bor; "tasvirsiz" faqat umuman kadr bo'lmagan kamera.
                video=is_video_flowing(camera.last_frame_at) or bool(live and live.frames),
                recognized_today=people,
                last_recognition=_hm(last),
                frames_checked_today=live.frames if live else 0,
                faces_seen_today=live.faces if live else 0,
                face_px_median=live.face_px_median if live else None,
                small_faces_today=live.small_faces if live else 0,
                best_similarity_today=round(live.best_similarity, 3) if live and live.best_similarity >= 0 else None,
                similarity_buckets=dict(live.buckets) if live else {},
                strict_matches_today=live.strict if live else 0,
                relaxed_confirmed_today=live.relaxed_confirmed if live else 0,
                relaxed_pending_today=live.relaxed_pending if live else 0,
                last_checked=_hm(live.last_frame_at) if live else None,
                cycles_today=live.cycles if live else 0,
                last_cycle_seconds=live.last_cycle_seconds if live else None,
                last_grab_seconds=live.last_grab_seconds if live else None,
                stream_in_use=live.stream if live else None,
                diagnosis=_diagnose(enabled, is_reachable(camera.last_seen_at), live, people, enrolled),
            )
        )
    rows.sort(key=lambda r: (not r.attendance_enabled, r.role == "Xona/koridor", r.building, r.name))

    return AttendanceCamerasOut(
        staff_module_active=staff_active,
        student_module_active=student_active,
        total=len(rows),
        attendance_enabled=sum(1 for r in rows if r.attendance_enabled),
        entrance=sum(1 for c in cameras if c.is_entrance),
        exit=sum(1 for c in cameras if c.is_exit),
        online=sum(1 for r in rows if r.attendance_enabled and r.online),
        video=sum(1 for r in rows if r.attendance_enabled and r.video),
        recognizing_today=sum(1 for r in rows if r.recognized_today > 0),
        people_recognized_today=people_today or 0,
        enrolled_faces=enrolled,
        match_threshold=settings.attendance_ai_match_threshold,
        relaxed_threshold=(
            settings.attendance_ai_relaxed_threshold
            if 0 < settings.attendance_ai_relaxed_threshold < settings.attendance_ai_match_threshold
            else None
        ),
        cameras=rows,
    )
