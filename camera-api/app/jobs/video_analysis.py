"""Kunlik video tahlil orkestratori (ANALYSIS_MODE=kunlik).

Kun oxirida (settings.video_analysis_start, standart 20:00) o'sha kunning
NVR yozuvlari tahlil qilinadi:

  1. reja (app/batch/planner.py) — vazifalar bazaga yoziladi;
  2. vazifalar parallel bajariladi (umumiy chegara va har NVR'ning
     playback oqimlari chegarasi), har biri o'z kuzatuvlarini yozadi;
  3. hammasi tugagach — agregatsiya (app/batch/aggregate.py).

Jarayon qayta ishga tushsa, tugamagan kun davom ettiriladi (bajarilgan
vazifalar qayta o'qilmaydi). Server o'chib qolgan kunlar
video_analysis_catchup_days kun orqaga to'ldiriladi. Kunni qo'lda qayta
hisoblash — API (app/routers/video_analysis.py).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date as date_type, datetime, time as time_type, timedelta, timezone

from sqlalchemy import case, delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.batch.analyzer import Analyzer, JobContext
from app.batch.planner import Clip, LessonSlot, build_plan
from app.config import settings
from app.database import SessionLocal
from app.models import (
    AIModuleConfig,
    Camera,
    LessonSession,
    NvrDevice,
    VideoAnalysisJob,
    VideoAnalysisRun,
    VideoObservation,
)
from app.services.face_matching import load_candidate_matrix
from app.services.nvr.sources import source_for
from app.timezone import INSTITUTE_TZ, business_date, local_now

logger = logging.getLogger("app.video_analysis")

ACTIVE_RUN_STATUSES = ("navbatda", "ishlamoqda", "agregatsiya")
_OBSERVATION_BATCH = 500
# Vazifalar tartibi: muddat yetmay qolsa ham eng muhim kriteriyalar
# (darslar, keyin kunlik davomat) bajarilgan bo'lsin.
JOB_PRIORITY = {"dars": 0, "kirish": 1, "umumiy": 2, "chekish": 3}


def run_deadline(day: date_type, started_at: datetime) -> datetime:
    """Yangi vazifa boshlanmaydigan payt: ertasi kuni video_analysis_deadline.
    Kech boshlangan (o'tkazib yuborilgan kun, qo'lda) tahlil uchun —
    boshlanishidan 12 soat."""
    deadline = datetime.combine(day + timedelta(days=1), _clock(settings.video_analysis_deadline), tzinfo=INSTITUTE_TZ)
    if started_at >= deadline - timedelta(hours=2):
        return started_at + timedelta(hours=12)
    return deadline


def _clock(value: str) -> time_type:
    return time_type.fromisoformat(value.strip())


def analysis_window(day: date_type, *, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Kun oynasi (UTC): day_start .. video_analysis_start, institut soatida.
    Bugungi kun uchun oxiri hozirdan keyin bo'lmaydi (qo'lda ishga tushirish)."""
    start = datetime.combine(day, _clock(settings.video_analysis_day_start), tzinfo=INSTITUTE_TZ)
    end = datetime.combine(day, _clock(settings.video_analysis_start), tzinfo=INSTITUTE_TZ)
    now = now or datetime.now(timezone.utc)
    # NVR yozuvni bir necha daqiqa kechikib yopadi — oxirgi 2 daqiqa olinmaydi.
    end = min(end, now - timedelta(minutes=2))
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


async def lock_runs(db: AsyncSession) -> None:
    """Tahlil yaratishni ketma-ket qiladi (tranzaksiya oxirigacha). "Band
    emasmi?" tekshiruvi va yaratish orasida ikkinchi so'rov (ikki admin bir
    paytda yoki API va ai-worker) ikkinchi parallel tahlilni ochmasin."""
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('video_analysis_run'))"))


async def _active_codes(db: AsyncSession) -> set[int]:
    return set((await db.execute(select(AIModuleConfig.code).where(AIModuleConfig.active.is_(True)))).scalars())


