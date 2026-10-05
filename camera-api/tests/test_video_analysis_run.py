"""Kunlik tahlilning to'liq yo'li bazada: reja -> vazifalar -> agregatsiya.

Tahlilchi bu yerda "ssenariy" bo'yicha javob beradi (kim, qaysi kamerada,
qachon ko'rindi) — kadr tahlilining o'zi tests/test_batch_analyzer.py va
tests/test_video_analysis_e2e.py da. Bu fayl natijalar mavjud jadvallarga
(davomat, dars, hodisalar) to'g'ri yozilishini, qayta hisoblash
idempotentligini, qo'lda kiritilgan yozuvlar saqlanishini, uzilishdan
keyin davom etishni va rejalashtirishni tekshiradi."""

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy import func, select

from app.batch.analyzer import JobOutcome, ObservationData
from app.config import settings
from app.jobs import video_analysis as va
from app.models import (
    AttendanceRecord,
    Camera,
    DailyPersonCriteria,
    Event,
    LessonAttendance,
    LessonSession,
    NvrDevice,
    PresenceVisit,
    StudentStaff,
    VideoAnalysisJob,
    VideoAnalysisRun,
    VideoObservation,
)
from app.timezone import INSTITUTE_TZ, business_today
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.daily_mode


def past_work_day() -> date:
    day = business_today() - timedelta(days=1)
    while day.isoweekday() == 7:
        day -= timedelta(days=1)
    return day


DAY = past_work_day()


def at(hh, mm, ss=0, day=None) -> datetime:
    return datetime.combine(day or DAY, time(hh, mm, ss), tzinfo=INSTITUTE_TZ).astimezone(timezone.utc)


@dataclass
class Seen:
    person: str
    camera: str
    moment: datetime
    sim: float = 0.62
    coat: bool | None = None
    phone: bool = False
    frontal: bool = True
    movement: float | None = None


@dataclass
class Script:
    seen: list[Seen] = field(default_factory=list)
    smoking: list[tuple[str, datetime, str]] = field(default_factory=list)  # (kamera, payt, odam)
    fail_once: set[str] = field(default_factory=set)
    uncovered: set[str] = field(default_factory=set)  # shu kameralarda yozuv yo'q


class ScriptedAnalyzer:
    def __init__(self, script: Script, people: dict[str, str]):
        self.script = script
        self.people = people  # nom -> id
        self.calls: dict[str, int] = {}

    async def run(self, ctx, source, *, should_stop=None):
        name = ctx.camera_name
        self.calls[name] = self.calls.get(name, 0) + 1
        if name in self.script.fail_once and self.calls[name] == 1:
            raise RuntimeError("NVR uzildi")
        outcome = JobOutcome()
        if name in self.script.uncovered:
            return outcome
        for index, clip in enumerate(ctx.clips):
            outcome.frames += clip.frames
            faces = 0
            for item in self.script.seen:
                if item.camera != name or not (clip.start <= item.moment < clip.end):
                    continue
                faces += 1
                coat_frames = 1 if item.coat is not None else 0
                outcome.observations.append(
                    ObservationData(
                        person_id=self.people[item.person],
                        seen_at=item.moment,
                        last_seen_at=item.moment + timedelta(seconds=1),
                        similarity=item.sim,
                        margin=0.2,
                        frames=1,
                        face_px=80,
                        frontal_frames=1 if item.frontal and not item.phone else 0,
                        phone_frames=1 if item.phone else 0,
                        coat_frames=coat_frames,
                        coat_white_frames=1 if item.coat else 0,
                        movement=item.movement,
                        evidence_key="dalil.jpg" if item.coat is False else None,
                        clip_index=index,
                    )
                )
            for camera, moment, person in self.script.smoking:
                if camera == name and clip.start <= moment < clip.end:
                    outcome.smoking.append(
                        {"at": moment.isoformat(), "person_id": self.people.get(person), "episodes": 3,
                         "confidence": 70, "snapshot_key": "chekish.jpg"}
                    )
            outcome.faces += faces
            outcome.covered.append([index, clip.frames, faces])
        return outcome


def embedding() -> str:
    return json.dumps(list(np.random.default_rng().normal(size=8)))


