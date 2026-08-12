"""TT kriteriya 20 ("Talabaning uxlab qolishi") — eye-closure (EAR) sweep
across every reachable camera. See app/services/sleep_detection.py for the
detection method and its honest accuracy caveats.

Runs its own camera sweep (separate from app/jobs/attendance_ai.py's)
rather than sharing a single frame grab — checks EVERY face in the frame
(a classroom camera routinely sees many people; attendance matching only
cares about the largest/nearest face at a check-in point), a genuinely
different requirement worth the modest extra ffmpeg overhead of a second
per-camera frame grab every sweep tick.

Grabs a PAIR of frames per tick (app/services/frame_grabber.py's
grab_frame_pair, ~1s apart — the same two-frame pattern app/jobs/fire_ai.py
uses) and only raises an Event when the same identity reads as asleep in
BOTH. Found necessary from real testing: a single frame can misread a
normal blink, or an oblique head angle (someone looking down at a desk
instead of the camera) as "asleep" — see sleep_detection.py's module
docstring for the concrete EAR numbers that motivated this. Requiring two
independent readings ~1s apart filters out both without needing head-pose
detection: a blink doesn't last a full second, and while a bad-angle
glitch CAN repeat across both frames (this isn't a fix for camera
placement itself), a momentary one won't.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.jobs.camera_health import is_reachable
from app.models import Camera, Event, StudentStaff
from app.schemas.event import EventOut
from app.services.face_matching import CandidateMatrix, load_candidate_matrix
from app.services.face_recognition import detect_faces
from app.services.frame_grabber import grab_frame_pair
from app.services.sleep_detection import is_asleep
from app.ws import manager

logger = logging.getLogger("app.vision_ai")

SLEEP_MODULE_CODE = 20
SLEEP_MODULE_NAME = "Talabaning uxlab qolishi"

# See app/jobs/attendance_ai.py's _camera_semaphore docstring — same
# rationale, own semaphore so a slow/backed-up vision_ai sweep can't starve
# attendance_ai's camera slots or vice versa.
_camera_semaphore = asyncio.Semaphore(settings.ai_sweep_camera_concurrency)


async def _recently_flagged(db: AsyncSession, camera_id, person_name: str | None) -> bool:
    """Dedup key is the person's name when identified (so the same person
    isn't re-flagged every tick while they stay asleep); falls back to
    "any unidentified sleeper at this camera" when not — without that
    fallback, an unmatched person staying asleep would raise a fresh Event
    every single sweep tick indefinitely, since there'd be no name to key
    on."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.sleep_dedup_minutes)
    stmt = select(Event.id).where(Event.module_code == SLEEP_MODULE_CODE).where(Event.occurred_at >= cutoff)
    if person_name is not None:
        stmt = stmt.where(Event.person_name == person_name)
    else:
        stmt = stmt.where(Event.camera_id == camera_id).where(Event.person_name.is_(None))
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


def _asleep_identities(faces, candidates: CandidateMatrix) -> set[str | None]:
    """Returns the set of identities (student_staff_id, or None for an
    unidentified face) that read as asleep among the given faces —
    used to check the SAME identity shows up asleep in both frames."""
    asleep_faces = [face for face in faces if is_asleep(face.landmarks_68)]
    if not asleep_faces:
        return set()
    embeddings = np.stack([face.embedding for face in asleep_faces])
    matches = candidates.best_matches(embeddings, settings.attendance_ai_match_threshold)
    return {match[0] if match is not None else None for match in matches}