async def create_run(
    db: AsyncSession,
    day: date_type,
    *,
    triggered_by: str = "tizim",
    now: datetime | None = None,
    window: tuple[datetime, datetime] | None = None,
) -> VideoAnalysisRun:
    """Kun uchun yangi tahlil: reja tuziladi va vazifalar yoziladi.

    Shu kunning oldingi tahlillari kuzatuvlari bu yerda O'CHIRILMAYDI:
    yangi tahlil yiqilsa yoki bekor qilinsa, kunning natijasi eski
    kuzatuvlardan qayta hisoblanishi mumkin bo'lsin. Ular yangi tahlil
    muvaffaqiyatli agregatsiya qilingandan keyin o'chiriladi
    (`supersede_old_runs`).
    `window` — kun oynasini qo'lda berish (yozib olingan videolar sinovi,
    scripts/video_tahlil.py); berilmasa sozlamadagi 07:00–20:00."""
    window_start, window_end = window if window is not None else analysis_window(day, now=now)
    run = VideoAnalysisRun(
        day=day,
        status="navbatda",
        window_start=window_start,
        window_end=window_end,
        triggered_by=triggered_by,
    )
    db.add(run)
    await db.flush()

    if window_end <= window_start:
        run.status = "xato"
        run.error = "Kun oynasi hali boshlanmagan"
        run.finished_at = datetime.now(timezone.utc)
        await db.commit()
        return run

    cameras = list(
        (
            await db.execute(
                select(Camera)
                .join(NvrDevice, NvrDevice.id == Camera.nvr_id)
                .where(Camera.status == "faol", NvrDevice.enabled.is_(True))
            )
        ).scalars().unique()
    )
    lessons = [
        LessonSlot(
            id=row.id,
            camera_id=row.camera_id,
            start=row.scheduled_start_time,
            end=row.scheduled_end_time or row.scheduled_start_time + timedelta(minutes=settings.lesson_duration_minutes),
        )
        for row in (
            await db.execute(
                select(LessonSession).where(
                    LessonSession.date == day,
                    LessonSession.camera_id.is_not(None),
                    LessonSession.scheduled_start_time.is_not(None),
                )
            )
        ).scalars().unique()
    ]
    plan = build_plan(
        cameras=cameras,
        lessons=lessons,
        window_start=window_start,
        window_end=window_end,
        active_codes=await _active_codes(db),
    )
    for job in plan.jobs:
        db.add(
            VideoAnalysisJob(
                run_id=run.id,
                camera_id=job.camera_id,
                lesson_session_id=job.lesson_session_id,
                kind=job.kind,
                clips=[clip.to_json() for clip in job.clips],
                start_at=job.start,
                end_at=job.end,
                frames_planned=job.frames,
                status="navbatda",
            )
        )
    run.jobs_total = len(plan.jobs)
    run.frames_planned = plan.frames
    run.stats = {"o'tkazib_yuborilgan_kameralar": len(plan.skipped_cameras)}
    await db.commit()
    logger.info(
        "video analysis run planned",
        extra={"day": day.isoformat(), "jobs": len(plan.jobs), "frames": plan.frames, "run_id": str(run.id)},
    )
    return run