@pytest.fixture
async def campus(db_session, seeded):
    nvr = NvrDevice(name="NVR-1", kind="fayl", base_path="/tmp/nvr", max_streams=4)
    db_session.add(nvr)
    await db_session.flush()
    cams = {
        "door": Camera(name="Asosiy kirish", ip="10.0.0.1", zone="A", resolution="4K", status="faol", is_entrance=True,
                       nvr_id=nvr.id, nvr_channel=1),
        "room": Camera(name="201-xona", ip="10.0.0.2", zone="A", resolution="4K", status="faol",
                       room_type="auditoriya", nvr_id=nvr.id, nvr_channel=2),
        "yard": Camera(name="Hovli", ip="10.0.0.3", zone="A", resolution="4K", status="faol", room_type="tashqi",
                       nvr_id=nvr.id, nvr_channel=3),
        "nomap": Camera(name="Bog'lanmagan", ip="10.0.0.4", zone="A", resolution="4K", status="faol",
                        is_entrance=True),
    }
    db_session.add_all(cams.values())
    before = datetime.combine(DAY - timedelta(days=30), time(9), tzinfo=timezone.utc)

    def person(name, kind, group, position=None):
        return StudentStaff(full_name=name, type=kind, group_or_position=group, position=position,
                            biometrics_status="tasdiqlangan", biometric_embedding=embedding(),
                            biometrics_confirmed_at=before)

    people = {
        "T": person("Toshmatov Teacher", "xodim", "Anatomiya kafedrasi", "o'qituvchi"),
        "X": person("Xolmatov Buxgalter", "xodim", "Buxgalteriya", "buxgalter"),
        "S1": person("Aliyev Talaba", "talaba", "DI-101"),
        "S2": person("Valiyeva Talaba", "talaba", "DI-101"),
        "S3": person("Karimov Talaba", "talaba", "DI-101"),
    }
    db_session.add_all(people.values())
    await db_session.flush()
    lesson = LessonSession(date=DAY, group_name="DI-101", faculty="Davolash", teacher="Toshmatov", subject="Anatomiya",
                           teacher_id=people["T"].id, camera_id=cams["room"].id, scheduled_start_time=at(9, 0),
                           scheduled_end_time=at(10, 20))
    db_session.add(lesson)
    await db_session.commit()
    return {
        "nvr": nvr,
        "cams": {key: cam.name for key, cam in cams.items()},
        "cam_ids": {key: cam.id for key, cam in cams.items()},
        "people": {key: str(p.id) for key, p in people.items()},
        "lesson": lesson.id,
    }


def full_day_script() -> Script:
    door, room, yard = "Asosiy kirish", "201-xona", "Hovli"
    # Dars kliplari: boshlanish 08:50..09:19 har daqiqada, o'rta 09:22:30 dan
    # har 5 daqiqada, oxir 10:05..10:19 har daqiqada (3 s dan).
    seen = [
        Seen("T", door, at(7, 50)), Seen("T", room, at(8, 58)), Seen("T", room, at(9, 27, 31), movement=60),
        Seen("T", room, at(9, 42, 31), movement=40), Seen("T", door, at(17, 30)),
        Seen("X", door, at(8, 40)), Seen("X", yard, at(12, 0, 5)), Seen("X", door, at(13, 0)),
        Seen("S1", door, at(8, 20), coat=True), Seen("S1", room, at(8, 55), coat=True),
        Seen("S1", room, at(9, 27, 31), coat=True), Seen("S1", room, at(10, 15, 1)), Seen("S1", door, at(17, 10)),
        Seen("S2", door, at(8, 5), coat=False), Seen("S2", room, at(9, 15), coat=False),
        Seen("S2", room, at(9, 27, 31), coat=False, phone=True), Seen("S2", room, at(9, 32, 31), phone=True),
    ]
    return Script(seen=seen, smoking=[(yard, at(12, 0, 5), "X")])


async def run_day(script: Script, people: dict, day=DAY, now=None):
    async with TestSessionLocal() as db:
        run = await va.create_run(db, day, now=now or datetime.combine(day + timedelta(days=1), time(9), tzinfo=timezone.utc))
        run_id = run.id
    executor = va.RunExecutor(run_id, TestSessionLocal, analyzer=ScriptedAnalyzer(script, people),
                              source_factory=lambda nvr, camera: None)
    result = await executor.execute()
    return result


