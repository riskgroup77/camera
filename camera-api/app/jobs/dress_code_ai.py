"""TT kriteriya 10 ("Oq xalat kiyilganligi") va 11 ("Bosh kiyim
(kalpakcha) borligi") — bitta sweep'da birlashtirilgan, chunki ikkalasi
ham bir xil quvur liniyasidan foydalanadi: kadr olish -> yuz orqali
xodimni aniqlash -> poza orqali tana/bosh hududini topish -> rang
tahlili. Xuddi app/jobs/lesson_quality_ai.py #19+#21'ni birlashtirgani
kabi.

Faqat TANILGAN XODIMLAR (StudentStaff.type == 'xodim') uchun tekshiriladi
— tasodifiy talaba yoki mehmonning oddiy kiyimda ekanligi "qoidabuzarlik"
emas, shuning uchun har bir aniqlangan odamni tekshirish shunchaki shovqin
(false positive) yaratardi. Bu — app/jobs/unauthorized_person_ai.py'ning
yuz moslashtirish quvuridan foydalanadi, faqat xodimlarga cheklangan va
teskari: bu yerda Event — TANILGAN xodim kutilgan kiyim/bosh kiyimsiz
ko'rilganini bildiradi, kimdir kiyib olganini emas.

Haqiqiy aniqlash usuli (klassik HSV rang evristikasi, o'qitilgan model
EMAS) uchun app/services/coat_detection.py va
app/services/head_covering_detection.py'ning docstringlariga qarang —
u yerda halol ko'lam va cheklovlar batafsil yozilgan.

Yuz (InsightFace) -> xodim identifikatsiyasi; poza (mediapipe) ->
tana/bosh hududi rang namunasi uchun; ikkalasi bir-biriga yuz bbox
markazini eng yaqin pozaning burun landmarkiga solishtirib bog'lanadi
(app/jobs/lesson_quality_ai.py'ning _closest_pose_to_point naqshi bilan
bir xil). Tizimdagi har bir boshqa kriteriya kabi ikki-kadrli
tasdiqlash bilan."""

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.jobs.camera_health import is_reachable
from app.jobs.module_status import camera_allows_module, is_module_active
from app.jobs.sweep_guard import SweepGuard
from app.jobs.sweep_concurrency import camera_sweep_slot
from app.models import Camera, Event, StudentStaff
from app.services.coat_detection import is_wearing_white_coat
from app.services.event_bus import raise_event
from app.services.face_matching import CandidateMatrix, load_candidate_matrix_for_sweep
from app.services.face_recognition import detect_faces
from app.services.frame_grabber import grab_frame_pair_for_camera
from app.services.head_covering_detection import is_wearing_head_covering
from app.services.pose_detection import NOSE, PoseLandmarks, detect_poses

logger = logging.getLogger("app.dress_code_ai")

COAT_MODULE_CODE = 10
COAT_MODULE_NAME = "Oq xalat kiyilganligi"
HEAD_COVERING_MODULE_CODE = 11
HEAD_COVERING_MODULE_NAME = "Bosh kiyim (kalpakcha) borligi"

# See app/jobs/attendance_ai.py's _camera_semaphore docstring.
_sweep_guard = SweepGuard("dress_code_ai")


async def _load_staff_ids(db: AsyncSession) -> set[str]:
    result = await db.execute(select(StudentStaff.id).where(StudentStaff.type == "xodim"))
    return {str(row) for row in result.scalars().all()}


async def _recently_flagged(db: AsyncSession, camera_id, module_code: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.coat_dedup_minutes)
    result = await db.execute(
        select(Event.id)
        .where(Event.module_code == module_code)
        .where(Event.camera_id == camera_id)
        .where(Event.occurred_at >= cutoff)
    )
    return result.scalar_one_or_none() is not None


