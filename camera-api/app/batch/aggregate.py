"""Kun tahlili tugagach: kuzatuvlardan kriteriyalar va ularni bazaga yozish.

Qoidalar — app/batch/rules.py (sof funksiyalar). Bu yerda faqat o'qish va
yozish. Natijalar MAVJUD jadvallarga ham yoziladi, shuning uchun davomat,
darslar, hisobotlar va odam kartasi sahifalari o'zgarishsiz ishlaydi:

  * attendance_records   — kunlik kelish/ketish (#6, #7);
  * presence_visits      — kamera bo'yicha tashriflar (odam yo'li, erta ketish dalili);
  * lesson_attendance    — dars davomati, kechikish, erta ketish, diqqat (#7, #8, #9, #19);
  * lesson_sessions      — darsning diqqat balli, o'qituvchi faolligi va kelishi (#19, #21, #22);
  * events               — chekish (#15), xalat buzilishi (#10), o'qituvchi kechikishi (#22);
  * daily_person_criteria — har odam × kun: hamma kriteriyalar bitta qatorda.

Kunni qayta hisoblash idempotent: o'sha kunning video natijalari
o'chiriladi va qaytadan yoziladi; qo'lda kiritilgan (qolda) va turniket
yozuvlari saqlanadi.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, time as time_type, timedelta, timezone

from sqlalchemy import and_, delete, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.batch import coat as coat_rules
from app.batch import holatlar
from app.batch.planner import KIND_ENTRANCE, KIND_LESSON, Clip
from app.batch.rules import (
    DayAttendance,
    JobInfo,
    arrival_coverage,
    LessonInfo,
    Obs,
    coat_votes,
    day_attendance,
    group_by_person,
    lesson_result,
    presence_visits,
    smoking_incidents,
)
from app.config import settings
from app.models import (
    AIModuleConfig,
    AttendanceRecord,
    Camera,
    DailyPersonCriteria,
    Event,
    LessonAttendance,
    LessonSession,
    PresenceVisit,
    StudentStaff,
    VideoAnalysisJob,
    VideoAnalysisRun,
    VideoObservation,
)
from app.services.attendance_policy import load_policy
from app.services.camera_roles import is_door_camera
from app.services.event_bus import VIDEO_ANALYSIS_SOURCE, create_analysis_event
from app.timezone import INSTITUTE_TZ, day_bounds, to_local

logger = logging.getLogger("app.batch.aggregate")

PUNCTUALITY_CODE = 22
COAT_CODE = 10
SMOKING_CODE = 15
ATTENDANCE_CODES = (6, 7)
LESSON_LATE_CODE = 8
EARLY_LEAVE_CODE = 9
ATTENTION_CODE = 19
ACTIVITY_CODE = 21


def _finding(code: int, kind: str, camera_id: str | None, at: datetime | None, reason: str) -> dict | None:
    """Bitta aniqlangan holat — DailyPersonCriteria.details["dalillar"] elementi.
    Video klip (klip) keyin kesiladi: app/batch/evidence.py."""
    if at is None:
        return None
    return {"kod": code, "tur": kind, "sabab": reason, "kamera_id": camera_id, "vaqt": at.isoformat(), "klip": None}


def _hhmm(moment: datetime | None) -> str:
    return to_local(moment).strftime("%H:%M") if moment else "—"


def _job_info(job: VideoAnalysisJob) -> JobInfo:
    covered = {int(item[0]) for item in (job.covered or []) if item and int(item[1] or 0) > 0}
    return JobInfo(
        id=str(job.id),
        camera_id=str(job.camera_id) if job.camera_id else None,
        kind=job.kind,
        clips=[Clip.from_json(raw) for raw in job.clips],
        covered=covered,
        lesson_id=str(job.lesson_session_id) if job.lesson_session_id else None,
        faces=job.faces,
        result=job.result,
    )


def _obs(row: VideoObservation) -> Obs:
    return Obs(
        person_id=str(row.student_staff_id),
        camera_id=str(row.camera_id) if row.camera_id else None,
        job_id=str(row.job_id),
        clip_index=row.clip_index,
        seen_at=row.seen_at,
        last_seen_at=row.last_seen_at,
        similarity=row.similarity,
        margin=row.margin,
        frames=row.frames,
        frontal_frames=row.frontal_frames,
        phone_frames=row.phone_frames,
        coat_frames=row.coat_frames,
        coat_white_frames=row.coat_white_frames,
        movement=row.movement,
        evidence_key=row.evidence_key,
    )


async def _group_roster(db: AsyncSession, group_name: str, day_end: datetime) -> list[str]:
    from app.jobs.lesson_attendance import group_member_clause

    rows = (
        await db.execute(
            select(StudentStaff.id).where(
                StudentStaff.type == "talaba",
                StudentStaff.active.is_(True),
                StudentStaff.biometrics_status == "tasdiqlangan",
                or_(StudentStaff.biometrics_confirmed_at.is_(None), StudentStaff.biometrics_confirmed_at < day_end),
                group_member_clause(group_name),
            )
        )
    ).scalars().all()
    return [str(pid) for pid in rows]


async def _write_attendance(
    db: AsyncSession, person_id: str, day, attendance: DayAttendance, existing: AttendanceRecord | None, policy, person_type
) -> None:
    if existing is not None and existing.source == "qolda":
        return  # qo'lda tuzatilgan — tegilmaydi
    if existing is None:
        db.add(
            AttendanceRecord(
                student_staff_id=uuid.UUID(person_id),
                date=day,
                status=attendance.status,
                check_in=attendance.check_in,
                check_out=attendance.check_out,
                source="kamera",
            )
        )
        return
    if existing.status == "kelmadi" or existing.source in (None, "kamera"):
        existing.status = attendance.status
        existing.check_in = attendance.check_in
        existing.check_out = attendance.check_out
        existing.source = "kamera"
        return
    # Turniket kabi boshqa manba: eng erta kelish, eng kech ketish.
    check_ins = [t for t in (existing.check_in, attendance.check_in) if t is not None]
    if check_ins:
        from app.timezone import business_seconds

        earliest = min(check_ins, key=business_seconds)
        existing.check_in = earliest
        existing.status = policy.arrival_status(earliest, person_type, day)
    check_outs = [t for t in (existing.check_out, attendance.check_out) if t is not None]
    if check_outs:
        from app.timezone import business_seconds

        existing.check_out = max(check_outs, key=business_seconds)


async def _clear_day(db: AsyncSession, day, start: datetime, end: datetime) -> None:
    """Kunning oldingi video natijalari (qayta hisoblash uchun)."""
    await db.execute(
        delete(AttendanceRecord).where(
            AttendanceRecord.date == day,
            or_(
                AttendanceRecord.source == "kamera",
                and_(AttendanceRecord.status == "kelmadi", AttendanceRecord.source.is_(None)),
            ),
        )
    )
    await db.execute(
        delete(PresenceVisit).where(PresenceVisit.first_seen_at >= start, PresenceVisit.first_seen_at < end)
    )
    await db.execute(
        delete(Event).where(
            Event.occurred_at >= start,
            Event.occurred_at < end,
            Event.module_code.in_((COAT_CODE, SMOKING_CODE, PUNCTUALITY_CODE)),
            Event.details["source"].astext == VIDEO_ANALYSIS_SOURCE,
        )
    )
    await db.execute(delete(DailyPersonCriteria).where(DailyPersonCriteria.day == day))


async def aggregate_run(db: AsyncSession, run: VideoAnalysisRun, *, now: datetime | None = None) -> dict:
    """Bitta kun tahlilining yakuni. Qaytaradi — kriteriyalar bo'yicha sonlar."""
    now = now or datetime.now(timezone.utc)
    day = run.day
    day_start, day_end = day_bounds(day)
    policy = await load_policy(db)

    jobs = [
        _job_info(job)
        for job in (await db.execute(select(VideoAnalysisJob).where(VideoAnalysisJob.run_id == run.id))).scalars()
    ]
    observations = [
        _obs(row)
        for row in (
            await db.execute(select(VideoObservation).where(VideoObservation.run_id == run.id))
        ).scalars()
    ]
    modules = {
        module.code: module for module in (await db.execute(select(AIModuleConfig))).scalars().all()
    }
    active_codes = {code for code, module in modules.items() if module.active}

    camera_ids = {uuid.UUID(job.camera_id) for job in jobs if job.camera_id}
    cameras: dict[str, Camera] = {
        str(camera.id): camera
        for camera in (await db.execute(select(Camera).where(Camera.id.in_(camera_ids)))).scalars().unique()
    } if camera_ids else {}
    door_cameras = {
        job.camera_id for job in jobs if job.kind == KIND_ENTRANCE and job.camera_id
    } | {camera_id for camera_id, camera in cameras.items() if is_door_camera(camera)}

    await _clear_day(db, day, day_start, day_end)

    # Odamlar: tasdiqlangan faol hamma + kuzatilganlar.
    observed_ids = {uuid.UUID(obs.person_id) for obs in observations}
    people_rows = (
        await db.execute(
            select(StudentStaff).where(
                or_(
                    and_(StudentStaff.active.is_(True), StudentStaff.biometrics_status == "tasdiqlangan"),
                    StudentStaff.id.in_(observed_ids) if observed_ids else false(),
                )
            )
        )
    ).scalars().unique().all()
    people = {str(person.id): person for person in people_rows}
    staff_ids = {pid for pid, person in people.items() if person.type == "xodim"}

    stats: dict[str, int] = defaultdict(int)
    by_person = group_by_person(observations)
    findings: dict[str, list[dict]] = defaultdict(list)

    def note(
        person_id: str | None, code: int, kind: str, camera_id: str | None, at: datetime | None, reason: str
    ) -> None:
        if person_id is None or code not in active_codes:
            return
        item = _finding(code, kind, camera_id, at, reason)
        if item is not None:
            findings[person_id].append(item)

    # ── kunlik davomat va tashriflar ────────────────────────────────────
    existing_records = {
        str(record.student_staff_id): record
        for record in (await db.execute(select(AttendanceRecord).where(AttendanceRecord.date == day))).scalars()
    }
    attendance_on = bool(active_codes & set(ATTENDANCE_CODES))
    day_results: dict[str, DayAttendance] = {}
    for person_id, reliable_obs in by_person.items():
        person = people.get(person_id)
        if person is None or not reliable_obs:
            continue
        attendance = day_attendance(
            reliable_obs,
            person_type=person.type,
            day=day,
            policy=policy,
            door_cameras=door_cameras,
            now=now,
        )
        if attendance is None:
            continue
        day_results[person_id] = attendance
        for visit in presence_visits(reliable_obs, settings.presence_visit_gap_minutes):
            db.add(
                PresenceVisit(
                    student_staff_id=uuid.UUID(person_id),
                    camera_id=uuid.UUID(visit["camera_id"]),
                    first_seen_at=visit["first_seen_at"],
                    last_seen_at=visit["last_seen_at"],
                    sightings=visit["sightings"],
                    best_similarity=visit["best_similarity"],
                )
            )
        type_code = 7 if person.type == "talaba" else 6
        if attendance_on and type_code in active_codes:
            await _write_attendance(
                db, person_id, day, attendance, existing_records.get(person_id), policy, person.type
            )
            stats["kelganlar"] += 1
            if attendance.status == "kech_keldi":
                stats["kech_kelganlar"] += 1
                if attendance.arrival_known:
                    note(person_id, type_code, holatlar.LATE, attendance.arrival_camera_id, attendance.arrived_at,
                         f"{attendance.late_minutes} daqiqa kech keldi ({_hhmm(attendance.arrived_at)})")
            if attendance.early_leave == "erta_ketdi":
                stats["erta_ketganlar"] += 1
                note(person_id, EARLY_LEAVE_CODE, holatlar.WORK_EARLY, attendance.exit_camera_id, attendance.left_at,
                     f"Ishdan erta ketdi (oxirgi ko'rinish {_hhmm(attendance.left_at)})")
    await db.flush()

    # ── darslar ─────────────────────────────────────────────────────────
    lesson_jobs = [job for job in jobs if job.kind == KIND_LESSON and job.lesson_id]
    lesson_rows = {
        str(row.id): row
        for row in (
            await db.execute(
                select(LessonSession).where(LessonSession.id.in_([uuid.UUID(job.lesson_id) for job in lesson_jobs]))
            )
        ).scalars().unique()
    } if lesson_jobs else {}
    obs_by_job: dict[str, list[Obs]] = defaultdict(list)
    for obs in observations:
        obs_by_job[obs.job_id].append(obs)
    rosters: dict[str, list[str]] = {}
    student_lessons: dict[str, list] = defaultdict(list)
    teacher_lessons: dict[str, list] = defaultdict(list)
    punctuality_events: list[tuple[LessonSession, object]] = []
    for job in lesson_jobs:
        row = lesson_rows.get(job.lesson_id)
        if row is None or row.scheduled_start_time is None:
            continue
        end = row.scheduled_end_time or row.scheduled_start_time + timedelta(minutes=settings.lesson_duration_minutes)
        lesson = LessonInfo(
            id=str(row.id),
            group_name=row.group_name,
            teacher_id=str(row.teacher_id) if row.teacher_id else None,
            camera_id=str(row.camera_id) if row.camera_id else None,
            start=row.scheduled_start_time,
            end=end,
        )
        if row.group_name not in rosters:
            rosters[row.group_name] = await _group_roster(db, row.group_name, day_end)
        result = lesson_result(
            lesson, job, obs_by_job.get(job.id, []), rosters[row.group_name], staff_ids, window_end=run.window_end
        )
        await db.execute(delete(LessonAttendance).where(LessonAttendance.lesson_session_id == row.id))
        span = f"{row.group_name}, {_hhmm(lesson.start)}–{_hhmm(lesson.end)}"
        for student_id, student in result.students.items():
            if student.status == "kech_keldi":
                note(student_id, LESSON_LATE_CODE, holatlar.LESSON_LATE, lesson.camera_id, student.first_seen,
                     f"Darsga kech keldi: {span}, xonada {_hhmm(student.first_seen)} dan")
            elif student.status == "kelmadi":
                note(student_id, 7, holatlar.LESSON_ABSENT, lesson.camera_id, result.room_at, f"Darsda ko'rinmadi: {span}")
            if student.left_early:
                note(student_id, EARLY_LEAVE_CODE, holatlar.LESSON_EARLY, lesson.camera_id, student.last_seen,
                     f"Darsdan erta chiqdi: {span}, oxirgi ko'rinish {_hhmm(student.last_seen)}")
            if student.attention is not None and student.attention < settings.video_attention_low_score:
                note(student_id, ATTENTION_CODE, holatlar.LOW_ATTENTION, lesson.camera_id, student.attention_at,
                     f"Darsga diqqati past: {student.attention}/100 ({span})")
            db.add(
                LessonAttendance(
                    lesson_session_id=row.id,
                    student_staff_id=uuid.UUID(student_id),
                    first_seen_at=student.first_seen,
                    last_seen_at=student.last_seen,
                    sightings=student.sightings,
                    status=student.status,
                    left_early=student.left_early,
                    attention_score=student.attention,
                    attention_samples=student.attention_samples,
                )
            )
            student_lessons[student_id].append(student)
        row.attention_score = result.attention or 0
        row.attention_samples = result.attention_samples if result.attention is not None else 0
        if result.teacher is not None:
            teacher = result.teacher
            row.teacher_on_time = teacher.on_time
            row.teacher_first_seen_at = teacher.first_seen
            row.teacher_presence_pct = teacher.presence_pct
            row.teacher_activity_score = teacher.activity or 0
            row.activity_samples = teacher.activity_samples if teacher.activity is not None else 0
            row.punctuality_checked_at = now
            teacher_lessons[lesson.teacher_id].append(teacher)
            if teacher.status == "kechikdi":
                note(lesson.teacher_id, PUNCTUALITY_CODE, holatlar.TEACHER_LATE, lesson.camera_id, teacher.first_seen,
                     f"Darsga kech kirdi: dars {_hhmm(lesson.start)}, xonada {_hhmm(teacher.first_seen)} dan ({span})")
            elif teacher.status == "kelmadi":
                note(lesson.teacher_id, PUNCTUALITY_CODE, holatlar.TEACHER_ABSENT, lesson.camera_id, result.room_at,
                     f"Darsda ko'rinmadi ({span})")
            if teacher.activity is not None and teacher.activity < settings.video_teacher_activity_low_score:
                note(lesson.teacher_id, ACTIVITY_CODE, holatlar.LOW_ACTIVITY, lesson.camera_id, teacher.activity_at,
                     f"Darsdagi faolligi past: {teacher.activity}/100 ({span})")
            if teacher.status in ("kechikdi", "kelmadi"):
                punctuality_events.append((row, teacher))
                stats["oqituvchi_" + teacher.status] += 1
            elif teacher.status == "vaqtida":
                stats["oqituvchi_vaqtida"] += 1
        stats["darslar"] += 1
        if result.measured:
            stats["olchangan_darslar"] += 1
    await db.flush()

    # ── qo'lda bo'lmagan "kelmadi" (kunlik) ─────────────────────────────
    # Faqat ertalabki kelish oynasining videosi yetarlicha o'qilgan bo'lsa:
    # o'qilmagan soatlarda kelganlarga "kelmadi" — dalilsiz ayblov.
    until = datetime.combine(day, time_type.fromisoformat(settings.attendance_late_window_end), tzinfo=INSTITUTE_TZ)
    coverage = arrival_coverage(jobs, until)
    if coverage is not None:
        stats["kelish_qamrovi_foiz"] = round(100 * coverage)
    if attendance_on and settings.attendance_absence_marking_enabled and policy.is_work_day(day):
        if coverage is None or coverage < settings.video_absence_min_coverage:
            stats["kelmadi_belgilanmadi"] = 1
            logger.warning(
                "absence marking skipped: arrival window not covered by analysed video",
                extra={"day": day.isoformat(), "coverage": coverage, "required": settings.video_absence_min_coverage},
            )
        else:
            from app.jobs.absence_marker import mark_absences_for_day

            await db.commit()
            local_hour = to_local(now).time()
            from app.jobs.absence_marker import _quiet_after
            from app.timezone import business_seconds

            quiet = business_seconds(local_hour) >= business_seconds(_quiet_after())
            stats["kelmadi_belgilandi"] = await mark_absences_for_day(db, day, notify=not quiet)

    records = {
        str(record.student_staff_id): record
        for record in (await db.execute(select(AttendanceRecord).where(AttendanceRecord.date == day))).scalars()
    }

    # ── hodisalar ───────────────────────────────────────────────────────
    smoking_by_person: dict[str, int] = defaultdict(int)
    if settings.video_analysis_events:
        for incident in smoking_incidents([job for job in jobs if job.result]):
            person = people.get(incident.person_id) if incident.person_id else None
            event = await create_analysis_event(
                db,
                camera=cameras.get(incident.camera_id) if incident.camera_id else None,
                module_code=SMOKING_CODE,
                confidence=incident.confidence,
                severity="o'rta",
                occurred_at=incident.at,
                person_name=person.full_name if person else None,
                snapshot_key=incident.snapshot_key,
                module=modules.get(SMOKING_CODE),
                details={
                    "reason": f"Qo'l og'izga {incident.episodes} marta ko'tarildi ({incident.clips} klipda)",
                    "episodes": incident.episodes,
                    "clips": incident.clips,
                    "cigarette_seen": incident.cigarette_seen,
                    "person_id": incident.person_id,
                    "run_id": str(run.id),
                },
            )
            if event is not None:
                stats["chekish"] += 1
            if incident.person_id:
                smoking_by_person[incident.person_id] += 1
                note(incident.person_id, SMOKING_CODE, holatlar.SMOKING, incident.camera_id, incident.at,
                     f"Chekish harakati: qo'l og'izga {incident.episodes} marta ({incident.clips} klipda)")

        for row, teacher in punctuality_events:
            teacher_person = people.get(str(row.teacher_id)) if row.teacher_id else None
            camera = cameras.get(str(row.camera_id)) if row.camera_id else None
            start_local = to_local(row.scheduled_start_time).strftime("%H:%M")
            if teacher.status == "kechikdi":
                seen = to_local(teacher.first_seen).strftime("%H:%M")
                reason = f"Dars {start_local} da boshlangan, o'qituvchi {seen} da kirdi"
            else:
                reason = f"Dars {start_local} da boshlangan, o'qituvchi xonada ko'rinmadi"
            others = [people[pid].full_name for pid in teacher.others if pid in people][:3]
            if others:
                reason += f"; xonada: {', '.join(others)}"
            await create_analysis_event(
                db,
                camera=camera,
                module_code=PUNCTUALITY_CODE,
                confidence=90 if teacher.status == "kechikdi" else 75,
                severity="o'rta",
                occurred_at=teacher.first_seen or row.scheduled_start_time,
                person_name=teacher_person.full_name if teacher_person else row.teacher,
                module=modules.get(PUNCTUALITY_CODE),
                details={
                    "reason": reason,
                    "lesson_session_id": str(row.id),
                    "group": row.group_name,
                    "subject": row.subject,
                    "status": teacher.status,
                    "others": teacher.others,
                    "run_id": str(run.id),
                },
            )

    # ── kunlik natija (har odam) ────────────────────────────────────────
    raw_by_person: dict[str, list[Obs]] = defaultdict(list)
    for obs in observations:
        raw_by_person[obs.person_id].append(obs)
    coat_events = 0
    rows_written = 0
    for person_id, person in people.items():
        attendance = day_results.get(person_id)
        record = records.get(person_id)
        lessons = student_lessons.get(person_id, [])
        taught = teacher_lessons.get(person_id, [])
        reliable_obs = by_person.get(person_id, [])
        required = coat_rules.coat_required(person.type, person.position, person.group_or_position)
        votes = coat_votes(reliable_obs)
        coat_status = coat_rules.day_verdict(votes, required) if (votes or required) else None
        if not reliable_obs and not lessons and not taught and record is None:
            continue
        measured_lessons = [lesson for lesson in lessons if lesson.status is not None]
        attention_parts = [(lesson.attention, lesson.attention_samples) for lesson in lessons if lesson.attention is not None]
        attention = (
            round(sum(score * weight for score, weight in attention_parts) / sum(weight for _s, weight in attention_parts))
            if attention_parts and sum(weight for _s, weight in attention_parts) > 0
            else None
        )
        activities = [t.activity for t in taught if t.activity is not None]
        coat_ratio = (sum(1 for vote in votes if vote) / len(votes)) if votes else None
        coat_evidence = next((obs for obs in raw_by_person.get(person_id, []) if obs.evidence_key), None)
        coat_anchor = coat_evidence or (reliable_obs[0] if reliable_obs else None)
        if coat_status == coat_rules.COAT_NO and coat_anchor is not None:
            note(person_id, COAT_CODE, holatlar.NO_COAT, coat_anchor.camera_id, coat_anchor.seen_at,
                 f"Oq xalatsiz: {len(votes)} ta kuzatuvdan {len(votes) - sum(votes)} tasida xalat ko'rinmadi")
        db.add(
            DailyPersonCriteria(
                student_staff_id=person.id,
                day=day,
                run_id=run.id,
                attendance_status=record.status if record is not None else None,
                arrived_at=attendance.arrived_at if attendance else None,
                left_at=attendance.left_at if attendance else None,
                late_minutes=attendance.late_minutes if attendance and attendance.arrival_known else None,
                early_leave=attendance.early_leave if attendance else None,
                sightings=attendance.sightings if attendance else 0,
                cameras_seen=attendance.cameras if attendance else 0,
                lessons_total=len(lessons) if lessons else None,
                lessons_attended=sum(1 for l in measured_lessons if l.status in ("keldi", "kech_keldi")) if lessons else None,
                lessons_late=sum(1 for l in measured_lessons if l.status == "kech_keldi") if lessons else None,
                lessons_left_early=sum(1 for l in lessons if l.left_early) if lessons else None,
                lessons_unmeasured=sum(1 for l in lessons if l.status is None) if lessons else None,
                attention_score=attention,
                coat_status=coat_status,
                coat_samples=len(votes),
                coat_white_samples=sum(1 for vote in votes if vote),
                smoking_events=smoking_by_person.get(person_id, 0),
                teacher_lessons=len(taught) if taught else None,
                teacher_on_time=sum(1 for t in taught if t.status == "vaqtida") if taught else None,
                teacher_late=sum(1 for t in taught if t.status == "kechikdi") if taught else None,
                teacher_absent=sum(1 for t in taught if t.status == "kelmadi") if taught else None,
                teacher_activity=round(sum(activities) / len(activities)) if activities else None,
                details={
                    "arrival_known": attendance.arrival_known if attendance else None,
                    "coat_ratio": round(coat_ratio, 2) if coat_ratio is not None else None,
                    # Aniqlangan holatlar (payt, kamera, sabab); video dalil —
                    # app/batch/evidence.py keyin "klip" ga yozadi.
                    "dalillar": sorted(findings.get(person_id, []), key=lambda item: item["vaqt"]),
                },
                computed_at=now,
            )
        )
        rows_written += 1
        if coat_status == coat_rules.COAT_YES:
            stats["xalat_kiygan"] += 1
        elif coat_status == coat_rules.COAT_NO:
            stats["xalat_kiymagan"] += 1
            if settings.video_analysis_events and coat_events < settings.video_analysis_coat_events_max:
                evidence, anchor = coat_evidence, coat_anchor
                if anchor is not None:
                    event = await create_analysis_event(
                        db,
                        camera=cameras.get(anchor.camera_id) if anchor.camera_id else None,
                        module_code=COAT_CODE,
                        confidence=int(round(100 * (1 - (coat_ratio or 0.0)))),
                        severity="past",
                        occurred_at=anchor.seen_at,
                        person_name=person.full_name,
                        snapshot_key=evidence.evidence_key if evidence else None,
                        module=modules.get(COAT_CODE),
                        details={
                            "reason": f"Kun davomida {len(votes)} ta kuzatuvdan {len(votes) - sum(votes)} tasida oq xalat ko'rinmadi",
                            "samples": len(votes),
                            "white": sum(1 for vote in votes if vote),
                            "person_id": person_id,
                            "run_id": str(run.id),
                        },
                    )
                    if event is not None:
                        coat_events += 1
        if lessons:
            stats["dars_kechikish"] += sum(1 for l in lessons if l.status == "kech_keldi")
            stats["darsdan_erta_ketish"] += sum(1 for l in lessons if l.left_early)
    stats["kunlik_qatorlar"] = rows_written
    stats["kuzatuvlar"] = len(observations)
    stats["tanilgan_odamlar"] = len([p for p, items in by_person.items() if items])
    await db.commit()
    logger.info("video analysis aggregated", extra={"day": day.isoformat(), **stats})
    return dict(stats)
