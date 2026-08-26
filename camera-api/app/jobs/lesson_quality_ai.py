"""TT kriteriya 19 ("Talabaning darsga diqqati") va 21 ("O'qituvchi
faolligi") — combined into one sweep loop because both need the exact
same thing: an ACTIVE LessonSession window (teacher_id/camera_id/
scheduled_start_time set — see app/models/lesson_session.py — with "now"
falling inside [scheduled_start_time, scheduled_start_time +
settings.lesson_duration_minutes]) and frames grabbed from that
session's camera. Splitting these into two separate jobs would mean
grabbing frames from the same camera twice per tick for no reason — TT's
own category grouping (both are "3-E: Ta'lim jarayoni sifati" alongside
kriteriya 20 sleep detection and 22 teacher punctuality, already built)
supports treating them as one concern, not two.

Kriteriya 19 (student attention/diqqat): combines two EXISTING signals
rather than building a dedicated gaze-estimation model — head orientation
(reused from app/services/sleep_detection.py's frontality logic, the same
"is this face oriented toward the camera" proxy already validated there)
and phone visibility (reused from app/jobs/phone_ai.py's YOLO "cell
phone" detection — a real distraction signal, not a proxy). Honest scope
note: phone-visible is a FRAME-WIDE signal here, not attributed to a
specific student — associating a detected phone with a specific face
would need hand/proximity tracking this doesn't do, so every matched
student's score drops together if any phone is visible anywhere in
frame, whether or not they're the one holding it.

Kriteriya 21 (teacher activity/faollik): the pose closest to the
teacher's matched face (by nose-landmark-to-face-center distance) is
found independently in a ~1s frame pair, and the average per-landmark
displacement between those two readings becomes the activity signal —
more movement, higher score. No pose tracking (the "closest pose" in
frame_a and frame_b could, in principle, be different people if several
are near the teacher) — an accepted limitation, same class as
app/jobs/unauthorized_person_ai.py's lack of face tracking.

Both scores are RUNNING AVERAGES, sampled once per active sweep tick and
written to LessonSession.attention_score / teacher_activity_score. The
running sample count is kept in memory only (module-level dict, keyed by
LessonSession id — not persisted, resets on restart, same tradeoff as
app/jobs/crowd_density_ai.py's baseline history): a restart mid-lesson
makes the next sample count as the "first" one again rather than
resuming the true running average, which biases the score toward
whatever's sampled right after a restart. A real deployment tracking
this across restarts would need to persist the sample count, not just
the score — noted, not built, since it's a real but secondary gap.

Neither score is validated against real classroom footage or human-rated
engagement/activity — both are geometric proxies (frontality, phone
visibility, movement amount), not trained models, and should be read as
a decision-support signal for a human reviewer, not ground truth.
"""

import asyncio
import json
import logging
import math
from collections import defaultdict
from datetime import timedelta

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.jobs.camera_health import is_reachable
from app.jobs.module_status import any_module_active, is_module_active
from app.jobs.sweep_guard import SweepGuard
from app.jobs.phone_ai import PHONE_CLASS_ID
from app.models import LessonSession
from app.services.face_matching import CandidateMatrix, load_candidate_matrix_for_sweep
from app.services.face_recognition import detect_faces
from app.services.frame_grabber import grab_frame_pair
from app.services.object_detection import detect_objects
from app.services.pose_detection import NOSE, PoseLandmarks, detect_poses
from app.services.sleep_detection import is_plausible_frontal
from app.timezone import local_now

logger = logging.getLogger("app.lesson_quality_ai")

ATTENTION_MODULE_CODE = 19
TEACHER_ACTIVITY_MODULE_CODE = 21

_camera_semaphore = asyncio.Semaphore(settings.ai_sweep_camera_concurrency)
_sweep_guard = SweepGuard("lesson_quality_ai")

# {lesson_session_id: sample_count} — see module docstring's "kept in
# memory only" note.
_attention_sample_counts: dict[str, int] = defaultdict(int)
_activity_sample_counts: dict[str, int] = defaultdict(int)