def _decode(frame_bytes: bytes) -> np.ndarray | None:
    arr = np.frombuffer(frame_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


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


async def _staff_missing_compliance(
    frame_bytes: bytes, candidates: CandidateMatrix, staff_ids: set[str]
) -> tuple[bool, bool]:
    """(coat_missing, head_covering_missing) — True if ANY recognized
    staff member in this frame reads as non-compliant on that criterion.
    Both False if no staff member is recognized here — nothing to
    evaluate, not a compliance pass."""
    if candidates.is_empty or not staff_ids:
        return False, False

    faces = await detect_faces(frame_bytes)
    if not faces:
        return False, False

    embeddings = np.stack([face.embedding for face in faces])
    matches = candidates.best_matches(embeddings, settings.attendance_ai_match_threshold)
    staff_faces = [
        face for face, match in zip(faces, matches, strict=True) if match is not None and match[0] in staff_ids
    ]
    if not staff_faces:
        return False, False

    poses = await detect_poses(frame_bytes)
    image = _decode(frame_bytes)
    if not poses or image is None:
        return False, False

    coat_missing = False
    head_missing = False
    for face in staff_faces:
        x1, y1, x2, y2 = face.bbox
        center = ((float(x1) + float(x2)) / 2 / image.shape[1], (float(y1) + float(y2)) / 2 / image.shape[0])
        pose = _closest_pose_to_point(poses, center)
        if pose is None:
            continue
        if not is_wearing_white_coat(image, pose.points):
            coat_missing = True
        if not is_wearing_head_covering(image, pose.points):
            head_missing = True

    return coat_missing, head_missing


async def process_camera_frame_pair_for_dress_code(
    frame_a: bytes,
    frame_b: bytes,
    db: AsyncSession,
    camera: Camera,
    candidates: CandidateMatrix | None = None,
    staff_ids: set[str] | None = None,
    coat_module_active: bool = True,
    head_covering_module_active: bool = True,
) -> tuple[bool, bool]:
    """Returns (coat_event_raised, head_covering_event_raised)."""
    if candidates is None:
        candidates = await load_candidate_matrix_for_sweep(db)
    if staff_ids is None:
        staff_ids = await _load_staff_ids(db)

    coat_missing_b, head_missing_b = await _staff_missing_compliance(frame_b, candidates, staff_ids)
    if not coat_missing_b and not head_missing_b:
        return False, False

    coat_missing_a, head_missing_a = await _staff_missing_compliance(frame_a, candidates, staff_ids)
    coat_confirmed = coat_missing_b and coat_missing_a
    head_confirmed = head_missing_b and head_missing_a

    coat_raised = False
    if coat_confirmed and coat_module_active and not await _recently_flagged(db, camera.id, COAT_MODULE_CODE):
        await raise_event(
            db,
            camera=camera,
            module_code=COAT_MODULE_CODE,
            module_name=COAT_MODULE_NAME,
            group="C",
            confidence=40,  # klassik rang evristikasi, haqiqiy kamera bilan hali kalibrlanmagan — bilib turib past
            severity="past",  # xavfsizlik-kritik emas, intizom/qoida masalasi
            frame_bytes=frame_b,
        )
        coat_raised = True

    head_raised = False
    if head_confirmed and head_covering_module_active and not await _recently_flagged(
        db, camera.id, HEAD_COVERING_MODULE_CODE
    ):
        await raise_event(
            db,
            camera=camera,
            module_code=HEAD_COVERING_MODULE_CODE,
            module_name=HEAD_COVERING_MODULE_NAME,
            group="C",
            confidence=40,  # klassik rang evristikasi, haqiqiy kamera bilan hali kalibrlanmagan — bilib turib past
            severity="past",  # xavfsizlik-kritik emas, intizom/qoida masalasi
            frame_bytes=frame_b,
        )
        head_raised = True

    return coat_raised, head_raised


async def run_dress_code_ai_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """See app/jobs/attendance_ai.py's run_attendance_ai_sweep_once, which
    this mirrors. Returns how many Events (coat + head covering combined)
    were raised."""
    async with session_factory() as db:
        coat_module_active = await is_module_active(db, COAT_MODULE_CODE)
        head_covering_module_active = await is_module_active(db, HEAD_COVERING_MODULE_CODE)
        if not coat_module_active and not head_covering_module_active:
            return 0
        result = await db.execute(
            select(Camera)
            .where(Camera.status == "faol")
            .where(or_(camera_allows_module(COAT_MODULE_CODE), camera_allows_module(HEAD_COVERING_MODULE_CODE)))
        )
        cameras = [c for c in result.scalars().all() if c.stream_url and is_reachable(c.last_seen_at)]
        candidates = await load_candidate_matrix_for_sweep(db)
        staff_ids = await _load_staff_ids(db)

    if not cameras or not staff_ids:
        return 0

    async def _process_one(camera: Camera) -> tuple[bool, bool]:
        async with camera_sweep_slot():
            frames = await grab_frame_pair_for_camera(camera)
            if frames is None:
                return False, False
            frame_a, frame_b = frames
            async with session_factory() as camera_db:
                return await process_camera_frame_pair_for_dress_code(
                    frame_a,
                    frame_b,
                    camera_db,
                    camera,
                    candidates,
                    staff_ids,
                    coat_module_active,
                    head_covering_module_active,
                )

    results = await asyncio.gather(*(_process_one(camera) for camera in cameras), return_exceptions=True)

    total = 0
    for camera, result in zip(cameras, results, strict=True):
        if isinstance(result, BaseException):
            logger.exception("dress code camera task failed", extra={"camera_id": str(camera.id)}, exc_info=result)
            continue
        coat_raised, head_raised = result
        total += int(coat_raised) + int(head_raised)
    return total


async def dress_code_ai_loop() -> None:
    while True:
        try:
            count = await _sweep_guard.run(run_dress_code_ai_sweep_once)
            if count:
                logger.info("dress code AI sweep raised events", extra={"events": count})
        except Exception:
            logger.exception("dress code AI sweep failed")
        await asyncio.sleep(settings.dress_code_ai_interval_seconds)