def _snap_at(seen_list, camera):
    return [s for s in seen_list if s.camera == camera]


async def test_plan_creates_jobs_only_for_mapped_cameras(campus, db_session):
    async with TestSessionLocal() as db:
        run = await va.create_run(db, DAY, now=at(23, 0))
    jobs = (await db_session.execute(select(VideoAnalysisJob).where(VideoAnalysisJob.run_id == run.id))).scalars().all()
    kinds = {}
    for job in jobs:
        kinds.setdefault(job.kind, set()).add(job.camera_id)
    assert kinds["kirish"] == {campus["cam_ids"]["door"]}
    assert kinds["dars"] == {campus["cam_ids"]["room"]}
    assert kinds["chekish"] == {campus["cam_ids"]["yard"]}
    assert run.jobs_total == len(jobs) and run.frames_planned > 0
    assert run.window_start == at(7, 0) and run.window_end == at(20, 0)


async def test_full_day_results(campus, db_session):
    people = campus["people"]
    run = await run_day(full_day_script(), people)
    assert run.status == "tugadi", run.error
    assert run.jobs_failed == 0
    stats = run.stats
    assert stats["kelganlar"] == 4 and stats["chekish"] == 1

    records = {
        str(r.student_staff_id): r
        for r in (await db_session.execute(select(AttendanceRecord).where(AttendanceRecord.date == DAY))).scalars()
    }
    assert records[people["T"]].status == "keldi" and records[people["T"]].check_in == time(7, 50)
    assert records[people["T"]].check_out == time(17, 30, 1)
    assert records[people["X"]].status == "kech_keldi"
    assert records[people["S1"]].status == "kech_keldi"  # 08:20 > 08:10
    assert records[people["S2"]].status == "keldi"
    assert records[people["S3"]].status == "kelmadi"  # tahlildan keyin belgilandi
    assert all(r.source in ("kamera", None) for r in records.values())

    daily = {
        str(r.student_staff_id): r
        for r in (await db_session.execute(select(DailyPersonCriteria).where(DailyPersonCriteria.day == DAY))).scalars()
    }
    x = daily[people["X"]]
    assert x.late_minutes == 40 and x.early_leave == "erta_ketdi" and x.smoking_events == 1
    assert x.coat_status is None  # buxgalter — xalat talab qilinmaydi va namuna yo'q
    t = daily[people["T"]]
    assert t.teacher_lessons == 1 and t.teacher_on_time == 1 and t.teacher_activity is not None
    assert t.early_leave == "vaqtida"
    s1, s2, s3 = daily[people["S1"]], daily[people["S2"]], daily[people["S3"]]
    assert s1.coat_status == "kiygan" and s2.coat_status == "kiymagan"
    assert (s1.lessons_total, s1.lessons_attended, s1.lessons_late, s1.lessons_left_early) == (1, 1, 0, 0)
    assert (s2.lessons_attended, s2.lessons_late, s2.lessons_left_early) == (1, 1, 1)
    assert s3.attendance_status == "kelmadi" and s3.lessons_attended == 0
    assert s1.attention_score == 100 and s2.attention_score < 60

    lesson_rows = {
        str(r.student_staff_id): r
        for r in (
            await db_session.execute(select(LessonAttendance).where(LessonAttendance.lesson_session_id == campus["lesson"]))
        ).scalars()
    }
    assert lesson_rows[people["S1"]].status == "keldi" and lesson_rows[people["S1"]].left_early is False
    assert lesson_rows[people["S2"]].status == "kech_keldi" and lesson_rows[people["S2"]].left_early is True
    assert lesson_rows[people["S3"]].status == "kelmadi"

    lesson = await db_session.get(LessonSession, campus["lesson"])
    await db_session.refresh(lesson)
    assert lesson.teacher_on_time is True and lesson.teacher_first_seen_at == at(8, 58)
    assert lesson.attention_samples > 0 and lesson.punctuality_checked_at is not None

    events = (await db_session.execute(select(Event).order_by(Event.module_code))).scalars().all()
    by_code = {e.module_code: e for e in events}
    assert set(by_code) == {10, 15}
    assert by_code[15].person_name == "Xolmatov Buxgalter" and by_code[15].occurred_at == at(12, 0, 5)
    assert by_code[15].is_trial and by_code[15].details["source"] == "video_tahlil"
    assert by_code[10].person_name == "Valiyeva Talaba" and by_code[10].snapshot_key == "dalil.jpg"

    visits = (await db_session.execute(select(func.count()).select_from(PresenceVisit))).scalar_one()
    assert visits >= 6


