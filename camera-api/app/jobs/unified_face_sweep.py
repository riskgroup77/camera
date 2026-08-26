"""Unified face-based AI sweep — TT kriteriya 1, 5, 6, 7, 20 in one pass.

Replaces four independent loops (attendance_ai, unauthorized_person_ai,
crowd_density_ai, vision_ai) that each grabbed frames and ran detect_faces()
on the same cameras every ~30s. One tick per camera:

  1. Grab frame(s) once (burst when entrance attendance or sleep needs it)
  2. Run detect_faces() once per distinct frame
  3. Feed results into each active module's existing processor

Non-face modules (fire, phone, pose, etc.) stay on their own loops.
"""

import asyncio
import logging

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.jobs.attendance_ai import (
    OFF_HOURS_MODULE_CODE,
    STAFF_ATTENDANCE_MODULE_CODE,
    STUDENT_ATTENDANCE_MODULE_CODE,
    process_camera_frame,
)
from app.jobs.camera_health import is_reachable
from app.jobs.crowd_density_ai import CROWD_MODULE_CODE, process_camera_frame_for_crowd
from app.jobs.module_status import camera_allows_module, is_module_active
from app.jobs.sweep_guard import SweepGuard
from app.jobs.unauthorized_person_ai import UNAUTHORIZED_MODULE_CODE, process_camera_frame_pair_for_unauthorized
from app.jobs.vision_ai import SLEEP_MODULE_CODE, process_camera_frame_for_sleep
from app.models import Camera
from app.services.face_matching import CandidateMatrix, load_candidate_matrix_for_sweep
from app.services.face_recognition import detect_faces
from app.services.frame_grabber import grab_frame, grab_frame_burst, grab_frame_pair

logger = logging.getLogger("app.unified_face_sweep")

_camera_semaphore = asyncio.Semaphore(settings.ai_sweep_camera_concurrency)
_sweep_guard = SweepGuard("unified_face_sweep")


def _allows(camera: Camera, module_code: int) -> bool:
    excluded = camera.excluded_module_codes
    return excluded is None or module_code not in excluded


async def _load_module_flags(db: AsyncSession) -> dict[str, bool]:
    return {
        "staff_attendance": await is_module_active(db, STAFF_ATTENDANCE_MODULE_CODE),
        "student_attendance": await is_module_active(db, STUDENT_ATTENDANCE_MODULE_CODE),
        "off_hours": await is_module_active(db, OFF_HOURS_MODULE_CODE),
        "crowd": await is_module_active(db, CROWD_MODULE_CODE),
        "unauthorized": await is_module_active(db, UNAUTHORIZED_MODULE_CODE),
        "sleep": await is_module_active(db, SLEEP_MODULE_CODE),
    }


def _any_face_module(flags: dict[str, bool]) -> bool:
    return any(
        flags[k]
        for k in ("staff_attendance", "student_attendance", "crowd", "unauthorized", "sleep")
    )