async def process_camera_frame_for_sleep(
    frame_a: bytes, frame_b: bytes, db: AsyncSession, camera: Camera, candidates: CandidateMatrix | None = None
) -> int:
    """Checks every face in frame_b, raises a (deduped) Event for each one
    whose eyes read as closed AND whose same identity also read as asleep
    in frame_a — see the module docstring for why the second frame is
    required. Returns how many Events were raised.

    `candidates` lets a sweep loop share one CandidateMatrix across every
    camera this tick instead of each camera re-querying/re-parsing the
    same embeddings — see app/services/face_matching.py. Defaults to a
    self-load for simple/one-off callers (tests, mainly)."""
    faces_b = await detect_faces(frame_b)
    if not faces_b:
        return 0

    if candidates is None:
        candidates = await load_candidate_matrix(db)
    faces_a = await detect_faces(frame_a)
    confirmed_identities = _asleep_identities(faces_a, candidates)

    asleep_faces_b = [face for face in faces_b if is_asleep(face.landmarks_68)]
    matches_b: list[tuple[str, float] | None] = []
    if asleep_faces_b:
        embeddings_b = np.stack([face.embedding for face in asleep_faces_b])
        matches_b = candidates.best_matches(embeddings_b, settings.attendance_ai_match_threshold)

    raised = 0
    for match in matches_b:
        student_staff_id = match[0] if match is not None else None

        if student_staff_id not in confirmed_identities:
            continue  # not asleep in the earlier frame too — likely a blink or a one-off glitch

        person_name = None
        if student_staff_id is not None:
            person = await db.get(StudentStaff, student_staff_id)
            person_name = person.full_name if person else None

        if await _recently_flagged(db, camera.id, person_name):
            continue

        event = Event(
            camera_id=camera.id,
            camera_name=camera.name,
            building=camera.building.name if camera.building else "",
            module_code=SLEEP_MODULE_CODE,
            module_name=SLEEP_MODULE_NAME,
            group="E",
            confidence=80,  # two independent frames agreed — more than a single-frame reading, still modest
            severity="past",  # low: sleeping isn't dangerous, even when confirmed across two frames
            person_name=person_name,
            status="yangi",
        )
        db.add(event)
        await db.flush()  # populate event.id/occurred_at before building EventOut
        event_out = EventOut(
            id=str(event.id),
            timestamp=event.occurred_at.strftime("%Y-%m-%d %H:%M"),
            camera_id=str(event.camera_id) if event.camera_id else "",
            camera_name=event.camera_name,
            building=event.building,
            module_code=event.module_code,
            module_name=event.module_name,
            group=event.group,
            confidence=event.confidence,
            severity=event.severity,
            status=event.status,
            person_name=event.person_name,
            reviewed_by=event.reviewed_by,
        )
        await db.commit()
        await manager.broadcast(event_out.model_dump(by_alias=True))
        raised += 1

    return raised


async def run_vision_ai_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """Grabs a frame pair from every reachable 'faol' camera and checks it
    for sleeping faces — cameras run concurrently (bounded by
    _camera_semaphore), and the candidate matrix is loaded once for the
    whole sweep and shared across every camera task. See
    app/jobs/attendance_ai.py's run_attendance_ai_sweep_once, which this
    mirrors. Returns how many sleep Events were raised."""
    async with session_factory() as db:
        result = await db.execute(select(Camera).where(Camera.status == "faol"))
        cameras = [c for c in result.scalars().all() if c.stream_url and is_reachable(c.last_seen_at)]
        candidates = await load_candidate_matrix(db)

    if not cameras:
        return 0

    async def _process_one(camera: Camera) -> int:
        async with _camera_semaphore:
            frames = await grab_frame_pair(camera.stream_url)
            if frames is None:
                return 0
            frame_a, frame_b = frames
            async with session_factory() as camera_db:
                return await process_camera_frame_for_sleep(frame_a, frame_b, camera_db, camera, candidates)

    results = await asyncio.gather(*(_process_one(camera) for camera in cameras), return_exceptions=True)

    total = 0
    for camera, result in zip(cameras, results, strict=True):
        if isinstance(result, BaseException):
            logger.exception("vision AI camera task failed", extra={"camera_id": str(camera.id)}, exc_info=result)
            continue
        total += result
    return total


async def vision_ai_loop() -> None:
    while True:
        try:
            count = await run_vision_ai_sweep_once()
            if count:
                logger.info("vision AI sweep complete", extra={"sleep_events": count})
        except Exception:
            logger.exception("vision AI sweep failed")
        await asyncio.sleep(settings.vision_ai_interval_seconds)