async def test_recompute_is_idempotent_and_keeps_manual_records(campus, db_session):
    people = campus["people"]
    await run_day(full_day_script(), people)
    # Operator X ning kunini qo'lda tuzatdi.
    record = (
        await db_session.execute(
            select(AttendanceRecord).where(AttendanceRecord.student_staff_id == uuid.UUID(people["X"]),
                                           AttendanceRecord.date == DAY)
        )
    ).scalar_one()
    record.status, record.check_in, record.source = "keldi", time(8, 0), "qolda"
    await db_session.commit()
    record_id = record.id

    run = await run_day(full_day_script(), people)
    assert run.status == "tugadi"
    db_session.expire_all()
    counts = {
        "records": await db_session.scalar(select(func.count()).select_from(AttendanceRecord).where(AttendanceRecord.date == DAY)),
        "daily": await db_session.scalar(select(func.count()).select_from(DailyPersonCriteria)),
        "events": await db_session.scalar(select(func.count()).select_from(Event)),
        "lesson": await db_session.scalar(select(func.count()).select_from(LessonAttendance)),
        "obs_runs": await db_session.scalar(select(func.count(func.distinct(VideoObservation.run_id)))),
    }
    assert counts == {"records": 5, "daily": 5, "events": 2, "lesson": 3, "obs_runs": 1}
    manual = await db_session.get(AttendanceRecord, record_id)
    assert manual.source == "qolda" and manual.check_in == time(8, 0)


async def test_turnstile_record_is_merged_not_replaced(campus, db_session):
    people = campus["people"]
    db_session.add(AttendanceRecord(student_staff_id=uuid.UUID(people["T"]), date=DAY, status="keldi",
                                    check_in=time(7, 40), check_out=time(16, 0), source="turniket"))
    await db_session.commit()
    await run_day(full_day_script(), people)
    db_session.expire_all()
    record = (
        await db_session.execute(select(AttendanceRecord).where(AttendanceRecord.student_staff_id == uuid.UUID(people["T"])))
    ).scalar_one()
    assert record.source == "turniket"
    assert record.check_in == time(7, 40)  # eng erta
    assert record.check_out == time(17, 30, 1)  # eng kech


async def test_day_without_recognitions_leaves_existing_data_untouched(campus, db_session):
    people = campus["people"]
    db_session.add(AttendanceRecord(student_staff_id=uuid.UUID(people["S1"]), date=DAY, status="keldi",
                                    check_in=time(8, 0), source="kamera"))
    await db_session.commit()
    run = await run_day(Script(), people)
    assert run.status == "tugadi" and "izoh" in run.stats
    db_session.expire_all()
    rows = (await db_session.execute(select(AttendanceRecord).where(AttendanceRecord.date == DAY))).scalars().all()
    assert [(str(r.student_staff_id), r.status) for r in rows] == [(people["S1"], "keldi")]


async def test_no_absence_when_morning_door_video_was_not_read(campus, db_session):
    """Eshik videosi o'qilmagan (muddat yetmagan, yozuv yo'q) — o'sha
    soatlarda kelganlarga "kelmadi" yozilmaydi; sababi statistikada."""
    people = campus["people"]
    script = full_day_script()
    script.uncovered = {"Asosiy kirish"}
    run = await run_day(script, people)
    assert run.status == "tugadi"
    assert run.stats["kelmadi_belgilanmadi"] == 1 and run.stats["kelish_qamrovi_foiz"] == 0
    db_session.expire_all()
    statuses = {
        str(r.student_staff_id): r.status
        for r in (await db_session.execute(select(AttendanceRecord).where(AttendanceRecord.date == DAY))).scalars()
    }
    assert people["S3"] not in statuses  # "kelmadi" emas — aniqlanmadi
    assert "kelmadi" not in statuses.values()


