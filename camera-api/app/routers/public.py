"""Public (no-auth) endpoints backing the Monitoring page — camera/src/pages/public/MonitoringPage.tsx.

Honest scope note: cameras here have no real link to a faculty/course/group
in the schema (a Camera is just a physical device in a Building/zone), so
unlike the admin-only endpoints this never exposes ip/port/rtsp_path/
credentials, and the frontend can't filter by faculty/course/group the way
an earlier mock-data version pretended to.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import time
import uuid
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import and_, case, extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.dependencies import CurrentUser, require_monitoring_access
from app.jobs.camera_health import is_reachable, is_video_flowing
from app.models import AttendanceRecord, Building, Camera, Department, Event, LessonSession, StudentStaff
from app.pagination import Page, PageParams, build_page, paginate
from app.rate_limit import limiter
from app.schemas.public import (
    CameraAnalysisStatusOut,
    CampusBuildingOut,
    CampusFloorOut,
    CampusOut,
    DetectedFaceOut,
    LiveDetectionOut,
    PublicCameraOut,
    PublicDepartmentOut,
    PublicStatsOut,
    PublicTopStudentOut,
)
from app.services.access_scope import allowed_buildings, camera_filter, ensure_camera_allowed, is_restricted
from app.services.event_scope import NOT_SUPPRESSED, OPERATOR_EVENTS
from app.services.face_matching import load_candidate_matrix_cached
from app.services.face_recognition import detect_faces
from app.services.inference_gate import PRIORITY_LIVE
from app.services.frame_grabber import frame_wait_seconds_for_camera, grab_frame_for_camera, grab_live_main_frame
from app.services.image_size import jpeg_dimensions
from app.services.video_gateway import internal_whep_url
from app.services import live_focus
from app.services.sleep_detection import is_asleep, is_face_measurable
from app.services.stream_links import signed_stream_url
from app.services.sweep_result_cache import get_camera_sweep
from app.services.thumbnail_cache import ensure_thumbnail

logger = logging.getLogger("app.public")
from app.timezone import day_start, local_now
from app.timezone import business_today

# Himoya BUTUN router darajasida: endpointlarga birma-bir qo'shilsa,
# keyin qo'shiladigan yangi endpoint ochiq qolib ketishi mumkin edi —
# audit aynan shunday teshikni topdi.
router = APIRouter(
    prefix="/api/public",
    tags=["public"],
    dependencies=[Depends(require_monitoring_access)],
)

# Kamera bilan ishlaydigan endpointlar foydalanuvchini ham oladi — bino
# doirasi uchun (app/services/access_scope.py). FastAPI bog'liqlikni bitta
# so'rovda keshlaydi, ya'ni router darajasidagi tekshiruv qayta ishlamaydi.
# None — himoya o'chirilgan rejimdagi anonim devor: u hamma kamerani
# ko'radi (public_monitoring_requires_auth izohiga qarang).
Viewer = Annotated[CurrentUser | None, Depends(require_monitoring_access)]


async def _load_camera(db: AsyncSession, camera_id: str, viewer: CurrentUser | None = None) -> Camera:
    """Kamerani identifikator bo'yicha oladi; noto'g'ri shaklda — 404.

    Xom satrni so'rovga qo'yish Postgres darajasida "invalid input
    syntax for type uuid" xatosiga olib kelardi: OCHIQ endpointda bu
    500 va buzilgan sessiya degani edi, holbuki javob oddiy "topilmadi"
    bo'lishi kerak."""
    try:
        key = uuid.UUID(camera_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi") from None
    camera = (await db.execute(select(Camera).where(Camera.id == key))).scalar_one_or_none()
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi")
    return ensure_camera_allowed(viewer, camera)


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
        department=camera.department.name if camera.department else "",
        status="live" if live else "offline",
        has_video=has_video,
        stream_url=signed_stream_url(camera.stream_url),
        floor=camera.floor,
        # Protokolsiz PTZ ishlamaydi (har harakat 409) — panel ham ko'rsatilmasin.
        ptz_enabled=bool(camera.ptz_enabled and camera.ptz_protocol),
    )


