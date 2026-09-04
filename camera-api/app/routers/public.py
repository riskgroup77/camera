"""Public (no-auth) endpoints backing the Monitoring page — camera/src/pages/public/MonitoringPage.tsx.

Honest scope note: cameras here have no real link to a faculty/course/group
in the schema (a Camera is just a physical device in a Building/zone), so
unlike the admin-only endpoints this never exposes ip/port/rtsp_path/
credentials, and the frontend can't filter by faculty/course/group the way
an earlier mock-data version pretended to.
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, case, extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.dependencies import require_monitoring_access
from app.jobs.camera_health import is_reachable, is_video_flowing
from app.models import AttendanceRecord, Building, Camera, Event, LessonSession, StudentStaff
from app.pagination import Page, PageParams, build_page, paginate
from app.rate_limit import limiter
from app.schemas.public import CameraAnalysisStatusOut, DetectedFaceOut, LiveDetectionOut, PublicCameraOut, PublicStatsOut, PublicTopStudentOut
from app.services.face_matching import load_candidate_matrix_cached
from app.services.face_recognition import detect_faces
from app.services.inference_gate import PRIORITY_LIVE
from app.services.frame_grabber import frame_wait_seconds_for_camera, grab_frame_for_camera
from app.services.image_size import jpeg_dimensions
from app.services.sleep_detection import is_asleep
from app.services.sweep_result_cache import get_camera_sweep

logger = logging.getLogger("app.public")
from app.timezone import local_now

# Himoya BUTUN router darajasida: endpointlarga birma-bir qo'shilsa,
# keyin qo'shiladigan yangi endpoint ochiq qolib ketishi mumkin edi —
# audit aynan shunday teshikni topdi.
router = APIRouter(
    prefix="/api/public",
    tags=["public"],
    dependencies=[Depends(require_monitoring_access)],
)


def _is_live_expr():
    """SQL mirror of app/jobs/camera_health.py's is_reachable() — lets the
    'JONLI'/'OFLAYN' filter and the live/offline stats counts be computed
    in the database instead of fetching every camera row into Python."""
    freshness_cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.camera_health_freshness_seconds)
    return and_(Camera.status == "faol", Camera.last_seen_at.isnot(None), Camera.last_seen_at >= freshness_cutoff)


def _to_public_camera(camera: Camera) -> PublicCameraOut:
    # "live" requires BOTH the admin's intent (status='faol') AND a recent
    # successful reachability check (app/jobs/camera_health.py) — status
    # alone used to be enough, which meant a camera whose cable was
    # unplugged kept showing JONLI here indefinitely.
    live = camera.status == "faol" and is_reachable(camera.last_seen_at)
    # Tasvir alohida o'lchanadi — camera_health.is_video_flowing izohiga
    # qarang. Erishilmaydigan kamera uchun bu savol ma'nosiz, shuning
    # uchun u True qoladi va faqat `status` gapiradi.
    has_video = is_video_flowing(camera.last_frame_at) if live else True
    return PublicCameraOut(
        id=str(camera.id),
        name=camera.name,
        building=camera.building.name if camera.building else "",
        zone=camera.zone,
        status="live" if live else "offline",
        has_video=has_video,
        stream_url=camera.stream_url,
    )


@router.get("/cameras", response_model=Page[PublicCameraOut])
async def list_public_cameras(
    db: Annotated[AsyncSession, Depends(get_db)],
    params: Annotated[PageParams, Depends()],
    search: str | None = None,
    building: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> Page[PublicCameraOut]:
    """Paginated (see app/pagination.py's Page/PageParams) so the response
    stays bounded as the institute's camera count grows — search/building/
    status are applied in SQL rather than over the full table so filtering
    still only pulls back one page's worth of rows."""
    stmt = select(Camera).options(selectinload(Camera.building)).order_by(Camera.name)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Camera.name.ilike(like), Camera.zone.ilike(like)))
    if building:
        stmt = stmt.where(Camera.building.has(Building.name == building))
    if status_filter == "live":
        stmt = stmt.where(_is_live_expr())
    elif status_filter == "offline":
        stmt = stmt.where(~_is_live_expr())

    rows, total = await paginate(db, stmt, params)
    return build_page([_to_public_camera(c) for c in rows], total, params)