async def _active_sessions(db: AsyncSession) -> list[LessonSession]:
    """Filtered in Python against the camera's excluded_module_codes —
    see app/jobs/teacher_punctuality_ai.py's _due_sessions for why that's
    fine here (LessonSession.camera is lazy="joined", "active right now"
    is always a small set). A session is skipped only if its camera
    excludes BOTH #19 and #21 — same "any" rule run_lesson_quality_ai_
    sweep_once itself already applies at the whole-sweep level."""
    now = local_now()
    result = await db.execute(
        select(LessonSession)
        .where(LessonSession.teacher_id.is_not(None))
        .where(LessonSession.camera_id.is_not(None))
        .where(LessonSession.scheduled_start_time.is_not(None))
    )
    active = []
    for row in result.scalars().all():
        if row.camera is None:
            continue
        excluded = set(row.camera.excluded_module_codes or [])
        if {ATTENTION_MODULE_CODE, TEACHER_ACTIVITY_MODULE_CODE}.issubset(excluded):
            continue
        end = row.scheduled_start_time + timedelta(minutes=settings.lesson_duration_minutes)
        if row.scheduled_start_time <= now <= end:
            active.append(row)
    return active


def _running_average_update(counts: dict[str, int], session_id: str, current_score: int, sample: float) -> int:
    count = counts.get(session_id, 0)
    new_count = count + 1
    new_avg = (current_score * count + sample) / new_count
    counts[session_id] = new_count
    return round(new_avg)


async def _sample_attention(frame_bytes: bytes, candidates) -> float | None:
    """None if no enrolled student was matched in this frame — nothing to
    sample this tick, not a zero score (a zero would incorrectly drag the
    running average down every time the classroom camera briefly sees no
    one)."""
    faces = await detect_faces(frame_bytes)
    if not faces:
        return None

    embeddings = np.stack([face.embedding for face in faces])
    matches = candidates.best_matches(embeddings, settings.attendance_ai_match_threshold)
    matched = [(face, match) for face, match in zip(faces, matches, strict=True) if match is not None]
    if not matched:
        return None

    phone_detections = await detect_objects(
        frame_bytes, class_ids=[PHONE_CLASS_ID], confidence=settings.phone_detection_confidence
    )
    phone_visible = len(phone_detections) > 0

    scores = []
    for face, _match in matched:
        if phone_visible:
            scores.append(settings.attention_score_phone_visible)
        elif is_plausible_frontal(face.landmarks_68):
            scores.append(settings.attention_score_frontal)
        else:
            scores.append(settings.attention_score_not_frontal)
    return sum(scores) / len(scores)


def _closest_pose_to_point(poses: list[PoseLandmarks], point: tuple[float, float]) -> PoseLandmarks | None:
    best: PoseLandmarks | None = None
    best_distance = float("inf")
    for pose in poses:
        nose = pose.points[NOSE][:2]
        distance = math.hypot(float(nose[0]) - point[0], float(nose[1]) - point[1])
        if distance < best_distance:
            best_distance = distance
            best = pose
    return best


def _pose_movement(pose_a: PoseLandmarks, pose_b: PoseLandmarks) -> float:
    """Average per-landmark displacement (normalized 0-1 coordinates)
    between two pose readings, counting only landmarks visible enough in
    BOTH."""
    displacements = []
    for i in range(pose_a.points.shape[0]):
        if (
            pose_a.points[i][3] >= settings.teacher_activity_min_visibility
            and pose_b.points[i][3] >= settings.teacher_activity_min_visibility
        ):
            dx = float(pose_a.points[i][0] - pose_b.points[i][0])
            dy = float(pose_a.points[i][1] - pose_b.points[i][1])
            displacements.append(math.hypot(dx, dy))
    if not displacements:
        return 0.0
    return sum(displacements) / len(displacements)


