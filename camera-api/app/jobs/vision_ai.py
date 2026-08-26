"""TT kriteriya 20 ("Talabaning uxlab qolishi") — eye-closure (EAR) sweep
across every reachable camera. See app/services/sleep_detection.py for the
per-frame detection method (EAR threshold + a head-pose plausibility gate)
and its honest accuracy caveats.

Runs its own camera sweep (separate from app/jobs/attendance_ai.py's)
rather than sharing a single frame grab — checks EVERY face in the frame
(a classroom camera routinely sees many people; attendance matching only
cares about the largest/nearest face at a check-in point), a genuinely
different requirement.

Grabs a BURST of frames per tick (app/services/frame_grabber.py's
grab_frame_burst — settings.sleep_confirmation_frame_count frames,
settings.sleep_confirmation_gap_seconds apart, ~3s total by default) and
raises an Event only for an identity that reads as asleep in at least
settings.sleep_confirmation_majority_ratio of the frames they actually
appear in. This replaced an earlier "asleep in exactly 2 frames, both
required" design: requiring literal unanimity across only 2 samples meant
one noisy frame (see sleep_detection.py's documented oblique-angle
failure mode) could flip the result either way, in either direction. A
majority vote across more samples is statistically sturdier — a real
blink is well under a second and won't cost a person more than one frame
out of four at these gaps, while someone genuinely asleep reads as closed
consistently. Now cheap to do at all because app/services/stream_cache.py
already keeps a persistent decoder per stream — grabbing 4 frames costs
nothing beyond 2 did.

Known limitation, unchanged from the earlier 2-frame version: there is no
cross-frame face tracker (no DeepSORT/ByteTrack here), so an
UNIDENTIFIED sleeping face's votes are pooled under a single "unknown"
bucket per camera per tick rather than tracked per physical person. Two
different unidentified people each closing their eyes in one frame out of
four could theoretically combine into a false majority for that bucket.
This is a real, accepted gap — solving it needs actual multi-object
tracking, out of scope here — and is exactly why identified sleepers
should be treated as the trustworthy signal from this module; an
unidentified "asleep" Event is weaker evidence than an identified one.
"""

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.jobs.camera_health import is_reachable
from app.jobs.module_status import camera_allows_module, is_module_active
from app.jobs.sweep_guard import SweepGuard
from app.jobs.sweep_concurrency import camera_sweep_slot
from app.models import Camera, Event, StudentStaff
from app.schemas.event import EventOut
from app.services.face_matching import CandidateMatrix, load_candidate_matrix_for_sweep
from app.services.face_recognition import detect_faces
from app.services.frame_grabber import grab_frame_burst
from app.services.sleep_detection import is_asleep
from app.ws import manager

logger = logging.getLogger("app.vision_ai")

SLEEP_MODULE_CODE = 20
SLEEP_MODULE_NAME = "Talabaning uxlab qolishi"

# See app/jobs/attendance_ai.py's _camera_semaphore docstring — same
# rationale, own semaphore so a slow/backed-up vision_ai sweep can't starve
# attendance_ai's camera slots or vice versa.
_sweep_guard = SweepGuard("vision_ai")


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


def _tally_votes(
    frames_faces: list[list], candidates: CandidateMatrix
) -> tuple[dict[str | None, int], dict[str | None, int]]:
    """For each frame's detected faces, matches identities and tallies how
    many frames each identity (or None, for unidentified) appeared in
    (`appearances`) versus read as asleep in (`asleep_votes`).

    A KNOWN identity matched by more than one face in the same frame (a
    rare double-detection glitch) counts once, via AND-then-OR being
    unnecessary there — but every unidentified face is checked
    individually and pooled with OR logic (the frame counts as an
    "unidentified sleeper" appearance if ANY unidentified face in it read
    as asleep) — see the module docstring's "known limitation" note on
    why unidentified faces are pooled into one None bucket at all rather
    than tracked individually; collapsing to just the first one checked
    would throw away real signal for no reason, since (unlike a real
    duplicate identity match) there's no way to know two None faces are
    "the same" vs genuinely different unidentified people either way."""
    appearances: dict[str | None, int] = defaultdict(int)
    asleep_votes: dict[str | None, int] = defaultdict(int)

    for faces in frames_faces:
        if not faces:
            continue
        embeddings = np.stack([face.embedding for face in faces])
        matches = candidates.best_matches(embeddings, settings.attendance_ai_match_threshold)

        known_seen_this_frame: set[str] = set()
        unidentified_present = False
        unidentified_asleep = False

        for face, match in zip(faces, matches, strict=True):
            if match is not None:
                identity = match[0]
                if identity in known_seen_this_frame:
                    continue
                known_seen_this_frame.add(identity)
                appearances[identity] += 1
                if is_asleep(face.landmarks_68):
                    asleep_votes[identity] += 1
            else:
                unidentified_present = True
                if is_asleep(face.landmarks_68):
                    unidentified_asleep = True

        if unidentified_present:
            appearances[None] += 1
            if unidentified_asleep:
                asleep_votes[None] += 1

    return appearances, asleep_votes