async def test_failed_job_is_retried(campus, db_session):
    script = full_day_script()
    script.fail_once = {"Hovli"}
    run = await run_day(script, campus["people"])
    assert run.status == "tugadi" and run.jobs_failed == 0
    retried = (
        await db_session.execute(select(VideoAnalysisJob).where(VideoAnalysisJob.run_id == run.id,
                                                               VideoAnalysisJob.attempts > 1))
    ).scalars().all()
    assert retried


async def test_job_failing_every_time_is_marked_failed(campus, db_session, monkeypatch):
    class Broken(ScriptedAnalyzer):
        async def run(self, ctx, source, *, should_stop=None):
            if ctx.camera_name == "Hovli":
                raise RuntimeError("doim xato")
            return await super().run(ctx, source, should_stop=should_stop)

    async with TestSessionLocal() as db:
        run = await va.create_run(db, DAY, now=at(23, 0))
    executor = va.RunExecutor(run.id, TestSessionLocal, analyzer=Broken(full_day_script(), campus["people"]),
                              source_factory=lambda nvr, camera: None)
    run = await executor.execute()
    assert run.status == "tugadi"
    assert run.jobs_failed > 0


async def test_uncovered_lesson_is_not_absence(campus, db_session):
    script = full_day_script()
    script.uncovered = {"201-xona"}
    await run_day(script, campus["people"])
    rows = (await db_session.execute(select(LessonAttendance))).scalars().all()
    assert rows and all(r.status is None for r in rows)
    lesson = await db_session.get(LessonSession, campus["lesson"])
    await db_session.refresh(lesson)
    assert lesson.teacher_on_time is None


async def test_late_teacher_raises_punctuality_event(campus, db_session):
    script = full_day_script()
    script.seen = [s for s in script.seen if not (s.person == "T" and s.camera == "201-xona")]
    script.seen.append(Seen("T", "201-xona", at(9, 18)))
    script.seen.append(Seen("T", "201-xona", at(9, 42, 31)))
    await run_day(script, campus["people"])
    event = (await db_session.execute(select(Event).where(Event.module_code == 22))).scalar_one()
    assert event.details["status"] == "kechikdi" and "09:18" in event.details["reason"]
    assert not event.is_trial  # #22 ishchi rejimda


async def test_resume_after_crash(campus, db_session):
    async with TestSessionLocal() as db:
        run = await va.create_run(db, DAY, now=at(23, 0))
        job = (await db.execute(select(VideoAnalysisJob).where(VideoAnalysisJob.run_id == run.id).limit(1))).scalar_one()
        job.status = "ishlamoqda"  # oldingi jarayon shu vazifada o'lgan
        run.status = "ishlamoqda"
        await db.commit()
    async with TestSessionLocal() as db:
        picked = await va.pick_run(db, now=at(23, 30))
    assert picked.id == run.id
    executor = va.RunExecutor(run.id, TestSessionLocal, analyzer=ScriptedAnalyzer(full_day_script(), campus["people"]),
                              source_factory=lambda nvr, camera: None)
    finished = await executor.execute()
    assert finished.status == "tugadi"
    left = await db_session.scalar(
        select(func.count()).select_from(VideoAnalysisJob).where(VideoAnalysisJob.run_id == run.id,
                                                                VideoAnalysisJob.status.in_(("navbatda", "ishlamoqda")))
    )
    assert left == 0


async def test_cancel_stops_run_without_aggregation(campus, db_session):
    async with TestSessionLocal() as db:
        run = await va.create_run(db, DAY, now=at(23, 0))
        run.cancel_requested = True
        await db.commit()
    executor = va.RunExecutor(run.id, TestSessionLocal, analyzer=ScriptedAnalyzer(full_day_script(), campus["people"]),
                              source_factory=lambda nvr, camera: None)
    await executor._refresh_cancel()
    result = await executor.execute()
    assert result.status == "bekor"
    assert await db_session.scalar(select(func.count()).select_from(DailyPersonCriteria)) == 0


async def test_deadline_skips_remaining_low_priority_jobs(campus, db_session):
    async with TestSessionLocal() as db:
        run = await va.create_run(db, DAY, now=at(23, 0))
    executor = va.RunExecutor(run.id, TestSessionLocal, analyzer=ScriptedAnalyzer(full_day_script(), campus["people"]),
                              source_factory=lambda nvr, camera: None)
    executor.deadline_passed = True  # muddat allaqachon o'tgan
    result = await executor.execute()
    assert result.stats["muddat_otdi_bekor"] == result.jobs_total


