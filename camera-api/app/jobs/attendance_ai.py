"""Automatic attendance via face recognition — TT kriteriya 6 ("Xodim/
o'qituvchi davomati"), 7 ("Talaba davomati"), 8 ("Darsga kechikish") and,
for a check-in outside normal operating hours, 3 ("Notekis/kechki vaqtda
kirish" — raised as a real Event, since an off-hours entry is a security
signal, not just an attendance classification).

No external AI API of any kind: this runs entirely on the same local
InsightFace model app/services/face_recognition.py already uses for
biometric enrollment/compare (app/routers/students_staff.py). The loop
periodically grabs one frame (app/services/frame_grabber.py) from every
reachable camera, embeds EVERY face it finds (not just the largest —
found necessary from real classroom testing, see process_camera_frame()'s
docstring), and matches each one against every enrolled person's stored
embedding (StudentStaff.biometric_embedding).

Honest scope note on what this is and isn't: 1:N identification against
the whole enrolled population is a materially higher false-accept risk
than the 1:1 verification used at enrollment time — see
settings.attendance_ai_match_threshold's docstring in app/config.py. This
also only runs against a single sampled frame per camera per tick, not
continuous video — a real deployment tuning this for production accuracy
would want multi-frame consensus before writing a record, which this
does not yet do.

This writes directly to AttendanceRecord (same upsert-by-(person,date)
key as the existing manual POST /api/attendance) rather than going
through an HTTP round-trip to itself, since it runs in-process — see
app/routers/attendance.py's docstring for why that endpoint was
originally structured to allow either.
"""

import asyncio
import logging
from datetime import datetime, time as time_type

import numpy as np
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.jobs.camera_health import is_reachable
from app.jobs.module_status import camera_allows_module, is_module_active
from app.jobs.sweep_guard import SweepGuard
from app.jobs.sweep_concurrency import camera_sweep_slot
from app.models import AttendanceRecord, AuditLog, Camera, StudentStaff
from app.services.event_bus import raise_event
from app.services.face_matching import CandidateMatrix, find_best_match as _vectorized_find_best_match, load_candidate_matrix_for_sweep
from app.services.face_recognition import detect_faces
from app.services.frame_grabber import grab_frame_for_camera, grab_frame_burst_for_camera
from app.timezone import local_now, to_local

logger = logging.getLogger("app.attendance_ai")

OFF_HOURS_MODULE_CODE = 3
OFF_HOURS_MODULE_NAME = "Notekis/kechki vaqtda kirish"
# #6/#7 aren't gated the same way the other 13 jobs' single criterion is —
# this one sweep serves BOTH at once (same face-detection pass credits
# either a "xodim" or "talaba" match), so the sweep only skips entirely if
# an admin has turned off attendance tracking for both populations. #3
# (off-hours) is checked separately, per-sighting, in
# upsert_attendance_from_recognition — see its off_hours_module_active
# parameter.
STAFF_ATTENDANCE_MODULE_CODE = 6
STUDENT_ATTENDANCE_MODULE_CODE = 7

# Concurrent camera pipelines share app/jobs/sweep_concurrency.global_camera_semaphore
# (ai_global_sweep_concurrency in .env) — separate from face_recognition inference cap.
_sweep_guard = SweepGuard("attendance_ai")


def _is_off_hours(occurred_time: time_type) -> bool:
    start = time_type.fromisoformat(settings.attendance_off_hours_start)
    end = time_type.fromisoformat(settings.attendance_off_hours_end)
    return occurred_time < start or occurred_time >= end


def find_best_match(
    embedding: list[float], candidates: list[tuple[str, list[float]]]
) -> tuple[str, float] | None:
    """Thin, settings-bound wrapper kept here since app/jobs/vision_ai.py
    and the test suite call it as attendance_ai.find_best_match(embedding,
    candidates) relying on this module's own match threshold. The actual
    (vectorized) comparison lives in app/services/face_matching.py — sweep
    loops processing many faces/cameras should use CandidateMatrix /
    load_candidate_matrix directly instead of this one-off wrapper, which
    rebuilds a matrix from scratch on every call."""
    return _vectorized_find_best_match(embedding, candidates, settings.attendance_ai_match_threshold)