@router.get("/cameras", response_model=Page[PublicCameraOut])
async def list_public_cameras(
    db: Annotated[AsyncSession, Depends(get_db)],
    params: Annotated[PageParams, Depends()],
    viewer: Viewer,
    search: str | None = None,
    building: str | None = None,
    building_id: Annotated[str | None, Query(alias="buildingId")] = None,
    floor: Annotated[str | None, Query()] = None,
    department: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> Page[PublicCameraOut]:
    """Paginated (see app/pagination.py's Page/PageParams) so the response
    stays bounded as the institute's camera count grows — search/building/
    status are applied in SQL rather than over the full table so filtering
    still only pulls back one page's worth of rows."""
    stmt = (
        select(Camera)
        .options(selectinload(Camera.building), selectinload(Camera.department))
        .where(camera_filter(viewer))
        .order_by(Camera.name)
    )
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Camera.name.ilike(like), Camera.zone.ilike(like)))
    if building:
        stmt = stmt.where(Camera.building.has(Building.name == building))
    if building_id == "none":
        # Kesimdagi "Bino biriktirilmagan" guruhi.
        stmt = stmt.where(Camera.building_id.is_(None))
    elif building_id:
        # Monitoring markazi qavat gridi bino NOMI emas, ID bo'yicha
        # so'raydi: nom o'zgarishi mumkin, havola esa ishlab turishi kerak.
        try:
            stmt = stmt.where(Camera.building_id == uuid.UUID(building_id))
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Noto'g'ri bino identifikatori")
    if floor:
        # "none" — qavati belgilanmagan kameralar guruhi (Camera.floor
        # nullable, kesimda ular alohida plita bo'lib chiqadi).
        if floor == "none":
            stmt = stmt.where(Camera.floor.is_(None))
        elif floor.lstrip("-").isdigit():
            stmt = stmt.where(Camera.floor == int(floor))
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Noto'g'ri qavat qiymati")
    if department:
        # Kafedra bino ichida joylashadi, lekin filtr mustaqil: bino
        # tanlanmagan holda ham kafedra bo'yicha izlash mumkin.
        stmt = stmt.where(Camera.department.has(Department.name == department))
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
    today = business_today()
    start_of_today = day_start(business_today())

    total_students = (
        await db.execute(
            select(func.count())
            .select_from(StudentStaff)
            .where(StudentStaff.type == "talaba", StudentStaff.active.is_(True))
        )
    ).scalar_one()

    # "Talabalar" kartasi — faqat faol talabalar: ilgari keldi/kelmadi
    # xodimlarni ham qo'shib, "10 000 talabadan 700 keldi" (asosan xodim) chiqardi.
    today_statuses = (
        await db.execute(
            select(AttendanceRecord.status)
            .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
            .where(AttendanceRecord.date == today)
            .where(StudentStaff.type == "talaba", StudentStaff.active.is_(True))
        )
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
            # Devordagi signal paneli bilan bir xil doira (event_scope).
            .where(OPERATOR_EVENTS, NOT_SUPPRESSED)
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
    department_rows = (
        await db.execute(
            select(Department.name, Building.name)
            .outerjoin(Building, Department.building_id == Building.id)
            .order_by(Building.name, Department.name)
        )
    ).all()

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
        departments=[
            PublicDepartmentOut(name=name, building=building or "")
            for name, building in department_rows
        ],
    )