def test_run_deadline_rules():
    started = datetime.combine(DAY, time(20, 1), tzinfo=INSTITUTE_TZ)
    assert va.run_deadline(DAY, started) == datetime.combine(DAY + timedelta(days=1), time(8), tzinfo=INSTITUTE_TZ)
    late_start = datetime.combine(DAY + timedelta(days=3), time(10), tzinfo=INSTITUTE_TZ)
    assert va.run_deadline(DAY, late_start) == late_start + timedelta(hours=12)


async def test_pick_run_schedule(campus, db_session):
    today = business_today()
    before_start = datetime.combine(today, time(19, 0), tzinfo=INSTITUTE_TZ)
    async with TestSessionLocal() as db:
        run = await va.pick_run(db, now=before_start)
    # 20:00 dan oldin — bugun emas, kechagi (o'tkazib yuborilgan) kun.
    assert run.day == today - timedelta(days=1)
    async with TestSessionLocal() as db:
        await db.execute(VideoAnalysisRun.__table__.update().values(status="tugadi"))
        await db.commit()
        after_start = datetime.combine(today, time(20, 5), tzinfo=INSTITUTE_TZ)
        run = await va.pick_run(db, now=after_start)
    assert run.day == today
    assert run.window_end == datetime.combine(today, time(20), tzinfo=INSTITUTE_TZ).astimezone(timezone.utc)


async def test_pick_run_catches_up_missed_days_then_stops(campus, db_session, monkeypatch):
    monkeypatch.setattr(settings, "video_analysis_catchup_days", 1)
    today = business_today()
    now = datetime.combine(today, time(21, 0), tzinfo=INSTITUTE_TZ)
    days = []
    for _ in range(3):
        async with TestSessionLocal() as db:
            run = await va.pick_run(db, now=now)
            if run is None:
                break
            days.append(run.day)
            run.status = "tugadi"
            await db.commit()
    assert days == [today, today - timedelta(days=1)]


async def _observation_runs(db_session) -> set:
    db_session.expire_all()
    return set((await db_session.execute(select(VideoObservation.run_id).distinct())).scalars())


async def test_failed_recompute_keeps_previous_observations_then_retries(campus, db_session, monkeypatch):
    """Qayta hisoblash yiqilsa, kunning oldingi kuzatuvlari yo'qolmaydi;
    yiqilgan tahlil video qayta o'qilmasdan agregatsiyadan qayta uriniladi."""
    people = campus["people"]
    first = await run_day(full_day_script(), people)
    assert first.status == "tugadi"

    import app.batch.aggregate as aggregate

    real_aggregate = aggregate.aggregate_run

    async def broken(db, run, **kwargs):
        raise RuntimeError("agregatsiya yiqildi")

    monkeypatch.setattr(aggregate, "aggregate_run", broken)
    second = await run_day(full_day_script(), people)
    assert second.status == "xato" and "agregatsiya yiqildi" in second.error
    assert await _observation_runs(db_session) == {first.id, second.id}

    # Kutish oralig'i o'tmagan — qayta urinilmaydi.
    async with TestSessionLocal() as db:
        assert await va._run_for_day(db, DAY, second.finished_at + timedelta(minutes=5)) is None

    monkeypatch.setattr(aggregate, "aggregate_run", real_aggregate)
    later = second.finished_at + timedelta(minutes=settings.video_analysis_retry_minutes + 1)
    async with TestSessionLocal() as db:
        retried = await va._run_for_day(db, DAY, later)
    assert retried.id == second.id and retried.status == "navbatda"
    assert retried.stats["qayta_urinish"] == 1 and "agregatsiya yiqildi" in retried.stats["oldingi_xato"]

    analyzer = ScriptedAnalyzer(full_day_script(), people)
    finished = await va.RunExecutor(second.id, TestSessionLocal, analyzer=analyzer,
                                    source_factory=lambda nvr, camera: None).execute()
    assert finished.status == "tugadi" and finished.error is None
    assert analyzer.calls == {}  # video qayta o'qilmadi
    assert await _observation_runs(db_session) == {second.id}
    assert await db_session.scalar(select(func.count()).select_from(DailyPersonCriteria)) == 5