async def upsert_attendance_from_recognition(
    db: AsyncSession,
    student_staff_id: str,
    occurred_at: datetime,
    camera: Camera | None = None,
    off_hours_module_active: bool = True,
    frame_bytes: bytes | None = None,
) -> AttendanceRecord:
    """First sighting of the day (on ANY camera the attendance module runs
    on) inserts the row — sets check_in and the keldi/kech_keldi status.
    A later sighting the same day only ever advances check_out, and ONLY
    when it comes from a camera flagged Camera.is_exit — see that field's
    docstring. Without this gate, check_out was really just "last seen by
    ANY camera today," so being spotted once by an ordinary interior
    camera (a classroom, a hallway) silently doubled as "left the
    building." A later non-exit sighting still confirms the person is on
    campus (harmless no-op here) without touching check_out; status and
    check_in from the first sighting are always left alone either way.

    `camera` is optional only for callers (tests, mainly) that don't care
    about TT kriteriya 3 — passing it lets a genuine first-sighting-of-the-
    day check-in outside operating hours raise a real Event, exactly like
    any other AI-detected incident.

    `off_hours_module_active` defaults to True so direct/test callers keep
    working unchanged — the real sweep loop (run_attendance_ai_sweep_once)
    checks AIModuleConfig.active for module #3 ONCE per sweep and passes
    the result through here, rather than every call re-querying it.

    occurred_at is converted to the institute's local clock (see
    app/timezone.py) before its date/time are extracted — record_date is
    the LOCAL calendar day (not UTC's, which would misfile a real local
    midnight-to-5am arrival under yesterday's date), and occurred_time is
    what actually gets compared against attendance_ai_late_cutoff below,
    which is itself written as a local clock time."""
    local_occurred_at = to_local(occurred_at)
    record_date = local_occurred_at.date()
    occurred_time = local_occurred_at.time().replace(microsecond=0)
    cutoff = time_type.fromisoformat(settings.attendance_ai_late_cutoff)
    status = "kech_keldi" if occurred_time >= cutoff else "keldi"
    is_exit_sighting = camera is not None and camera.is_exit

    existing = (
        await db.execute(
            select(AttendanceRecord)
            .where(AttendanceRecord.student_staff_id == student_staff_id)
            .where(AttendanceRecord.date == record_date)
        )
    ).scalar_one_or_none()
    is_first_sighting_today = existing is None
    wrote_something = False

    if is_first_sighting_today:
        # on_conflict_do_nothing (not do_update): a concurrent sighting on
        # another camera may have inserted the row a moment ago — that
        # insert already owns check_in/status for today, so this one backs
        # off rather than overwriting it. The re-fetch below then behaves
        # exactly like a normal "not first sighting" call.
        stmt = (
            insert(AttendanceRecord)
            .values(
                student_staff_id=student_staff_id,
                date=record_date,
                status=status,
                check_in=occurred_time,
                check_out=None,
            )
            .on_conflict_do_nothing(index_elements=[AttendanceRecord.student_staff_id, AttendanceRecord.date])
            .returning(AttendanceRecord)
        )
        record = (await db.execute(stmt)).scalar_one_or_none()
        if record is None:
            existing = (
                await db.execute(
                    select(AttendanceRecord)
                    .where(AttendanceRecord.student_staff_id == student_staff_id)
                    .where(AttendanceRecord.date == record_date)
                )
            ).scalar_one()
        else:
            wrote_something = True
    if not wrote_something and existing is not None and is_exit_sighting:
        # populate_existing=True: without it, when this same day's row is
        # already in the session's identity map, SQLAlchemy's ORM-enabled
        # RETURNING silently keeps the stale cached object instead of
        # applying the just-updated check_out.
        stmt = (
            update(AttendanceRecord)
            .where(AttendanceRecord.id == existing.id)
            .values(check_out=occurred_time)
            .returning(AttendanceRecord)
        )
        record = (await db.execute(stmt.execution_options(populate_existing=True))).scalar_one()
        wrote_something = True
    elif not wrote_something:
        record = existing

    # Skip the extra lookup entirely for the common no-op case (a mid-day
    # sighting on an ordinary, non-exit camera writes nothing) — this
    # function runs once per matched face per sweep tick, so an unneeded
    # StudentStaff SELECT here isn't free at scale.
    needs_person = wrote_something or (
        is_first_sighting_today and off_hours_module_active and camera is not None and _is_off_hours(occurred_time)
    )
    person = await db.get(StudentStaff, student_staff_id) if needs_person else None
    if wrote_something:
        db.add(
            AuditLog(
                user_id=None,
                user_name="AI davomat tizimi",
                action=f"Yuzni tanish orqali davomat qayd etildi: {person.full_name if person else student_staff_id}",
                module="Talabalar",
                status="muvaffaqiyatli",
                ip="internal",
            )
        )

    if off_hours_module_active and camera is not None and is_first_sighting_today and _is_off_hours(occurred_time):
        await raise_event(
            db,
            camera=camera,
            module_code=OFF_HOURS_MODULE_CODE,
            module_name=OFF_HOURS_MODULE_NAME,
            group="A",
            confidence=100,  # this is a rule (a time comparison), not a model score
            severity="o'rta",
            frame_bytes=frame_bytes,
            person_name=person.full_name if person else None,
        )
    else:
        await db.commit()
    return record