class RunExecutor:
    def __init__(
        self,
        run_id: uuid.UUID,
        session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
        analyzer: Analyzer | None = None,
        source_factory=source_for,
    ) -> None:
        self.run_id = run_id
        self.session_factory = session_factory
        self.analyzer = analyzer or Analyzer()
        self.source_factory = source_factory
        self.cancelled = False
        # Muddat o'tdi: yangi vazifa boshlanmaydi, bori bilan agregatsiya.
        self.deadline_passed = False
        self.deadline: datetime | None = None
        self._nvr_slots: dict[uuid.UUID, asyncio.Semaphore] = {}
        self._evidence: set = set()

    def _nvr_slot(self, nvr: NvrDevice) -> asyncio.Semaphore:
        slot = self._nvr_slots.get(nvr.id)
        if slot is None:
            slot = asyncio.Semaphore(max(1, nvr.max_streams))
            self._nvr_slots[nvr.id] = slot
        return slot

    async def _refresh_cancel(self) -> None:
        async with self.session_factory() as db:
            flag = await db.scalar(select(VideoAnalysisRun.cancel_requested).where(VideoAnalysisRun.id == self.run_id))
        self.cancelled = bool(flag)

    async def _watch_cancel(self) -> None:
        while not self.cancelled:
            await asyncio.sleep(10)
            if self.deadline is not None and datetime.now(timezone.utc) >= self.deadline:
                self.deadline_passed = True
            try:
                await self._refresh_cancel()
            except Exception:  # noqa: BLE001
                logger.warning("cancel flag check failed", exc_info=True)

    async def execute(self) -> VideoAnalysisRun | None:
        async with self.session_factory() as db:
            run = await db.get(VideoAnalysisRun, self.run_id)
            if run is None:
                return None
            if run.status not in ACTIVE_RUN_STATUSES:
                return run
            run.status = "ishlamoqda"
            run.started_at = run.started_at or datetime.now(timezone.utc)
            # Oldingi jarayon o'chganda "ishlamoqda" qolgan vazifalar qayta navbatga.
            await db.execute(
                update(VideoAnalysisJob)
                .where(VideoAnalysisJob.run_id == run.id, VideoAnalysisJob.status == "ishlamoqda")
                .values(status="navbatda")
            )
            await db.commit()
            day = run.day
            self.deadline = run_deadline(day, run.started_at)
            candidates = await load_candidate_matrix(db)
            existing_evidence = (
                await db.execute(
                    select(VideoObservation.student_staff_id).where(
                        VideoObservation.run_id == run.id, VideoObservation.evidence_key.is_not(None)
                    )
                )
            ).scalars().all()
            self._evidence = {(day, str(pid)) for pid in existing_evidence}

        watcher = asyncio.create_task(self._watch_cancel())
        try:
            await self._run_jobs(day, candidates)
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)

        async with self.session_factory() as db:
            run = await db.get(VideoAnalysisRun, self.run_id)
            if self.deadline_passed and not self.cancelled:
                skipped = await db.execute(
                    update(VideoAnalysisJob)
                    .where(VideoAnalysisJob.run_id == run.id, VideoAnalysisJob.status == "navbatda")
                    .values(status="bekor", error="Muddat o'tdi — boshlanmadi")
                )
                run.stats = {**(run.stats or {}), "muddat_otdi_bekor": skipped.rowcount or 0}
                logger.warning(
                    "video analysis deadline passed; remaining jobs skipped",
                    extra={"run_id": str(self.run_id), "skipped": skipped.rowcount},
                )
            await self._refresh_counters(db, run)
            if self.cancelled or run.cancel_requested:
                run.status = "bekor"
                run.finished_at = datetime.now(timezone.utc)
                await db.execute(
                    update(VideoAnalysisJob)
                    .where(VideoAnalysisJob.run_id == run.id, VideoAnalysisJob.status == "navbatda")
                    .values(status="bekor")
                )
                await db.commit()
                return run
            if run.observations == 0:
                # Hech kim tanilmadi (yozuv yo'q, NVR sozlanmagan yoki kameralar
                # bog'lanmagan) — kunning mavjud natijalari (masalan real vaqt
                # rejimida yig'ilgan davomat) o'chirilmasin.
                run.status = "tugadi"
                run.finished_at = datetime.now(timezone.utc)
                run.stats = {
                    **(run.stats or {}),
                    "izoh": "Videoda hech kim tanilmadi — kunning natijalari o'zgartirilmadi",
                }
                await db.commit()
                logger.warning(
                    "video analysis produced no observations; results left untouched",
                    extra={"run_id": str(self.run_id), "jobs": run.jobs_total},
                )
                return run
            run.status = "agregatsiya"
            await db.commit()
            try:
                from app.batch.aggregate import aggregate_run

                stats = await aggregate_run(db, run)
            except Exception as exc:  # noqa: BLE001 — xato tahlil holatida ko'rinadi
                await db.rollback()
                logger.exception("video analysis aggregation failed", extra={"run_id": str(self.run_id)})
                run = await db.get(VideoAnalysisRun, self.run_id)
                run.status = "xato"
                run.error = f"Agregatsiya xatosi: {exc}"[:1000]
                run.finished_at = datetime.now(timezone.utc)
                await db.commit()
                return run
            # Video dalil (2 daqiqalik klip) — holatlar yozilgandan keyin.
            # Klip kesilmasa ham natija qoladi (rasm dalili va holat bor).
            try:
                from app.batch.evidence import cut_evidence_clips

                stats.update(
                    await cut_evidence_clips(self.session_factory, self.run_id, source_factory=self.source_factory)
                )
            except Exception:  # noqa: BLE001
                logger.exception("evidence clips failed", extra={"run_id": str(self.run_id)})
                stats["dalil_xato"] = stats.get("dalil_xato", 0) + 1
            run = await db.get(VideoAnalysisRun, self.run_id)
            await db.refresh(run)
            run.stats = {**(run.stats or {}), **stats}
            run.status = "tugadi"
            run.finished_at = datetime.now(timezone.utc)
            stale_keys = await supersede_old_runs(db, run)
            await db.commit()
            if stale_keys:
                from app.storage import delete_files_quietly

                await delete_files_quietly(stale_keys)
            logger.info("video analysis run finished", extra={"run_id": str(self.run_id), "day": run.day.isoformat()})
            return run

    async def _run_jobs(self, day: date_type, candidates) -> None:
        global_slot = asyncio.Semaphore(max(1, settings.video_analysis_concurrency))
        progress_every = 10
        done_since_refresh = 0
        priority = case(JOB_PRIORITY, value=VideoAnalysisJob.kind, else_=9)
        while not self.cancelled and not self.deadline_passed:
            async with self.session_factory() as db:
                pending = (
                    await db.execute(
                        select(VideoAnalysisJob.id)
                        .where(VideoAnalysisJob.run_id == self.run_id, VideoAnalysisJob.status == "navbatda")
                        .order_by(priority, VideoAnalysisJob.start_at)
                    )
                ).scalars().all()
            if not pending:
                return

            async def one(job_id: uuid.UUID) -> None:
                nonlocal done_since_refresh
                async with global_slot:
                    if self.cancelled or self.deadline_passed:
                        return
                    await self._run_job(job_id, day, candidates)
                done_since_refresh += 1
                if done_since_refresh >= progress_every:
                    done_since_refresh = 0
                    async with self.session_factory() as db:
                        run = await db.get(VideoAnalysisRun, self.run_id)
                        await self._refresh_counters(db, run)
                        await db.commit()

            await asyncio.gather(*(one(job_id) for job_id in pending))

    async def _run_job(self, job_id: uuid.UUID, day: date_type, candidates) -> None:
        async with self.session_factory() as db:
            job = await db.get(VideoAnalysisJob, job_id)
            if job is None or job.status != "navbatda":
                return
            camera = await db.get(Camera, job.camera_id) if job.camera_id else None
            nvr = await db.get(NvrDevice, camera.nvr_id) if camera is not None and camera.nvr_id else None
            teacher_id = None
            if job.lesson_session_id:
                lesson = await db.get(LessonSession, job.lesson_session_id)
                teacher_id = str(lesson.teacher_id) if lesson and lesson.teacher_id else None
            if camera is None or nvr is None:
                job.status = "xato"
                job.error = "Kamera yoki NVR topilmadi"
                await db.commit()
                return
            job.status = "ishlamoqda"
            job.attempts += 1
            job.started_at = datetime.now(timezone.utc)
            # Qayta urinish: oldingi urinishning yarim kuzatuvlari o'chiriladi.
            await db.execute(delete(VideoObservation).where(VideoObservation.job_id == job.id))
            await db.commit()
            clips = [Clip.from_json(raw) for raw in job.clips]
            context = JobContext(
                job_id=job.id,
                day=day,
                camera_id=camera.id,
                camera_name=camera.name,
                clips=clips,
                candidates=candidates,
                teacher_id=teacher_id,
                evidence_registry=self._evidence,
            )
            attempts = job.attempts
            run_id = job.run_id
            camera_id = camera.id

        try:
            source = self.source_factory(nvr, camera)
            async with self._nvr_slot(nvr):
                outcome = await self.analyzer.run(context, source, should_stop=lambda: self.cancelled)
        except Exception as exc:  # noqa: BLE001 — vazifa xatosi tahlilni to'xtatmaydi
            logger.warning(
                "video analysis job failed", extra={"job_id": str(job_id), "error": str(exc)}, exc_info=True
            )
            async with self.session_factory() as db:
                job = await db.get(VideoAnalysisJob, job_id)
                job.error = str(exc)[:1000]
                job.status = "xato" if attempts >= settings.video_analysis_max_attempts else "navbatda"
                job.finished_at = datetime.now(timezone.utc)
                await db.commit()
            return

        async with self.session_factory() as db:
            rows = [
                {
                    "run_id": run_id,
                    "job_id": job_id,
                    "day": day,
                    "camera_id": camera_id,
                    "student_staff_id": uuid.UUID(obs.person_id),
                    "seen_at": obs.seen_at,
                    "last_seen_at": obs.last_seen_at,
                    "similarity": obs.similarity,
                    "margin": obs.margin,
                    "frames": obs.frames,
                    "face_px": obs.face_px,
                    "frontal_frames": obs.frontal_frames,
                    "phone_frames": obs.phone_frames,
                    "coat_frames": obs.coat_frames,
                    "coat_white_frames": obs.coat_white_frames,
                    "coat_fraction": obs.coat_fraction,
                    "movement": obs.movement,
                    "clip_index": obs.clip_index,
                    "evidence_key": obs.evidence_key,
                }
                for obs in outcome.observations
            ]
            for start in range(0, len(rows), _OBSERVATION_BATCH):
                await db.execute(VideoObservation.__table__.insert(), rows[start : start + _OBSERVATION_BATCH])
            job = await db.get(VideoAnalysisJob, job_id)
            job.frames = outcome.frames
            job.faces = outcome.faces
            job.observations = len(rows)
            job.covered = outcome.covered
            job.result = outcome.result_json()
            job.finished_at = datetime.now(timezone.utc)
            if self.cancelled:
                job.status = "bekor"
            elif not outcome.covered:
                job.status = "yozuv_yoq"
                job.error = "; ".join(outcome.errors[-2:])[:1000] or "Oraliqda yozuv topilmadi"
            else:
                job.status = "tugadi"
                job.error = "; ".join(outcome.errors[-2:])[:1000] or None
            await db.commit()

    async def _refresh_counters(self, db: AsyncSession, run: VideoAnalysisRun) -> None:
        rows = (
            await db.execute(
                select(
                    VideoAnalysisJob.status,
                    func.count(),
                    func.coalesce(func.sum(VideoAnalysisJob.frames), 0),
                    func.coalesce(func.sum(VideoAnalysisJob.faces), 0),
                    func.coalesce(func.sum(VideoAnalysisJob.observations), 0),
                )
                .where(VideoAnalysisJob.run_id == run.id)
                .group_by(VideoAnalysisJob.status)
            )
        ).all()
        counts = {status: count for status, count, *_ in rows}
        run.jobs_done = counts.get("tugadi", 0) + counts.get("yozuv_yoq", 0)
        run.jobs_failed = counts.get("xato", 0)
        run.jobs_no_video = counts.get("yozuv_yoq", 0)
        run.frames_analyzed = int(sum(row[2] for row in rows))
        run.faces_detected = int(sum(row[3] for row in rows))
        run.observations = int(sum(row[4] for row in rows))