async def test_cancelled_recompute_keeps_previous_observations(campus, db_session):
    first = await run_day(full_day_script(), campus["people"])
    async with TestSessionLocal() as db:
        second = await va.create_run(db, DAY, now=at(23, 0))
        second.cancel_requested = True
        await db.commit()
    executor = va.RunExecutor(second.id, TestSessionLocal,
                              analyzer=ScriptedAnalyzer(full_day_script(), campus["people"]),
                              source_factory=lambda nvr, camera: None)
    await executor._refresh_cancel()
    assert (await executor.execute()).status == "bekor"
    assert first.id in await _observation_runs(db_session)


async def test_failed_day_retry_is_limited(campus, db_session, monkeypatch):
    monkeypatch.setattr(settings, "video_analysis_day_retries", 1)
    async with TestSessionLocal() as db:
        run = await va.create_run(db, DAY, now=at(23, 0))
        run.status, run.error = "xato", "Agregatsiya xatosi"
        run.finished_at = at(23, 30)
        run.stats = {**(run.stats or {}), "qayta_urinish": 1}
        await db.commit()
    async with TestSessionLocal() as db:
        assert await va._run_for_day(db, DAY, at(23, 0) + timedelta(days=1)) is None


async def test_cancelled_or_finished_day_is_not_retried(campus, db_session):
    async with TestSessionLocal() as db:
        failed = await va.create_run(db, DAY, now=at(23, 0))
        failed.status, failed.finished_at = "xato", at(23, 5)
        cancelled = await va.create_run(db, DAY, now=at(23, 0))
        cancelled.status, cancelled.finished_at = "bekor", at(23, 10)
        await db.commit()
    async with TestSessionLocal() as db:
        assert await va._run_for_day(db, DAY, at(23, 0) + timedelta(days=1)) is None


async def test_failed_run_without_jobs_gets_a_new_run(campus, db_session):
    """Bo'sh oyna bilan yiqilgan tahlil (vazifasiz) — oyna qaytadan hisoblanadi."""
    async with TestSessionLocal() as db:
        empty = await va.create_run(db, DAY, now=at(6, 0))
    assert empty.status == "xato" and empty.jobs_total == 0
    # finished_at — haqiqiy soat; kutish oralig'idan keyingi payt.
    later = empty.finished_at + timedelta(minutes=settings.video_analysis_retry_minutes + 1)
    async with TestSessionLocal() as db:
        fresh = await va._run_for_day(db, DAY, later)
    assert fresh.id != empty.id and fresh.status == "navbatda" and fresh.jobs_total > 0


async def _activate_all_criteria(db_session):
    from app.models import AIModuleConfig

    await db_session.execute(
        AIModuleConfig.__table__.update()
        .where(AIModuleConfig.code.in_((6, 7, 8, 9, 10, 15, 19, 21, 22)))
        .values(active=True)
    )
    await db_session.commit()


async def _daily(db_session) -> dict[str, DailyPersonCriteria]:
    db_session.expire_all()
    return {
        str(r.student_staff_id): r
        for r in (await db_session.execute(select(DailyPersonCriteria).where(DailyPersonCriteria.day == DAY))).scalars()
    }


async def test_every_finding_is_recorded_with_moment_and_camera(campus, db_session):
    """Har aniqlangan holat odam qatorida: kriteriya, sabab, payt, kamera."""
    await _activate_all_criteria(db_session)
    people, cams = campus["people"], campus["cam_ids"]
    await run_day(full_day_script(), people)
    daily = await _daily(db_session)

    def codes(key):
        return sorted(item["kod"] for item in daily[people[key]].details["dalillar"])

    assert codes("S2") == [8, 9, 10, 19]  # darsga kech, darsdan erta, xalatsiz, diqqat past
    assert codes("S3") == [7]  # darsda ko'rinmadi
    assert codes("X") == [6, 9, 15]  # ishga kech, ishdan erta, chekish
    assert codes("S1") == [7]  # 08:20 — talaba uchun kech (08:10 dan keyin)
    # O'qituvchi 9 ta o'rta klipning 2 tasida (22%), harakat 50: 0,4*22 + 0,6*50 = 39 < 40.
    assert codes("T") == [21]
    s2 = {item["kod"]: item for item in daily[people["S2"]].details["dalillar"]}
    assert s2[8]["kamera_id"] == str(cams["room"]) and datetime.fromisoformat(s2[8]["vaqt"]) == at(9, 15)
    assert "09:15" in s2[8]["sabab"] and "DI-101" in s2[8]["sabab"]
    assert datetime.fromisoformat(s2[19]["vaqt"]) == at(9, 27, 31)  # telefon ko'ringan payt
    x = {item["kod"]: item for item in daily[people["X"]].details["dalillar"]}
    assert x[6]["kamera_id"] == str(cams["door"]) and datetime.fromisoformat(x[6]["vaqt"]) == at(8, 40)
    assert x[15]["kamera_id"] == str(cams["yard"])
    # Sinovda manba yo'q — klip kesilmadi, sababi yozildi (natija baribir bor).
    assert all(item["klip"] is None and item.get("klip_xato") for item in daily[people["S2"]].details["dalillar"])