@router.get("/stats", response_model=PublicStatsOut)
async def get_public_stats(db: Annotated[AsyncSession, Depends(get_db)]) -> PublicStatsOut:
    # Local calendar day, not UTC's — matches how attendance_ai.py files
    # AttendanceRecord.date (see app/timezone.py's module docstring), and
    # avoids "today's" stats reading as yesterday's during the institute's
    # early-morning local hours.
    today = local_now().date()
    start_of_today = local_now().replace(hour=0, minute=0, second=0, microsecond=0)

    total_students = (
        await db.execute(select(func.count()).select_from(StudentStaff).where(StudentStaff.type == "talaba"))
    ).scalar_one()

    today_statuses = (
        await db.execute(select(AttendanceRecord.status).where(AttendanceRecord.date == today))
    ).scalars().all()
    present = sum(1 for s in today_statuses if s in ("keldi", "kech_keldi"))
    late = sum(1 for s in today_statuses if s == "kech_keldi")
    absent = sum(1 for s in today_statuses if s == "kelmadi")

    sleep_incidents = (
        await db.execute(
            select(func.coalesce(func.sum(LessonSession.sleep_incidents), 0)).where(LessonSession.date == today)
        )
    ).scalar_one()

    violations = (
        await db.execute(
            select(func.count())
            .select_from(Event)
            .where(Event.occurred_at >= start_of_today)
            .where(Event.severity.in_(["o'rta", "yuqori"]))
        )
    ).scalar_one()

    live_cameras = (
        await db.execute(select(func.count()).select_from(Camera).where(_is_live_expr()))
    ).scalar_one()
    total_cameras = (await db.execute(select(func.count()).select_from(Camera))).scalar_one()
    buildings = (
        await db.execute(select(Building.name).distinct().order_by(Building.name))
    ).scalars().all()

    return PublicStatsOut(
        total_students=total_students,
        present=present,
        absent=absent,
        late=late,
        sleep_incidents=sleep_incidents,
        violations=violations,
        live_cameras=live_cameras,
        offline_cameras=total_cameras - live_cameras,
        buildings=list(buildings),
    )


@router.get("/top-students", response_model=list[PublicTopStudentOut])
async def list_top_students(db: Annotated[AsyncSession, Depends(get_db)]) -> list[PublicTopStudentOut]:
    """Bu oyning davomat foizi bo'yicha eng yaxshi 10 ta talaba — kamida
    bitta davomat yozuvi bo'lganlar orasidan (bo'sh tarixli talabalar
    reytingga qo'shilmaydi, aks holda ular soxta 0% bilan pastda emas,
    umuman ko'rinmaydi degan ma'noni anglatadi)."""
    now = local_now()  # local month/year — AttendanceRecord.date is filed under the local calendar day
    present_count = func.sum(
        case((AttendanceRecord.status.in_(["keldi", "kech_keldi"]), 1), else_=0)
    )
    total_count = func.count(AttendanceRecord.id)
    rate = (present_count * 100.0) / total_count

    stmt = (
        select(StudentStaff.id, StudentStaff.full_name, StudentStaff.group_or_position, rate.label("rate"))
        .join(AttendanceRecord, AttendanceRecord.student_staff_id == StudentStaff.id)
        .where(StudentStaff.type == "talaba")
        .where(extract("year", AttendanceRecord.date) == now.year)
        .where(extract("month", AttendanceRecord.date) == now.month)
        .group_by(StudentStaff.id, StudentStaff.full_name, StudentStaff.group_or_position)
        .order_by(rate.desc())
        .limit(10)
    )
    result = await db.execute(stmt)
    return [
        PublicTopStudentOut(
            id=str(student_id),
            name=full_name,
            group=group_or_position,
            attendance_rate=round(rate_value),
        )
        for student_id, full_name, group_or_position, rate_value in result.all()
    ]


