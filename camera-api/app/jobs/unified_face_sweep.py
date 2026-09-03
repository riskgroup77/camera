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
from app.jobs.sweep_concurrency import camera_sweep_slot
from app.jobs.unauthorized_person_ai import UNAUTHORIZED_MODULE_CODE, process_camera_frame_pair_for_unauthorized
from app.jobs.vision_ai import SLEEP_MODULE_CODE, process_camera_frame_for_sleep
from app.models import Camera
from app.services.face_matching import CandidateMatrix, load_candidate_matrix_for_sweep
from app.services.face_recognition import detect_faces
from app.services.frame_grabber import (
    grab_frame_burst_for_camera,
    grab_frame_for_camera,
    grab_frame_pair_for_camera,
)
from app.services.sweep_result_cache import record_camera_sweep

logger = logging.getLogger("app.unified_face_sweep")

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

    # Entrance/exit cameras get attendance checked by their own much
    # faster-cadence sweep instead (app/jobs/attendance_ai.py's
    # run_entrance_exit_attendance_sweep_once, registered separately in
    # ai_scheduler.py) — excluded here so the same camera isn't processed
    # for attendance twice, once on each cadence.
    needs_attendance = not (camera.is_entrance or camera.is_exit) and (
        (flags["staff_attendance"] and _allows(camera, STAFF_ATTENDANCE_MODULE_CODE))
        or (flags["student_attendance"] and _allows(camera, STUDENT_ATTENDANCE_MODULE_CODE))
    )
    needs_crowd = flags["crowd"] and _allows(camera, CROWD_MODULE_CODE)
    needs_unauthorized = flags["unauthorized"] and _allows(camera, UNAUTHORIZED_MODULE_CODE)
    needs_sleep = flags["sleep"] and _allows(camera, SLEEP_MODULE_CODE)

    if not any((needs_attendance, needs_crowd, needs_unauthorized, needs_sleep)):
        return counts

    async with camera_sweep_slot():
        primary_frame: bytes | None = None
        pair: tuple[bytes, bytes] | None = None
        sleep_frames: list[bytes] = []

        if needs_sleep:
            sleep_frames = await grab_frame_burst_for_camera(
                camera,
                count=settings.sleep_confirmation_frame_count,
                gap_seconds=settings.sleep_confirmation_gap_seconds,
            )
            if sleep_frames:
                primary_frame = sleep_frames[0]

        if needs_unauthorized:
            # Reuse the sleep burst when there is one instead of grabbing a
            # SECOND set of frames from the same camera a second later.
            # Both modules are active on most cameras, so this used to cost
            # 6 frames and 6 detect_faces calls per camera (4 + 2) plus ~4s
            # of gap-sleeping, when 4 frames already satisfy both.
            #
            # The unauthorized check wants two frames far enough apart that
            # one bad angle can't fail both (see its module docstring). The
            # burst's first and last are sleep_confirmation_gap_seconds x
            # (count-1) apart — 3s by default, i.e. MORE separation than
            # grab_frame_pair_for_camera's own 1s, so this is a stronger
            # signal, not a weaker one.
            if len(sleep_frames) >= 2:
                pair = (sleep_frames[0], sleep_frames[-1])
            else:
                pair = await grab_frame_pair_for_camera(camera)
                if pair and primary_frame is None:
                    primary_frame = pair[1]

        # needs_attendance is never true for an is_entrance/is_exit camera
        # (see above) — those get burst-grabbed by their own dedicated,
        # faster sweep instead, so a single frame is always enough here.
        if (needs_attendance or needs_crowd) and primary_frame is None:
            primary_frame = await grab_frame_for_camera(camera)

        if primary_frame is None and not sleep_frames and pair is None:
            return counts

        # Every frame this camera grabbed (primary, the unauthorized pair,
        # the sleep burst) needs its own detect_faces() call, but they're
        # independent inference calls on independent frames — nothing here
        # depends on another frame's result. Running them one `await` at a
        # time (as this used to) served them strictly sequentially even
        # though face_inference_gate (app/services/inference_gate.py)
        # allows many calls to run concurrently: measured on production,
        # that turned a ~1.4s-per-call cost into ~10s of serialized wall
        # clock for a single camera needing sleep+unauthorized (up to 6
        # calls back to back), which was the dominant cost behind a
        # measured AI-sweep backlog going far past its configured
        # interval. Deduplicated by object identity (frames reused as
        # `primary_frame` are detected once, not twice) and gathered
        # concurrently instead — same results, a fraction of the wall time.
        frames_needing_faces: list[bytes] = []
        if primary_frame is not None:
            frames_needing_faces.append(primary_frame)
        if needs_unauthorized and pair is not None:
            for frame in pair:
                if not any(frame is f for f in frames_needing_faces):
                    frames_needing_faces.append(frame)
        if needs_sleep and len(sleep_frames) >= 2:
            for frame in sleep_frames:
                if not any(frame is f for f in frames_needing_faces):
                    frames_needing_faces.append(frame)

        detected = await asyncio.gather(*(detect_faces(frame) for frame in frames_needing_faces))
        faces_by_frame_id = {id(frame): faces for frame, faces in zip(frames_needing_faces, detected, strict=True)}

        primary_faces = faces_by_frame_id.get(id(primary_frame), []) if primary_frame is not None else []

        async with session_factory() as db:
            if needs_crowd and primary_frame is not None:
                if await process_camera_frame_for_crowd(primary_frame, db, camera, faces=primary_faces):
                    counts["crowd"] = 1

            if needs_attendance and primary_frame is not None:
                records = await process_camera_frame(
                    primary_frame,
                    db,
                    camera,
                    candidates=candidates,
                    off_hours_module_active=flags["off_hours"],
                    staff_module_active=flags["staff_attendance"],
                    student_module_active=flags["student_attendance"],
                    faces=primary_faces,
                )
                counts["attendance"] = len({str(r.student_staff_id) for r in records})

            if needs_unauthorized and pair is not None:
                frame_a, frame_b = pair
                faces_a = faces_by_frame_id[id(frame_a)]
                faces_b = faces_by_frame_id[id(frame_b)]
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
                frames_faces = [faces_by_frame_id[id(frame)] for frame in sleep_frames]
                counts["sleep"] = await process_camera_frame_for_sleep(
                    sleep_frames,
                    db,
                    camera,
                    candidates=candidates,
                    frames_faces=frames_faces,
                )

        modules_run: list[str] = []
        if needs_attendance:
            modules_run.append("attendance")
        if needs_crowd:
            modules_run.append("crowd")
        if needs_unauthorized:
            modules_run.append("unauthorized")
        if needs_sleep:
            modules_run.append("sleep")
        events_raised = sum(counts.values())
        await record_camera_sweep(
            str(camera.id),
            face_count=len(primary_faces),
            modules=modules_run,
            events_raised=events_raised,
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

        # Ro'yxat juda kichik bo'lsa 1-modulni shu yerda o'chiramiz.
        # Haqiqiy himoya process_camera_frame_pair_for_unauthorized
        # ichida, lekin bayroqni shu yerda tushirish kadr JUFTLIGINI
        # olishning oldini oladi — u har kamera uchun qo'shimcha ikki
        # kadr va bir necha soniya kutish demakdir.
        if flags["unauthorized"] and len(candidates.ids) < settings.unauthorized_min_enrolled:
            logger.warning(
                "unauthorized-person check disabled this sweep: enrolled roster too small",
                extra={"enrolled": len(candidates.ids), "required": settings.unauthorized_min_enrolled},
            )
            flags["unauthorized"] = False

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