async def test_evidence_clips_are_cut_and_attached(campus, db_session):
    from app.batch import evidence

    await _activate_all_criteria(db_session)
    people = campus["people"]
    run = await run_day(full_day_script(), people)
    exported: list[tuple] = []

    class FakeSource:
        async def export(self, start, end, out, *, height, timeout):
            exported.append((start, end, height))
            out.write_bytes(b"\x00" * 4096)

    uploaded: list[int] = []

    async def fake_upload(data: bytes) -> str:
        uploaded.append(len(data))
        return f"video-tahlil/dalil/{len(uploaded)}.mp4"

    stats = await evidence.cut_evidence_clips(
        TestSessionLocal, run.id, source_factory=lambda nvr, camera: FakeSource(), uploader=fake_upload
    )
    assert stats["dalil_kliplari"] == len(exported) == len(uploaded) > 0 and stats["dalil_xato"] == 0
    half = timedelta(seconds=settings.video_evidence_clip_seconds / 2)
    assert all(end - start == 2 * half for start, end, _h in exported)

    daily = await _daily(db_session)
    items = [item for row in daily.values() for item in row.details["dalillar"]]
    assert items and all(item["klip"] for item in items)
    events = (await db_session.execute(select(Event).where(Event.module_code.in_((10, 15))))).scalars().all()
    assert events and all(e.clip_key and e.clip_status == "ok" for e in events)

    # Qayta ishga tushirish — kesilganlar qayta kesilmaydi.
    again = await evidence.cut_evidence_clips(
        TestSessionLocal, run.id, source_factory=lambda nvr, camera: FakeSource(), uploader=fake_upload
    )
    assert again == {"dalil_kliplari": 0}


def test_nearby_findings_share_one_clip():
    from app.batch.evidence import group_requests

    t = at(9, 0)
    requests = group_requests([
        ("cam-a", t, 7, ("qator", 1, 0)),
        ("cam-a", t + timedelta(seconds=20), 7, ("qator", 2, 0)),  # bitta klip
        ("cam-a", t + timedelta(seconds=90), 19, ("qator", 3, 0)),
        ("cam-b", t, 15, ("hodisa", 9)),
    ])
    assert [(r.camera_id, len(r.targets)) for r in requests] == [("cam-b", 1), ("cam-a", 2), ("cam-a", 1)]
    assert requests[0].priority == 0  # chekish birinchi


def test_analysis_window_for_today_ends_now():
    today = business_today()
    now = datetime.combine(today, time(15, 0), tzinfo=INSTITUTE_TZ)
    start, end = va.analysis_window(today, now=now)
    assert start == datetime.combine(today, time(7), tzinfo=INSTITUTE_TZ)
    assert end == now - timedelta(minutes=2)


async def test_old_observations_cleanup(campus, db_session):
    run = await run_day(full_day_script(), campus["people"])
    count = await db_session.scalar(select(func.count()).select_from(VideoObservation))
    assert count > 0
    async with TestSessionLocal() as db:
        removed = await va.cleanup_observations(
            db, now=datetime.combine(DAY + timedelta(days=settings.video_observation_retention_days + 2), time(12),
                                     tzinfo=INSTITUTE_TZ)
        )
    assert removed == count
    assert run.status == "tugadi"