async def process_camera_frame(
    frame_bytes: bytes,
    db: AsyncSession,
    camera: Camera | None = None,
    occurred_at: datetime | None = None,
    candidates: CandidateMatrix | None = None,
    off_hours_module_active: bool = True,
    staff_module_active: bool = True,
    student_module_active: bool = True,
    faces: list | None = None,
) -> list[AttendanceRecord]:
    """Checks EVERY face in the frame — not just the largest — and writes
    an attendance record for each one that matches an enrolled person.

    Found necessary from real classroom testing, not a hypothetical: a
    classroom camera routinely sees several people at once (the same
    observation that drove app/jobs/vision_ai.py to check every face
    rather than just one). The original single-largest-face version gave
    attendance credit only to whoever happened to be closest to the
    camera each tick — a second enrolled person standing right next to
    them, clearly visible, got nothing, tick after tick, with no error
    and no log line to explain why.

    Returns an empty list — not an error — for "no faces in frame" and
    "no confident matches", both routine outcomes for an unattended
    hallway/entrance camera most of the time. `camera` is passed straight
    through to upsert_attendance_from_recognition() for TT kriteriya 3
    (off-hours entry) — see its docstring.

    `candidates` lets a sweep loop load the enrolled-population matrix
    ONCE and pass the same CandidateMatrix into every camera's call this
    tick, instead of each camera re-querying and re-parsing the same
    embeddings from the DB (see app/services/face_matching.py's module
    docstring for why that matters at scale). Defaults to a self-load for
    simple/one-off callers (tests, mainly).

    `faces` lets app/jobs/unified_face_sweep.py pass pre-detected faces
    from a shared detect_faces() call — skips a redundant inference pass."""
    if faces is None:
        faces = await detect_faces(frame_bytes)
    if not faces:
        return []

    if candidates is None:
        candidates = await load_candidate_matrix_for_sweep(db)
    if candidates.is_empty:
        return []

    moment = occurred_at or local_now()
    embeddings = np.stack([face.embedding for face in faces])
    matches = candidates.best_matches(embeddings, settings.attendance_ai_match_threshold)

    matched_ids: set[str] = set()
    records: list[AttendanceRecord] = []
    for match in matches:
        if match is None:
            continue
        student_staff_id, similarity = match
        if student_staff_id in matched_ids:
            continue  # two faces in one frame matching the same person is a coincidence, not two sightings
        person_type = candidates.person_type(student_staff_id)
        if person_type == "xodim" and not staff_module_active:
            continue
        if person_type == "talaba" and not student_module_active:
            continue
        matched_ids.add(student_staff_id)
        logger.info(
            "attendance AI matched a face", extra={"student_staff_id": student_staff_id, "similarity": similarity}
        )
        records.append(
            await upsert_attendance_from_recognition(
                db, student_staff_id, moment, camera, off_hours_module_active, frame_bytes
            )
        )

    return records


