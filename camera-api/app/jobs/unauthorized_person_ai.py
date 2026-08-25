"""TT kriteriya 1 ("Notanish/begona shaxsni aniqlash") — flags any
detected face that does NOT match any enrolled person's embedding, using
the same InsightFace + app/services/face_matching.py pipeline as
app/jobs/attendance_ai.py, just inverted: attendance_ai credits a MATCH,
this raises an Event on the ABSENCE of one.

Runs across the same camera pool as the other sweep loops (every
faol+reachable camera) rather than restricting to "entrance" cameras
specifically — Camera.zone is free text with no reliable "this is an
entrance" signal to filter on, and the TT criterion itself (a stranger
appears anywhere in the building) doesn't require entrance-only coverage
to be useful. Per-camera scoping is a real admin config knob to add
later, not something to fake with brittle zone-name string matching now.

Grabs a PAIR of frames (grab_frame_pair, ~1s apart — the same pattern
app/jobs/fire_ai.py uses) and only raises when a face reads as unmatched
in BOTH. The real risk here isn't a blink, it's a single bad-angle or
poor-lighting frame making an ACTUALLY-enrolled person's embedding miss
attendance_ai_match_threshold and get flagged as a stranger — the same
class of failure sleep_detection.py documented for eye geometry, just for
face matching instead. Two independent frames both missing a match is
much less likely for a genuinely enrolled person than one frame failing
alone.

Honest scope note: with no re-identification/tracking (no DeepSORT/
ByteTrack here — see app/jobs/vision_ai.py's module docstring for the
same caveat), this can't tell "the same stranger is still there" from "a
different stranger walked into frame" a moment later. Dedup is per-camera
only (like fire_ai's), so a sustained unrecognized presence doesn't
re-raise every tick, but this also means two DIFFERENT strangers
back-to-back within the dedup window only produce one Event, not two —
an accepted limitation of face-matching without tracking, not a bug to
silently paper over.
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
from app.jobs.module_status import camera_allows_module, is_module_active
from app.models import Camera, Event
from app.schemas.event import EventOut
from app.services.face_matching import CandidateMatrix, load_candidate_matrix
from app.services.face_recognition import detect_faces
from app.services.frame_grabber import grab_frame_pair
from app.ws import manager

logger = logging.getLogger("app.unauthorized_person_ai")

UNAUTHORIZED_MODULE_CODE = 1
UNAUTHORIZED_MODULE_NAME = "Notanish/begona shaxsni aniqlash"

# See app/jobs/attendance_ai.py's _camera_semaphore docstring — same
# rationale, own semaphore so this job can't starve (or be starved by)
# the other AI sweep loops' camera slots.
_camera_semaphore = asyncio.Semaphore(settings.ai_sweep_camera_concurrency)


async def _recently_flagged(db: AsyncSession, camera_id) -> bool:
    """Dedup is per-camera only (like fire_ai.py's — no identity to key on
    for an unmatched face): a sustained unrecognized presence shouldn't
    re-raise an Event every single sweep tick."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.unauthorized_person_dedup_minutes)
    result = await db.execute(
        select(Event.id)
        .where(Event.module_code == UNAUTHORIZED_MODULE_CODE)
        .where(Event.camera_id == camera_id)
        .where(Event.occurred_at >= cutoff)
    )
    return result.scalar_one_or_none() is not None


def _has_unmatched_face(faces, candidates: CandidateMatrix) -> bool:
    if not faces:
        return False
    if candidates.is_empty:
        return True  # nobody enrolled at all -> every face is, by definition, unmatched
    embeddings = np.stack([face.embedding for face in faces])
    matches = candidates.best_matches(embeddings, settings.attendance_ai_match_threshold)
    return any(match is None for match in matches)


async def process_camera_frame_pair_for_unauthorized(
    frame_a: bytes, frame_b: bytes, db: AsyncSession, camera: Camera, candidates: CandidateMatrix | None = None
) -> bool:
    """Returns True if a (deduped) unauthorized-person Event was raised —
    see the module docstring for the two-frame confirmation rationale."""
    faces_b = await detect_faces(frame_b)
    if not faces_b:
        return False

    if candidates is None:
        candidates = await load_candidate_matrix(db)

    if not _has_unmatched_face(faces_b, candidates):
        return False  # everyone detected in frame_b matched an enrolled person

    faces_a = await detect_faces(frame_a)
    if not _has_unmatched_face(faces_a, candidates):
        return False  # frame_a had no unmatched face — frame_b's miss looks like a one-off angle/lighting glitch

    if await _recently_flagged(db, camera.id):
        return False

    event = Event(
        camera_id=camera.id,
        camera_name=camera.name,
        building=camera.building.name if camera.building else "",
        module_code=UNAUTHORIZED_MODULE_CODE,
        module_name=UNAUTHORIZED_MODULE_NAME,
        group="A",
        confidence=70,  # two independent frames agreed — still a real false-positive risk, see module docstring
        severity="yuqori",
        status="yangi",
    )
    db.add(event)
    await db.flush()
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
    return True


async def run_unauthorized_person_ai_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """Grabs a frame pair from every reachable 'faol' camera and checks it
    for unmatched faces — cameras run concurrently (bounded by
    _camera_semaphore), and the candidate matrix is loaded once for the
    whole sweep and shared across every camera task. See
    app/jobs/attendance_ai.py's run_attendance_ai_sweep_once, which this
    mirrors. Returns how many unauthorized-person Events were raised."""
    async with session_factory() as db:
        if not await is_module_active(db, UNAUTHORIZED_MODULE_CODE):
            return 0
        result = await db.execute(
            select(Camera).where(Camera.status == "faol").where(camera_allows_module(UNAUTHORIZED_MODULE_CODE))
        )
        cameras = [c for c in result.scalars().all() if c.stream_url and is_reachable(c.last_seen_at)]
        candidates = await load_candidate_matrix(db)

    if not cameras:
        return 0

    async def _process_one(camera: Camera) -> bool:
        async with _camera_semaphore:
            frames = await grab_frame_pair(camera.stream_url)
            if frames is None:
                return False
            frame_a, frame_b = frames
            async with session_factory() as camera_db:
                return await process_camera_frame_pair_for_unauthorized(
                    frame_a, frame_b, camera_db, camera, candidates
                )

    results = await asyncio.gather(*(_process_one(camera) for camera in cameras), return_exceptions=True)

    total = 0
    for camera, result in zip(cameras, results, strict=True):
        if isinstance(result, BaseException):
            logger.exception(
                "unauthorized person camera task failed", extra={"camera_id": str(camera.id)}, exc_info=result
            )
            continue
        if result:
            total += 1
    return total


async def unauthorized_person_ai_loop() -> None:
    while True:
        try:
            count = await run_unauthorized_person_ai_sweep_once()
            if count:
                logger.warning("unauthorized person AI sweep raised events", extra={"events": count})
        except Exception:
            logger.exception("unauthorized person AI sweep failed")
        await asyncio.sleep(settings.unauthorized_person_ai_interval_seconds)
