"""TT kriteriya 18 — talaba umumiy dress code (tanilgan talabalar uchun)."""

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone

import cv2
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
from app.services.event_bus import raise_event
from app.services.face_matching import CandidateMatrix, load_candidate_matrix_for_sweep
from app.services.face_recognition import detect_faces
from app.services.frame_grabber import grab_frame_pair
from app.services.pose_detection import NOSE, PoseLandmarks, detect_poses
from app.services.student_uniform_detection import is_uniform_compliant

logger = logging.getLogger("app.student_dress_code_ai")

STUDENT_DRESS_MODULE_CODE = 18
STUDENT_DRESS_MODULE_NAME = "Kiyim-bosh (dress code) umumiy"

_sweep_guard = SweepGuard("student_dress_code_ai")


async def _load_student_ids(db: AsyncSession) -> set[str]:
    result = await db.execute(select(StudentStaff.id).where(StudentStaff.type == "talaba"))
    return {str(row) for row in result.scalars().all()}


async def _recently_flagged(db: AsyncSession, camera_id) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.student_uniform_dedup_minutes)
    result = await db.execute(
        select(Event.id)
        .where(Event.module_code == STUDENT_DRESS_MODULE_CODE)
        .where(Event.camera_id == camera_id)
        .where(Event.occurred_at >= cutoff)
    )
    return result.scalar_one_or_none() is not None


def _decode(frame_bytes: bytes) -> np.ndarray | None:
    arr = np.frombuffer(frame_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _closest_pose(poses: list[PoseLandmarks], point: tuple[float, float]) -> PoseLandmarks | None:
    best, best_d = None, float("inf")
    for pose in poses:
        nose = pose.points[NOSE][:2]
        d = math.hypot(float(nose[0]) - point[0], float(nose[1]) - point[1])
        if d < best_d:
            best_d, best = d, pose
    return best


async def _student_uniform_violation(
    frame_bytes: bytes, candidates: CandidateMatrix, student_ids: set[str]
) -> bool:
    if candidates.is_empty or not student_ids:
        return False
    faces = await detect_faces(frame_bytes)
    if not faces:
        return False
    embeddings = np.stack([f.embedding for f in faces])
    matches = candidates.best_matches(embeddings, settings.attendance_ai_match_threshold)
    student_faces = [f for f, m in zip(faces, matches, strict=True) if m and m[0] in student_ids]
    if not student_faces:
        return False
    image = _decode(frame_bytes)
    poses = await detect_poses(frame_bytes)
    if image is None or not poses:
        return False
    for face in student_faces:
        x1, y1, x2, y2 = face.bbox
        center = ((x1 + x2) / 2 / image.shape[1], (y1 + y2) / 2 / image.shape[0])
        pose = _closest_pose(poses, center)
        if pose and not is_uniform_compliant(image, pose.points):
            return True
    return False


async def process_camera_frame_pair_for_student_dress(
    frame_a: bytes, frame_b: bytes, db: AsyncSession, camera: Camera, candidates: CandidateMatrix, student_ids: set[str]
) -> bool:
    if not await _student_uniform_violation(frame_b, candidates, student_ids):
        return False
    if not await _student_uniform_violation(frame_a, candidates, student_ids):
        return False
    if await _recently_flagged(db, camera.id):
        return False

    await raise_event(
        db,
        camera=camera,
        module_code=STUDENT_DRESS_MODULE_CODE,
        module_name=STUDENT_DRESS_MODULE_NAME,
        group="D",
        confidence=35,
        severity="past",
        frame_bytes=frame_b,
    )
    return True


async def run_student_dress_code_ai_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    async with session_factory() as db:
        if not await is_module_active(db, STUDENT_DRESS_MODULE_CODE):
            return 0
        result = await db.execute(
            select(Camera).where(Camera.status == "faol").where(camera_allows_module(STUDENT_DRESS_MODULE_CODE))
        )
        cameras = [c for c in result.scalars().all() if c.stream_url and is_reachable(c.last_seen_at)]
        candidates = await load_candidate_matrix_for_sweep(db)
        student_ids = await _load_student_ids(db)

    if not cameras or not student_ids:
        return 0

    async def _process_one(camera: Camera) -> bool:
        async with camera_sweep_slot():
            frames = await grab_frame_pair(camera.stream_url)
            if frames is None:
                return False
            async with session_factory() as camera_db:
                return await process_camera_frame_pair_for_student_dress(
                    frames[0], frames[1], camera_db, camera, candidates, student_ids
                )

    results = await asyncio.gather(*(_process_one(c) for c in cameras), return_exceptions=True)
    total = 0
    for camera, result in zip(cameras, results, strict=True):
        if isinstance(result, BaseException):
            logger.exception("student dress AI failed", extra={"camera_id": str(camera.id)}, exc_info=result)
            continue
        if result:
            total += 1
    return total


async def student_dress_code_ai_loop() -> None:
    while True:
        try:
            count = await _sweep_guard.run(run_student_dress_code_ai_sweep_once)
            if count:
                logger.info("student dress AI raised events", extra={"events": count})
        except Exception:
            logger.exception("student dress AI sweep failed")
        await asyncio.sleep(settings.student_uniform_ai_interval_seconds)