@router.get("/top-students", response_model=list[PublicTopStudentOut])
async def list_top_students(db: Annotated[AsyncSession, Depends(get_db)]) -> list[PublicTopStudentOut]:
    """Bu oyning davomat foizi bo'yicha eng yaxshi 10 ta talaba — kamida
    bitta davomat yozuvi bo'lganlar orasidan (bo'sh tarixli talabalar
    reytingga qo'shilmaydi, aks holda ular soxta 0% bilan pastda emas,
    umuman ko'rinmaydi degan ma'noni anglatadi)."""
    now = local_now()  # local month/year — AttendanceRecord.date is filed under the local calendar day
    month_start = now.date().replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    present_count = func.sum(
        case((AttendanceRecord.status.in_(["keldi", "kech_keldi"]), 1), else_=0)
    )
    total_count = func.count(AttendanceRecord.id)
    rate = (present_count * 100.0) / total_count

    stmt = (
        select(StudentStaff.id, StudentStaff.full_name, StudentStaff.group_or_position, rate.label("rate"))
        .join(AttendanceRecord, AttendanceRecord.student_staff_id == StudentStaff.id)
        .where(StudentStaff.type == "talaba", StudentStaff.active.is_(True))
        # Oraliq — sana indeksidan foydalanadi (extract(year/month) butun jadvalni skanerlardi).
        .where(AttendanceRecord.date >= month_start, AttendanceRecord.date < next_month)
        # dam_olish — o'lchanmagan kun, foizga kirmaydi.
        .where(AttendanceRecord.status != "dam_olish")
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


# camera_id -> monotonic payt: shu paytgacha kuzatuvchi natijasi kutilmaydi
# (kamera kuzatilmaydi yoki ai-worker o'chiq) — har so'rov bir necha soniya
# behuda kutmasin.
_no_watcher_until: dict[str, float] = {}
_NO_WATCHER_BACKOFF_SECONDS = 60.0
_HISTORY_MAX_AGE_SECONDS = 10.0


async def _await_watcher_result(camera_id: str) -> dict | None:
    max_age = settings.live_result_max_age_seconds
    payload = await live_focus.latest_result(camera_id, max_age_seconds=max_age)
    if payload is not None:
        _no_watcher_until.pop(camera_id, None)
        return payload
    if time.monotonic() < _no_watcher_until.get(camera_id, 0.0):
        return None
    # Kuzatuvchi kutish rejimida bo'lsa, fokusni ~1 s da sezadi va keyingi
    # kadrni darhol tahlil qiladi.
    deadline = time.monotonic() + settings.live_result_first_wait_seconds
    while time.monotonic() < deadline:
        await asyncio.sleep(0.25)
        payload = await live_focus.latest_result(camera_id, max_age_seconds=max_age)
        if payload is not None:
            return payload
    _no_watcher_until[camera_id] = time.monotonic() + _NO_WATCHER_BACKOFF_SECONDS
    return None


@router.get("/cameras/{camera_id}/live-detection", response_model=LiveDetectionOut)
# Natija keshdan o'qiladi (arzon) — skaner har ~1.5 s da so'raydi.
@limiter.limit("90/minute")
async def get_live_detection(
    request: Request,
    camera_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    viewer: Viewer,
    player: Annotated[str | None, Query(max_length=10)] = None,
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
    camera = await _load_camera(db, camera_id, viewer)

    if settings.analysis_mode == "kunlik":
        # Kunlik tahlil rejimi: kun davomida yuz tahlili yo'q (server yukini
        # olib tashlash shu rejimning maqsadi) — jonli video ramkasiz.
        return LiveDetectionOut(frame_width=0, frame_height=0, faces=[], source="kunlik")

    # Real vaqt: ai-worker kuzatuvchisi shu kamerani eng yuqori navbat bilan
    # tahlil qiladi va natijani yozib boradi (app/services/live_focus.py).
    # So'rov o'sha natijani o'qiydi — o'zi kadr olmaydi va tahlil qilmaydi.
    key = str(camera.id)
    await live_focus.mark_focus(key, hls=player == "hls")
    payload = await _await_watcher_result(key)
    if payload is not None:
        history = await live_focus.recent_results(key, max_age_seconds=_HISTORY_MAX_AGE_SECONDS)
        return LiveDetectionOut.model_validate(
            {
                **payload,
                "history": history,
                # Kuzatuvchi o'lchagan farq; hali o'lchanmagan bo'lsa — sozlama.
                "clock_offset_ms": payload.get("clock_offset_ms", settings.live_overlay_clock_offset_ms),
                "server_time": time.time(),
            }
        )

    try:
        # Mayda yuzlar (sinf xonasi, shiftdagi kamera) faqat asosiy
        # oqimda tahlilga yaraydi — settings.live_detection_main_stream.
        source = "kichik"
        frame_bytes = None
        if settings.live_detection_main_stream:
            frame_bytes = await grab_live_main_frame(camera, wait_seconds=settings.live_detection_main_wait_seconds)
            if frame_bytes is not None:
                source = "asosiy"
        if frame_bytes is None:
            frame_bytes = await grab_frame_for_camera(camera, wait_seconds=frame_wait_seconds_for_camera(camera))
        if frame_bytes is None:
            return LiveDetectionOut(frame_width=0, frame_height=0, faces=[])

        # Header parse instead of a full cv2.imdecode: this handler is async
        # and polled repeatedly while an operator watches a camera, so a
        # synchronous full-resolution decode here blocked the event loop on
        # every poll — for two integers. See app/services/image_size.py.
        captured = time.time()
        dims = jpeg_dimensions(frame_bytes)
        frame_width, frame_height = dims if dims else (0, 0)

        faces = await detect_faces(frame_bytes, priority=PRIORITY_LIVE)
        candidates = await load_candidate_matrix_cached(db)
        threshold = settings.attendance_ai_match_threshold

        faces_out = []
        for face in faces:
            # Juda kichik yuz tahlil qilinmagan: ramkasi chiziladi, ismi va
            # uyqu holati yo'q (baribir ishonchli aniqlab bo'lmasdi).
            analysed = face.embedding is not None
            match = candidates.best_match(face.embedding, threshold) if analysed else None
            similarity = None
            if analysed and not candidates.is_empty:
                _idx, best_sim, _second = candidates.top_two(face.embedding.reshape(1, -1))
                similarity = round(max(0.0, float(best_sim[0])), 3)
            person_name = None
            if match is not None:
                person = await db.get(StudentStaff, match[0])
                person_name = person.full_name if person else None
            faces_out.append(
                DetectedFaceOut(
                    bbox=[float(x) for x in face.bbox],
                    person_name=person_name,
                    asleep=analysed and is_face_measurable(face.bbox) and is_asleep(face.landmarks_68),
                    status="tanildi" if person_name else ("notanish" if analysed else "kichik"),
                    similarity=similarity,
                )
            )

        return LiveDetectionOut(
            frame_width=frame_width,
            frame_height=frame_height,
            faces=faces_out,
            source=source,
            captured_at=captured,
            server_time=time.time(),
        )
    except Exception:
        logger.exception("live-detection failed", extra={"camera_id": camera_id})
        return LiveDetectionOut(frame_width=0, frame_height=0, faces=[])


_WHEP_MAX_OFFER_BYTES = 64_000


@router.post("/cameras/{camera_id}/whep")
@limiter.limit("60/minute")
async def post_whep_offer(
    request: Request, camera_id: str, db: Annotated[AsyncSession, Depends(get_db)], viewer: Viewer
) -> Response:
    """Jonli video WebRTC orqali (~0.3-0.5 s kechikish; HLS'da 4-8 s edi).

    Brauzer SDP taklifini (application/sdp) yuboradi, bu yerdan u kamera
    turgan MediaMTX shard'ining WHEP manziliga uzatiladi va javob SDP
    qaytariladi. Ruxsat — jonli HLS bilan bir xil (monitoring ruxsati va
    bino doirasi, _load_camera). MediaMTX'ning o'zi brauzerga ochilmaydi:
    unga faqat shu API murojaat qiladi; media esa UDP'da to'g'ridan-to'g'ri.

    404 — WebRTC o'chirilgan yoki kameraning oqimi yo'q: brauzer HLS'ga qaytadi."""
    camera = await _load_camera(db, camera_id, viewer)
    target = internal_whep_url(camera.stream_url) if settings.webrtc_enabled else None
    if target is None:
        raise HTTPException(status_code=404, detail="WebRTC mavjud emas")
    offer = await request.body()
    if not offer or len(offer) > _WHEP_MAX_OFFER_BYTES or not offer.lstrip().startswith(b"v=0"):
        raise HTTPException(status_code=400, detail="SDP taklifi noto'g'ri")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            upstream = await client.post(target, content=offer, headers={"Content-Type": "application/sdp"})
    except httpx.HTTPError:
        logger.warning("whep upstream unreachable", extra={"camera_id": camera_id}, exc_info=True)
        raise HTTPException(status_code=502, detail="Video server javob bermadi") from None
    if upstream.status_code not in (200, 201):
        logger.info("whep upstream refused", extra={"camera_id": camera_id, "status": upstream.status_code})
        raise HTTPException(status_code=502, detail="Video server WebRTC'ni rad etdi")
    return Response(content=upstream.content, status_code=201, media_type="application/sdp")


@router.get("/cameras/{camera_id}/analysis-status", response_model=CameraAnalysisStatusOut)
@limiter.limit("60/minute")
async def get_camera_analysis_status(
    request: Request,
    camera_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    viewer: Viewer,
) -> CameraAnalysisStatusOut:
    """Oxirgi fon AI sweep vaqti va natijasi — monitoring modal badge."""
    await _load_camera(db, camera_id, viewer)

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


# Kampus kesimi 15 soniya keshlanadi: sanoqlar shu vaqt ichida sezilarli
# o'zgarmaydi, monitoring devorida esa bu so'rov har bir tomoshabinda
# takrorlanadi.
_CAMPUS_CACHE_SECONDS = 15
_campus_cache: tuple[float, CampusOut] | None = None


def _has_video_expr():
    """_is_live_expr() ning juftligi — app/jobs/camera_health.py dagi
    is_video_flowing() ning SQL ko'rinishi: kamera javob beryapti, lekin
    tasvir kelyaptimi."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.camera_video_stale_seconds)
    return and_(Camera.last_frame_at.isnot(None), Camera.last_frame_at >= cutoff)


def _floor_label(floor: int | None) -> str:
    return f"{floor}-qavat" if floor is not None else "Qavat belgilanmagan"


def _floor_sort_key(item) -> tuple[int, int]:
    floor = item[0]
    return (1, 0) if floor is None else (0, floor)


@router.get("/campus", response_model=CampusOut)
async def get_campus(db: Annotated[AsyncSession, Depends(get_db)], viewer: Viewer) -> CampusOut:
    """Bino -> qavat kesimi: har qavatda nechta kamera bor, nechtasi jonli,
    nechtasida tasvir yo'q va bugun nechta signal bo'lgan.

    Kameralar RO'YXATI bu yerda qaytarilmaydi — Video Monitoring Markazi
    avval shu yengil kesimni ko'rsatadi, kameralarni esa faqat operator
    qavatni tanlaganda so'raydi. 100+ kamerali kampusda birinchi
    yuklanish shu tariqa bir necha o'nlab marta yengillashadi.

    Hammasi ikkita GROUP BY so'rovda: kamera sanoqlari va bugungi
    signallar. Binolar ro'yxati uchinchi (kichik) so'rov — kamerasi hali
    biriktirilmagan bino ham kesimda ko'rinishi uchun."""
    global _campus_cache
    now = time.monotonic()
    # Kesh faqat cheklovsiz ko'rinish uchun: bino doirasi bor
    # foydalanuvchiga umumiy keshdan javob berilsa, boshqa binolar
    # sanoqlari ham ko'rinib qolardi (va aksincha, uning toraytirilgan
    # javobi hammaga tarqalardi).
    restricted = is_restricted(viewer)
    cached = _campus_cache
    if not restricted and cached is not None and now - cached[0] < _CAMPUS_CACHE_SECONDS:
        return cached[1]

    live = _is_live_expr()
    has_video = _has_video_expr()
    camera_rows = (
        await db.execute(
            select(
                Camera.building_id,
                Camera.floor,
                func.count(),
                func.count().filter(live),
                func.count().filter(and_(live, ~has_video)),
            )
            .where(camera_filter(viewer))
            .group_by(Camera.building_id, Camera.floor)
        )
    ).all()

    start_of_today = day_start(business_today())
    event_rows = (
        await db.execute(
            select(Camera.building_id, Camera.floor, func.count())
            .select_from(Event)
            .join(Camera, Camera.id == Event.camera_id)
            .where(Event.is_trial.is_(False))
            .where(Event.occurred_at >= start_of_today)
            .where(camera_filter(viewer))
            .group_by(Camera.building_id, Camera.floor)
        )
    ).all()

    building_stmt = select(Building).order_by(Building.sort_order, Building.name)
    if restricted:
        building_stmt = building_stmt.where(Building.id.in_(allowed_buildings(viewer) or set()))
    buildings = (await db.execute(building_stmt)).scalars().all()

    # (bino_id, qavat) -> [jami, jonli, tasvirsiz, bugungi signallar]
    counts: dict[tuple[str, int | None], list[int]] = {}
    for building_id, floor, total, live_count, no_video in camera_rows:
        counts[(str(building_id) if building_id else "", floor)] = [total, live_count, no_video, 0]
    for building_id, floor, event_count in event_rows:
        key = (str(building_id) if building_id else "", floor)
        counts.setdefault(key, [0, 0, 0, 0])[3] = event_count

    groups: list[tuple[str, str, int | None]] = [(str(b.id), b.name, b.floors) for b in buildings]
    # Binoga biriktirilmagan kameralar ham ko'rinishi kerak: aks holda ular
    # kesimdan butunlay tushib qolib, "hammasi joyida" degan yolg'on
    # manzara chiqadi.
    if any(building_id == "" for building_id, _floor in counts):
        groups.append(("", "Bino biriktirilmagan", None))

    out_buildings: list[CampusBuildingOut] = []
    for building_id, name, declared_floors in groups:
        floors: dict[int | None, list[int]] = {}
        # Bino nechta qavatli ekani ma'lum bo'lsa, kamerasi yo'q qavat ham
        # chiziladi — u yerda kamera yo'qligi ko'rinib tursin.
        for number in range(1, (declared_floors or 0) + 1):
            floors[number] = [0, 0, 0, 0]
        for (row_building, floor), values in counts.items():
            if row_building == building_id:
                floors[floor] = values
        floor_out = [
            CampusFloorOut(
                floor=floor,
                label=_floor_label(floor),
                cameras=values[0],
                live=values[1],
                offline=values[0] - values[1],
                no_video=values[2],
                events_today=values[3],
            )
            for floor, values in sorted(floors.items(), key=_floor_sort_key)
        ]
        out_buildings.append(
            CampusBuildingOut(
                id=building_id,
                name=name,
                floors=floor_out,
                cameras=sum(f.cameras for f in floor_out),
                live=sum(f.live for f in floor_out),
                offline=sum(f.offline for f in floor_out),
                no_video=sum(f.no_video for f in floor_out),
                events_today=sum(f.events_today for f in floor_out),
            )
        )

    campus = CampusOut(
        buildings=out_buildings,
        cameras=sum(b.cameras for b in out_buildings),
        live=sum(b.live for b in out_buildings),
        offline=sum(b.offline for b in out_buildings),
        no_video=sum(b.no_video for b in out_buildings),
        events_today=sum(b.events_today for b in out_buildings),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    if not restricted:
        _campus_cache = (now, campus)
    return campus


def reset_campus_cache_for_tests() -> None:
    global _campus_cache
    _campus_cache = None


@router.get("/cameras/{camera_id}/thumbnail", response_class=Response)
@limiter.limit("600/minute")
async def get_camera_thumbnail(
    request: Request, camera_id: str, db: Annotated[AsyncSession, Depends(get_db)], viewer: Viewer
) -> Response:
    """Qavat grididagi bitta kadr (JPEG).

    Jonli HLS o'rniga: 24 kamerali qavat 24 ta ffmpeg transkodini emas,
    24 ta kichik rasmni oladi. Rasm AI sweep allaqachon olgan kadrdan
    tayyorlanadi (app/services/thumbnail_cache.py), ya'ni odatda kameraga
    qo'shimcha ulanish umuman bo'lmaydi; sweep tegmagan kamera uchungina
    bitta kadr so'raladi va u ham sovutish oynasi bilan cheklangan."""
    try:
        camera_uuid = uuid.UUID(camera_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi")
    result = await db.execute(select(Camera).where(Camera.id == camera_uuid))
    camera = result.scalar_one_or_none()
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi")
    ensure_camera_allowed(viewer, camera)

    thumbnail = await ensure_thumbnail(camera)
    if thumbnail is None:
        # 404 ataylab: "hali rasm yo'q" — xato emas, holat. Frontend
        # bunda kamera holatiga qarab joy egallovchi chizadi.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Miniatyura hali tayyor emas")
    jpeg, age_seconds = thumbnail
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "X-Thumbnail-Age": str(age_seconds)},
    )