async def execute_run(run_id: uuid.UUID, session_factory: async_sessionmaker[AsyncSession] = SessionLocal):
    return await RunExecutor(run_id, session_factory).execute()


def _due_day(now: datetime) -> date_type | None:
    """Hozir qaysi kunning tahlili boshlanishi kerak (yoki None)."""
    local = now.astimezone(INSTITUTE_TZ)
    start = _clock(settings.video_analysis_start)
    today = business_date(now)
    if local.date() == today and local.time() >= start:
        return today
    if local.date() != today:
        # 00:00-06:00 — business_date kechagi kun; uning vaqti allaqachon o'tgan.
        return today
    return None


async def _run_for_day(db: AsyncSession, day: date_type, now: datetime) -> VideoAnalysisRun | None:
    """Kun uchun bajariladigan tahlil yoki None (kun yopilgan / kutish kerak).

    Ilgari kunda biror tahlil bo'lsa, u "xato" bilan tugagan bo'lsa ham kun
    yopilgan hisoblanardi — agregatsiya bir marta yiqilsa, kun natijasiz
    qolib ketardi va buni faqat qo'lda qayta ishga tushirish tuzatardi."""
    runs = list(
        (
            await db.execute(
                select(VideoAnalysisRun).where(VideoAnalysisRun.day == day).order_by(VideoAnalysisRun.created_at)
            )
        ).scalars()
    )
    if not runs:
        return await create_run(db, day, now=now)
    # Qaror oxirgi tahlil bo'yicha: "tugadi" — natija bor; "bekor" — admin
    # ataylab to'xtatgan (qo'lda qayta ishga tushiradi). Avval tugagan kunni
    # qo'lda qayta hisoblash yiqilsa ham qayta uriniladi.
    last = runs[-1]
    if last.status != "xato":
        return None
    if last.finished_at is not None and now - last.finished_at < timedelta(minutes=settings.video_analysis_retry_minutes):
        return None
    if last.jobs_total > 0:
        # Video o'qilgan, kuzatuvlar bazada — yiqilgan faqat agregatsiya.
        # O'sha tahlil qayta navbatga qo'yiladi: tugagan vazifalar qayta
        # o'qilmaydi, executor darhol agregatsiyaga o'tadi.
        retries = int((last.stats or {}).get("qayta_urinish", 0))
        if retries >= settings.video_analysis_day_retries:
            return None
        last.status = "navbatda"
        last.finished_at = None
        last.stats = {**(last.stats or {}), "qayta_urinish": retries + 1, "oldingi_xato": (last.error or "")[:300]}
        last.error = None
        await db.commit()
        logger.warning(
            "retrying failed video analysis run",
            extra={"run_id": str(last.id), "day": day.isoformat(), "attempt": retries + 1},
        )
        return last
    # Vazifasiz xato (masalan, kun oynasi bo'sh edi) — oyna qaytadan hisoblanadi.
    failed_in_a_row = 0
    for run in reversed(runs):
        if run.status != "xato":
            break
        failed_in_a_row += 1
    if failed_in_a_row > settings.video_analysis_day_retries:
        return None
    return await create_run(db, day, now=now)