def _decoded_frame_size(frame_bytes: bytes) -> tuple[int, int] | None:
    arr = np.frombuffer(frame_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    height, width = img.shape[0], img.shape[1]
    return width, height


async def _sample_activity(frame_a: bytes, frame_b: bytes, teacher_embedding: list[float]) -> float | None:
    """None if the teacher's face couldn't be matched in frame_b, or no
    pose was found near them in either frame — nothing to sample this
    tick. Associates a detected FACE (InsightFace, pixel bbox) with a
    detected POSE (mediapipe, normalized landmarks) by normalizing the
    face's center using the frame's real dimensions — the two models
    don't share a coordinate system otherwise."""
    faces_b = await detect_faces(frame_b)
    if not faces_b:
        return None

    embeddings_b = np.stack([face.embedding for face in faces_b])
    teacher_only = CandidateMatrix(ids=["teacher"], matrix=np.array([teacher_embedding]))
    matches_b = teacher_only.best_matches(embeddings_b, settings.attendance_ai_match_threshold)
    teacher_face_b = next((face for face, match in zip(faces_b, matches_b, strict=True) if match is not None), None)
    if teacher_face_b is None:
        return None

    frame_size = _decoded_frame_size(frame_b)
    if frame_size is None:
        return None
    width, height = frame_size
    bbox = teacher_face_b.bbox
    reference_point = ((bbox[0] + bbox[2]) / 2 / width, (bbox[1] + bbox[3]) / 2 / height)

    poses_a = await detect_poses(frame_a)
    poses_b = await detect_poses(frame_b)
    if not poses_a or not poses_b:
        return None

    # Same reference point used for both frames — a simplifying
    # assumption that the teacher hasn't moved far position-wise in the
    # ~1s gap between frames, reasonable for this two-frame comparison.
    pose_a = _closest_pose_to_point(poses_a, reference_point)
    pose_b = _closest_pose_to_point(poses_b, reference_point)
    if pose_a is None or pose_b is None:
        return None

    movement = _pose_movement(pose_a, pose_b)
    return min(100.0, movement * settings.teacher_activity_scale)


async def process_lesson_session(
    session_row: LessonSession,
    frame_a: bytes,
    frame_b: bytes,
    db: AsyncSession,
    candidates,
    attention_module_active: bool = True,
    teacher_activity_module_active: bool = True,
) -> None:
    """Samples both scores for one active LessonSession and commits any
    update — either signal can independently be "nothing to sample this
    tick" (see _sample_attention/_sample_activity), in which case that
    score is simply left unchanged."""
    session_id = str(session_row.id)

    attention_sample = await _sample_attention(frame_b, candidates) if attention_module_active else None
    if attention_sample is not None:
        session_row.attention_score = _running_average_update(
            _attention_sample_counts, session_id, session_row.attention_score, attention_sample
        )

    teacher = session_row.teacher_ref
    if teacher_activity_module_active and teacher is not None and teacher.biometric_embedding:
        teacher_embedding = json.loads(teacher.biometric_embedding)
        activity_sample = await _sample_activity(frame_a, frame_b, teacher_embedding)
        if activity_sample is not None:
            session_row.teacher_activity_score = _running_average_update(
                _activity_sample_counts, session_id, session_row.teacher_activity_score, activity_sample
            )

    await db.commit()


async def run_lesson_quality_ai_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """Grabs a frame pair from every active LessonSession's camera and
    samples both scores — sessions run concurrently (bounded by
    _camera_semaphore), and the candidate matrix is loaded once for the
    whole sweep. See app/jobs/attendance_ai.py's
    run_attendance_ai_sweep_once, which this mirrors. Returns how many
    sessions got at least one score sampled this tick (not an event
    count — this job never raises Events, only updates scores)."""
    async with session_factory() as db:
        attention_module_active = await is_module_active(db, ATTENTION_MODULE_CODE)
        teacher_activity_module_active = await is_module_active(db, TEACHER_ACTIVITY_MODULE_CODE)
        if not attention_module_active and not teacher_activity_module_active:
            return 0
        sessions = await _active_sessions(db)
        candidates = await load_candidate_matrix_for_sweep(db)

    if not sessions:
        return 0

    async def _process_one(session_row: LessonSession) -> bool:
        camera = session_row.camera
        if camera is None or not camera.stream_url or not is_reachable(camera.last_seen_at):
            return False
        async with _camera_semaphore:
            frames = await grab_frame_pair(camera.stream_url)
        if frames is None:
            return False
        frame_a, frame_b = frames
        async with session_factory() as db:
            row = await db.get(LessonSession, session_row.id)
            if row is None:
                return False
            await process_lesson_session(
                row,
                frame_a,
                frame_b,
                db,
                candidates,
                attention_module_active,
                teacher_activity_module_active,
            )
        return True

    results = await asyncio.gather(*(_process_one(row) for row in sessions), return_exceptions=True)

    total = 0
    for row, result in zip(sessions, results, strict=True):
        if isinstance(result, BaseException):
            logger.exception("lesson quality task failed", extra={"lesson_session_id": str(row.id)}, exc_info=result)
            continue
        if result:
            total += 1
    return total


async def lesson_quality_ai_loop() -> None:
    while True:
        try:
            count = await _sweep_guard.run(run_lesson_quality_ai_sweep_once)
            if count:
                logger.info("lesson quality sweep sampled sessions", extra={"sessions": count})
        except Exception:
            logger.exception("lesson quality sweep failed")
        await asyncio.sleep(settings.lesson_quality_ai_interval_seconds)