async def run_attendance_ai_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """Grabs a frame from every reachable 'faol' camera and processes it —
    cameras run CONCURRENTLY (bounded by _camera_semaphore), not one at a
    time, and the candidate embedding matrix is loaded ONCE for the whole
    sweep and shared read-only across every camera task. See this
    module's _camera_semaphore docstring and app/services/face_matching.py
    for why both changes were necessary at hundreds of cameras / thousands
    of enrolled people — the old sequential, per-camera-reload version
    took N times as long as one camera at N cameras, which at 400 cameras
    meant sweeps stretching to minutes against a 30s target interval.

    Each camera gets its own DB session from session_factory (AsyncSession
    isn't safe for concurrent use across tasks) — defaults to the real
    app.database.SessionLocal; tests pass their own test session factory.
    A single camera's failure (bad stream, DB error) is logged and
    skipped, not allowed to fail the whole sweep. Returns how many people
    (across all cameras, this tick) got an attendance write — not how many
    frames matched, since one frame can match several people at once."""
    async with session_factory() as db:
        staff_module_active = await is_module_active(db, STAFF_ATTENDANCE_MODULE_CODE)
        student_module_active = await is_module_active(db, STUDENT_ATTENDANCE_MODULE_CODE)
        if not staff_module_active and not student_module_active:
            return 0
        off_hours_module_active = await is_module_active(db, OFF_HOURS_MODULE_CODE)
        result = await db.execute(
            select(Camera)
            .where(Camera.status == "faol")
            .where(
                or_(
                    camera_allows_module(STAFF_ATTENDANCE_MODULE_CODE),
                    camera_allows_module(STUDENT_ATTENDANCE_MODULE_CODE),
                )
            )
        )
        cameras = [c for c in result.scalars().all() if c.stream_url and is_reachable(c.last_seen_at)]
        candidates = await load_candidate_matrix_for_sweep(db)

    if not cameras or candidates.is_empty:
        return 0

    async def _process_one(camera: Camera) -> int:
        async with camera_sweep_slot():
            if camera.is_entrance:
                frames = await grab_frame_burst_for_camera(
                    camera,
                    settings.attendance_entrance_burst_frame_count,
                    settings.attendance_entrance_burst_gap_seconds,
                )
            else:
                frame = await grab_frame_for_camera(camera)
                frames = [frame] if frame is not None else []
            if not frames:
                return 0

            async with session_factory() as camera_db:
                # ANY frame in the burst matching a person is enough to
                # credit them once — not majority voting like vision_ai's
                # sleep confirmation, since a burst here exists purely to
                # maximize the chance of catching someone only briefly in
                # frame, and upsert_attendance_from_recognition is already
                # idempotent per (person, day), so re-processing the same
                # person across multiple frames just advances check_out
                # rather than double-crediting them.
                credited: set[str] = set()
                for frame in frames:
                    records = await process_camera_frame(
                        frame,
                        camera_db,
                        camera,
                        candidates=candidates,
                        off_hours_module_active=off_hours_module_active,
                        staff_module_active=staff_module_active,
                        student_module_active=student_module_active,
                    )
                    credited.update(str(r.student_staff_id) for r in records)
                return len(credited)

    results = await asyncio.gather(*(_process_one(camera) for camera in cameras), return_exceptions=True)

    match_count = 0
    for camera, result in zip(cameras, results, strict=True):
        if isinstance(result, BaseException):
            logger.exception(
                "attendance AI camera task failed", extra={"camera_id": str(camera.id)}, exc_info=result
            )
            continue
        match_count += result
    return match_count


async def attendance_ai_loop() -> None:
    while True:
        try:
            count = await _sweep_guard.run(run_attendance_ai_sweep_once)
            if count:
                logger.info("attendance AI sweep complete", extra={"matches": count})
        except Exception:
            logger.exception("attendance AI sweep failed")
        await asyncio.sleep(settings.attendance_ai_interval_seconds)