async def pick_run(db: AsyncSession, *, now: datetime | None = None) -> VideoAnalysisRun | None:
    """Bajariladigan tahlil: avval tugamagani (qayta ishga tushganda davom),
    keyin vaqti kelgan kun, keyin o'tkazib yuborilgan kunlar. "Xato" bilan
    tugagan kun cheklangan marta qayta uriniladi (`_run_for_day`)."""
    now = now or datetime.now(timezone.utc)
    await lock_runs(db)
    unfinished = (
        await db.execute(
            select(VideoAnalysisRun)
            .where(VideoAnalysisRun.status.in_(ACTIVE_RUN_STATUSES))
            .order_by(VideoAnalysisRun.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if unfinished is not None:
        return unfinished
    due = _due_day(now)
    if due is None:
        due = business_date(now) - timedelta(days=1)
    candidates = [due - timedelta(days=offset) for offset in range(0, settings.video_analysis_catchup_days + 1)]
    for day in candidates:
        run = await _run_for_day(db, day, now)
        if run is not None:
            return run
    return None


async def _unreferenced_evidence(db: AsyncSession, *where) -> list[str]:
    """Shu shartdagi kuzatuvlarning hech bir hodisaga ilinmagan dalil rasmlari."""
    from app.models import Event

    return list(
        (
            await db.execute(
                select(VideoObservation.evidence_key).where(
                    *where,
                    VideoObservation.evidence_key.is_not(None),
                    ~select(Event.id).where(Event.snapshot_key == VideoObservation.evidence_key).exists(),
                )
            )
        ).scalars()
    )


async def supersede_old_runs(db: AsyncSession, run: VideoAnalysisRun) -> list[str]:
    """`run` kunning natijasini muvaffaqiyatli yozdi — shu kunning oldingi
    tahlillari kuzatuvlari endi kerak emas. Commit chaqiruvchida; qaytaradi —
    commit'dan keyin o'chiriladigan dalil rasmlari (eski hodisalar
    aggregate_run'da o'chgan, shuning uchun ularning rasmlari ham shu yerda)."""
    old_runs = select(VideoAnalysisRun.id).where(VideoAnalysisRun.day == run.day, VideoAnalysisRun.id != run.id)
    keys = await _unreferenced_evidence(db, VideoObservation.run_id.in_(old_runs))
    await db.execute(delete(VideoObservation).where(VideoObservation.run_id.in_(old_runs)))
    return keys


async def cleanup_observations(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Eski kuzatuvlar va ularning dalil rasmlari (hodisaga ilinmaganlari)."""
    from app.storage import delete_files_quietly

    now = now or datetime.now(timezone.utc)
    cutoff = business_date(now) - timedelta(days=settings.video_observation_retention_days)
    keys = await _unreferenced_evidence(db, VideoObservation.day < cutoff)
    result = await db.execute(delete(VideoObservation).where(VideoObservation.day < cutoff))
    await db.commit()
    if keys:
        await delete_files_quietly(keys)
    return result.rowcount or 0


async def video_analysis_loop() -> None:
    """Leader jarayonida (AI worker) ishlaydi — app/main.py."""
    logger.info("daily video analysis loop started", extra={"start": settings.video_analysis_start})
    last_cleanup: date_type | None = None
    while True:
        try:
            async with SessionLocal() as db:
                run = await pick_run(db)
                run_id = run.id if run is not None else None
            if run_id is not None:
                await execute_run(run_id)
                continue
            today = local_now().date()
            if last_cleanup != today:
                async with SessionLocal() as db:
                    removed = await cleanup_observations(db)
                if removed:
                    logger.info("old video observations removed", extra={"rows": removed})
                last_cleanup = today
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — sikl to'xtamasin
            logger.exception("daily video analysis loop iteration failed")
        await asyncio.sleep(settings.video_analysis_poll_seconds)