async def _process_camera(
    camera: Camera,
    flags: dict[str, bool],
    candidates: CandidateMatrix,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, int]:
    counts = {"attendance": 0, "crowd": 0, "unauthorized": 0, "sleep": 0}

    needs_attendance = (
        flags["staff_attendance"] and _allows(camera, STAFF_ATTENDANCE_MODULE_CODE)
    ) or (flags["student_attendance"] and _allows(camera, STUDENT_ATTENDANCE_MODULE_CODE))
    needs_crowd = flags["crowd"] and _allows(camera, CROWD_MODULE_CODE)
    needs_unauthorized = flags["unauthorized"] and _allows(camera, UNAUTHORIZED_MODULE_CODE)
    needs_sleep = flags["sleep"] and _allows(camera, SLEEP_MODULE_CODE)

    if not any((needs_attendance, needs_crowd, needs_unauthorized, needs_sleep)):
        return counts

    async with _camera_semaphore:
        primary_frame: bytes | None = None
        pair: tuple[bytes, bytes] | None = None
        sleep_frames: list[bytes] = []
        attendance_frames: list[bytes] = []

        if needs_sleep:
            sleep_frames = await grab_frame_burst(
                camera.stream_url,
                count=settings.sleep_confirmation_frame_count,
                gap_seconds=settings.sleep_confirmation_gap_seconds,
            )
            if sleep_frames:
                primary_frame = sleep_frames[0]

        if needs_unauthorized:
            pair = await grab_frame_pair(camera.stream_url)
            if pair and primary_frame is None:
                primary_frame = pair[1]

        if needs_attendance and camera.is_entrance:
            attendance_frames = await grab_frame_burst(
                camera.stream_url,
                settings.attendance_entrance_burst_frame_count,
                settings.attendance_entrance_burst_gap_seconds,
            )
            if attendance_frames and primary_frame is None:
                primary_frame = attendance_frames[0]
        elif (needs_attendance or needs_crowd) and primary_frame is None:
            primary_frame = await grab_frame(camera.stream_url)

        if primary_frame is None and not sleep_frames and pair is None:
            return counts

        primary_faces = await detect_faces(primary_frame) if primary_frame else []

        async with session_factory() as db:
            if needs_crowd and primary_frame is not None:
                if await process_camera_frame_for_crowd(primary_frame, db, camera, faces=primary_faces):
                    counts["crowd"] = 1

            if needs_attendance:
                frames_to_process = (
                    attendance_frames
                    if camera.is_entrance and attendance_frames
                    else ([primary_frame] if primary_frame else [])
                )
                credited: set[str] = set()
                for frame in frames_to_process:
                    frame_faces = primary_faces if frame is primary_frame else None
                    records = await process_camera_frame(
                        frame,
                        db,
                        camera,
                        candidates=candidates,
                        off_hours_module_active=flags["off_hours"],
                        staff_module_active=flags["staff_attendance"],
                        student_module_active=flags["student_attendance"],
                        faces=frame_faces,
                    )
                    credited.update(str(r.student_staff_id) for r in records)
                counts["attendance"] = len(credited)

            if needs_unauthorized and pair is not None:
                frame_a, frame_b = pair
                faces_b = primary_faces if frame_b is primary_frame else await detect_faces(frame_b)
                faces_a = await detect_faces(frame_a)
                if await process_camera_frame_pair_for_unauthorized(
                    frame_a,
                    frame_b,
                    db,
                    camera,
                    candidates=candidates,
                    faces_a=faces_a,
                    faces_b=faces_b,
                ):
                    counts["unauthorized"] = 1

            if needs_sleep and len(sleep_frames) >= 2:
                frames_faces = []
                for frame in sleep_frames:
                    if frame is primary_frame and primary_faces:
                        frames_faces.append(primary_faces)
                    else:
                        frames_faces.append(await detect_faces(frame))
                counts["sleep"] = await process_camera_frame_for_sleep(
                    sleep_frames,
                    db,
                    camera,
                    candidates=candidates,
                    frames_faces=frames_faces,
                )

    return counts


async def run_unified_face_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> dict[str, int]:
    async with session_factory() as db:
        flags = await _load_module_flags(db)
        if not _any_face_module(flags):
            return {}
        result = await db.execute(
            select(Camera)
            .where(Camera.status == "faol")
            .where(
                or_(
                    camera_allows_module(STAFF_ATTENDANCE_MODULE_CODE),
                    camera_allows_module(STUDENT_ATTENDANCE_MODULE_CODE),
                    camera_allows_module(CROWD_MODULE_CODE),
                    camera_allows_module(UNAUTHORIZED_MODULE_CODE),
                    camera_allows_module(SLEEP_MODULE_CODE),
                )
            )
        )
        cameras = [c for c in result.scalars().all() if c.stream_url and is_reachable(c.last_seen_at)]
        candidates = await load_candidate_matrix_for_sweep(db)

    totals = {"attendance": 0, "crowd": 0, "unauthorized": 0, "sleep": 0}
    if not cameras:
        return totals

    results = await asyncio.gather(
        *(_process_camera(camera, flags, candidates, session_factory) for camera in cameras),
        return_exceptions=True,
    )
    for camera, outcome in zip(cameras, results, strict=True):
        if isinstance(outcome, BaseException):
            logger.exception(
                "unified face sweep camera task failed",
                extra={"camera_id": str(camera.id)},
                exc_info=outcome,
            )
            continue
        for key, value in outcome.items():
            totals[key] += value
    return totals


async def unified_face_sweep_loop() -> None:
    while True:
        try:
            totals = await _sweep_guard.run(run_unified_face_sweep_once)
            if totals and any(totals.values()):
                logger.info("unified face sweep complete", extra=totals)
        except Exception:
            logger.exception("unified face sweep failed")
        await asyncio.sleep(settings.unified_face_sweep_interval_seconds)