@router.get("/cameras/{camera_id}/live-detection", response_model=LiveDetectionOut)
@limiter.limit("20/minute")
async def get_live_detection(
    request: Request, camera_id: str, db: Annotated[AsyncSession, Depends(get_db)]
) -> LiveDetectionOut:
    """A one-shot snapshot of what the AI currently sees on this camera —
    grabs a fresh frame and runs the same detection/matching InsightFace
    pipeline app/jobs/attendance_ai.py and vision_ai.py use, but
    synchronously and without writing an AttendanceRecord/Event. Backs the
    face-box overlay on the live video (both the public MonitoringPage and
    the admin CameraConfigDetailModal poll this every few seconds while a
    camera is actually being watched).

    Deliberately NOT the same pipeline as the persistent one: this checks
    is_asleep() on a single frame, with none of vision_ai.py's two-frame
    confirmation (see that module's docstring for why that check exists) —
    a stray "asleep" box here is a harmless visual flicker that clears on
    the next poll, not a stored alert, so the extra frame grab isn't
    worth doubling this endpoint's cost for. Rate-limited since, unlike
    this router's other endpoints, each call spawns an ffmpeg process and
    runs a real inference pass — cheap enough for a human watching one
    camera, not something to leave wide open on a no-auth endpoint.
    """
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi")

    try:
        frame_bytes = await grab_frame_for_camera(
            camera, wait_seconds=frame_wait_seconds_for_camera(camera)
        )
        if frame_bytes is None:
            return LiveDetectionOut(frame_width=0, frame_height=0, faces=[])

        # Header parse instead of a full cv2.imdecode: this handler is async
        # and polled repeatedly while an operator watches a camera, so a
        # synchronous full-resolution decode here blocked the event loop on
        # every poll — for two integers. See app/services/image_size.py.
        dims = jpeg_dimensions(frame_bytes)
        frame_width, frame_height = dims if dims else (0, 0)

        faces = await detect_faces(frame_bytes, priority=PRIORITY_LIVE)
        candidates = await load_candidate_matrix_cached(db)

        faces_out = []
        for face in faces:
            match = candidates.best_match(face.embedding, settings.attendance_ai_match_threshold)
            person_name = None
            if match is not None:
                person = await db.get(StudentStaff, match[0])
                person_name = person.full_name if person else None
            faces_out.append(
                DetectedFaceOut(
                    bbox=[float(x) for x in face.bbox],
                    person_name=person_name,
                    asleep=is_asleep(face.landmarks_68),
                )
            )

        return LiveDetectionOut(frame_width=frame_width, frame_height=frame_height, faces=faces_out)
    except Exception:
        logger.exception("live-detection failed", extra={"camera_id": camera_id})
        return LiveDetectionOut(frame_width=0, frame_height=0, faces=[])


@router.get("/cameras/{camera_id}/analysis-status", response_model=CameraAnalysisStatusOut)
@limiter.limit("60/minute")
async def get_camera_analysis_status(
    request: Request,
    camera_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CameraAnalysisStatusOut:
    """Oxirgi fon AI sweep vaqti va natijasi — monitoring modal badge."""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi")

    snap = await get_camera_sweep(camera_id)
    if snap is None:
        return CameraAnalysisStatusOut()

    now = datetime.now(timezone.utc)
    seconds_ago = max(0, int((now - snap.swept_at).total_seconds()))
    return CameraAnalysisStatusOut(
        last_sweep_at=snap.swept_at.isoformat(),
        seconds_ago=seconds_ago,
        face_count=snap.face_count,
        modules=list(snap.modules),
        events_raised=snap.events_raised,
    )