async def process_camera_frame_for_sleep(
    frames: list[bytes],
    db: AsyncSession,
    camera: Camera,
    candidates: CandidateMatrix | None = None,
    frames_faces: list[list] | None = None,
) -> int:
    """Runs face detection on every frame in the burst, tallies per-identity
    asleep-vote ratios (see _tally_votes), and raises a (deduped) Event for
    each identity whose ratio meets settings.sleep_confirmation_
    majority_ratio — see the module docstring for the full rationale.
    Returns how many Events were raised.

    Requires at least 2 frames with any detected face to make a call at
    all (a single frame can't distinguish a blink from real closure no
    matter the vote ratio). `candidates` lets a sweep loop share one
    CandidateMatrix across every camera this tick instead of each camera
    re-querying/re-parsing the same embeddings — see
    app/services/face_matching.py. Defaults to a self-load for simple/
    one-off callers (tests, mainly)."""
    if len(frames) < 2:
        return 0

    if candidates is None:
        candidates = await load_candidate_matrix_for_sweep(db)

    if frames_faces is None:
        frames_faces = [await detect_faces(frame) for frame in frames]
    appearances, asleep_votes = _tally_votes(frames_faces, candidates)

    raised = 0
    for identity, total in appearances.items():
        if total < 2:
            continue  # appeared in only one frame — not enough evidence either way
        votes = asleep_votes.get(identity, 0)
        ratio = votes / total
        if ratio < settings.sleep_confirmation_majority_ratio:
            continue

        person_name = None
        if identity is not None:
            person = await db.get(StudentStaff, identity)
            person_name = person.full_name if person else None

        if await _recently_flagged(db, camera.id, person_name):
            continue

        # Scales with how consistently the identity read as asleep across
        # the burst — a bare-majority ratio (just above the threshold)
        # reads as more tentative than every sampled frame agreeing.
        confidence = min(95, round(60 + ratio * 35))

        event = Event(
            camera_id=camera.id,
            camera_name=camera.name,
            building=camera.building.name if camera.building else "",
            module_code=SLEEP_MODULE_CODE,
            module_name=SLEEP_MODULE_NAME,
            group="E",
            confidence=confidence,
            severity="past",  # low: sleeping isn't dangerous, even when confirmed across a multi-frame burst
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
    """Grabs a multi-frame burst from every reachable 'faol' camera and
    checks it for sleeping faces — cameras run concurrently (bounded by
    _camera_semaphore), and the candidate matrix is loaded once for the
    whole sweep and shared across every camera task. See
    app/jobs/attendance_ai.py's run_attendance_ai_sweep_once, which this
    mirrors. Returns how many sleep Events were raised."""
    async with session_factory() as db:
        if not await is_module_active(db, SLEEP_MODULE_CODE):
            return 0
        result = await db.execute(
            select(Camera).where(Camera.status == "faol").where(camera_allows_module(SLEEP_MODULE_CODE))
        )
        cameras = [c for c in result.scalars().all() if c.stream_url and is_reachable(c.last_seen_at)]
        candidates = await load_candidate_matrix_for_sweep(db)

    if not cameras:
        return 0

    async def _process_one(camera: Camera) -> int:
        async with camera_sweep_slot():
            frames = await grab_frame_burst(
                camera.stream_url,
                count=settings.sleep_confirmation_frame_count,
                gap_seconds=settings.sleep_confirmation_gap_seconds,
            )
            if len(frames) < 2:
                return 0
            async with session_factory() as camera_db:
                return await process_camera_frame_for_sleep(frames, camera_db, camera, candidates)

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
            count = await _sweep_guard.run(run_vision_ai_sweep_once)
            if count:
                logger.info("vision AI sweep complete", extra={"sleep_events": count})
        except Exception:
            logger.exception("vision AI sweep failed")
        await asyncio.sleep(settings.vision_ai_interval_seconds)
