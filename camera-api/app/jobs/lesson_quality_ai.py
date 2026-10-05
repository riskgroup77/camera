"""TT kriteriya 19 ("Talabaning darsga diqqati"), 21 ("O'qituvchi
faolligi") va 7 ning dars darajasidagi qismi (dars davomati) — combined
into one sweep loop because all of them need the exact same thing: an ACTIVE LessonSession window (teacher_id/camera_id/
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
and phone visibility (YOLO "cell phone" detection — a real distraction signal, not a proxy). Honest scope
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
sample counts live next to them (attention_samples / activity_samples),
so a restart mid-lesson resumes the true average, and a lesson nobody
measured yet (count 0) reads as "—" rather than "0%".

Dars davomati (2026-09-07 dan). #19 uchun har bir faol darsning
kadridagi yuzlar allaqachon ro'yxatdagi odamlar bilan solishtiriladi —
ya'ni "shu darsda kim bor" degan savolga javob har bir tikda tekinga
hisoblanib, keyin tashlab yuborilardi. Endi u saqlanadi
(app/models/lesson_attendance.py), va dars tugagach
app/jobs/lesson_attendance.py uni guruh ro'yxati bilan solishtirib
yakunlaydi. Qo'shimcha kamera so'rovi ham, qo'shimcha inference ham
yo'q: aynan o'sha bitta solishtiruv ikkinchi marta ishlatiladi.

Shuning uchun bu sweep endi #19/#21 o'chirilgan bo'lsa ham ishlashi
mumkin — #7 yoqilgan bo'lsa yetarli. Kadr baribir bittagina.

Neither score is validated against real classroom footage or human-rated
engagement/activity — both are geometric proxies (frontality, phone
visibility, movement amount), not trained models, and should be read as
a decision-support signal for a human reviewer, not ground truth.
"""

import asyncio
import json
import logging
import math
import time
from datetime import timedelta

import numpy as np
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.jobs.camera_health import is_reachable
from app.jobs.module_status import any_module_active, is_module_active
from app.jobs.sweep_guard import SweepGuard
from app.jobs.sweep_concurrency import camera_sweep_slot
from app.jobs.lesson_attendance import STUDENT_ATTENDANCE_MODULE_CODE, group_member_clause, record_sightings
from app.models import LessonSession, StudentStaff
from app.services.face_matching import CandidateMatrix, matrix_from_rows
from app.services.face_recognition import detect_faces, recognizable_faces
from app.services.frame_grabber import grab_frame_pair_for_camera
from app.services.image_size import jpeg_dimensions
from app.services.object_detection import detect_objects
from app.services.pose_detection import NOSE, PoseLandmarks, detect_poses
from app.services.sleep_detection import is_plausible_frontal
from app.timezone import local_now

# COCO "cell phone" klassi — app/services/object_detection.py dagi aynan
# shu model bilan tekshirilgan. Ilgari bu konstanta phone_ai.py da edi;
# #16 ("Imtihonda telefondan foydalanish") olib tashlangandan keyin
# telefon signalini ishlatadigan yagona joy shu modul bo'lib qoldi.
PHONE_CLASS_ID = 67

logger = logging.getLogger("app.lesson_quality_ai")

ATTENTION_MODULE_CODE = 19
TEACHER_ACTIVITY_MODULE_CODE = 21

_sweep_guard = SweepGuard("lesson_quality_ai")

# Jadvalga asoslangan siyrak namuna olish. Ilgari har faol dars har 45 s da
# (sweep har aylanishida) tahlil qilinardi — o'nlab dars bir vaqtda bo'lsa,
# bu xona kameralarini kirish eshigi bilan CPU uchun talashtirardi. Diqqat
# va faollik davomiy o'rtacha, dars davomati esa 3 ta ko'rinish talab qiladi:
# 90 daqiqalik darsda 5 daqiqada bir namuna (18 ta) ikkalasiga ham yetarli.
_last_sampled: dict[str, float] = {}
# Darsning galereyasi: faqat shu guruh talabalari va o'qituvchisi.
_gallery_cache: dict[str, tuple[float, CandidateMatrix]] = {}
GALLERY_TTL_SECONDS = 600.0


def reset_sampling_for_tests() -> None:
    _last_sampled.clear()
    _gallery_cache.clear()


async def _lesson_gallery(db: AsyncSession, session_row: LessonSession) -> CandidateMatrix:
    """Dars uchun kichik galereya: guruhning tasdiqlangan talabalari va
    jadvaldagi o'qituvchi. 8800 kishilik umumiy ro'yxat o'rniga ~30 kishi:
    yolg'on moslik ehtimoli ~300 barobar kam, solishtirish esa deyarli bepul.
    Guruhdan tashqaridagi odam (boshqa guruh talabasi, mehmon) bu darsda
    baribir hisobga olinmasdi."""
    key = str(session_row.id)
    cached = _gallery_cache.get(key)
    now = time.monotonic()
    if cached is not None and now - cached[0] < GALLERY_TTL_SECONDS:
        return cached[1]
    members = [(StudentStaff.type == "talaba") & group_member_clause(session_row.group_name)]
    if session_row.teacher_id is not None:
        members.append(StudentStaff.id == session_row.teacher_id)
    rows = (
        await db.execute(
            select(StudentStaff.id, StudentStaff.biometric_embedding, StudentStaff.type)
            .where(StudentStaff.biometric_embedding.is_not(None))
            # Faolsizlantirilgan odam tanilmaydi (face_matching.load_candidate_matrix).
            .where(StudentStaff.active.is_(True))
            # Umumiy ro'yxatdagi qoida (face_matching.load_candidate_matrix):
            # tekshiruvdagi ("kutilmoqda") yuz hech kim uchun tanilmaydi.
            .where(StudentStaff.biometrics_status != "kutilmoqda")
            .where(or_(*members))
        )
    ).all()
    gallery = await matrix_from_rows(rows)
    # Eskirganlar olib tashlanadi: kaliti dars id'si, kuniga ~230 dars —
    # tozalanmasa kesh jarayon qayta ishga tushguncha o'sib boraverardi.
    for stale in [k for k, (at, _g) in _gallery_cache.items() if now - at >= GALLERY_TTL_SECONDS]:
        del _gallery_cache[stale]
    _gallery_cache[key] = (now, gallery)
    return gallery


async def _active_sessions(db: AsyncSession) -> list[LessonSession]:
    """Filtered in Python against the camera's excluded_module_codes —
    see app/jobs/teacher_punctuality_ai.py's _due_sessions for why that's
    fine here (LessonSession.camera is lazy="joined", "active right now"
    is always a small set). A session is skipped only if its camera
    excludes BOTH #19 and #21 — same "any" rule run_lesson_quality_ai_
    sweep_once itself already applies at the whole-sweep level."""
    now = local_now()
    # Faqat hozir davom etayotgan darslar SQL'da tanlanadi — ilgari har
    # 30-45 soniyada butun jadval tarixi o'qilib, Python'da saralanardi.
    result = await db.execute(
        select(LessonSession)
        .where(LessonSession.teacher_id.is_not(None))
        .where(LessonSession.camera_id.is_not(None))
        .where(LessonSession.scheduled_start_time <= now)
        .where(LessonSession.scheduled_start_time >= now - timedelta(minutes=settings.lesson_duration_minutes))
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


async def _group_student_ids(db: AsyncSession, group_name: str) -> set[str]:
    """Guruh talabalarining id lari.

    Har tikda so'raladi va keshlanmaydi: faol darslar soni kichik (bir
    vaqtda o'nlab), so'rov esa bitta indeksli ustun bo'yicha. Keshlash
    yangi ro'yxatdan o'tgan talabani darsning oxirigacha ko'rinmas
    qilardi — bu narxga arzimaydi."""
    result = await db.execute(
        select(StudentStaff.id)
        .where(StudentStaff.type == "talaba")
        .where(group_member_clause(group_name))
    )
    return {str(row) for row in result.scalars().all()}


def _running_average(current_score: int, count: int, sample: float) -> int:
    # count == 0: yaratilgandagi qiymat o'lchov emas — birinchi namuna o'rnini egallaydi.
    return round((current_score * count + sample) / (count + 1))


async def _match_enrolled(frame_bytes: bytes, candidates, faces: list | None = None) -> list[tuple[object, tuple]]:
    """Kadrdagi yuzlarni ro'yxat bilan solishtiradi va TANILGANLARNI
    qaytaradi.

    Alohida funksiya, chunki natijasi ikki joyda kerak: diqqat balli
    (#19) va dars davomati (#7). Ilgari bu hisob _sample_attention
    ichida edi va natijasi ballga aylantirilib, tashlab yuborilardi —
    ya'ni "shu darsda kim bor" degan javob har tikda hisoblanib,
    saqlanmasdi.

    `faces` — shu kadrda allaqachon aniqlangan yuzlar (qayta aniqlanmaydi)."""
    if faces is None:
        faces = await detect_faces(frame_bytes)
    faces = recognizable_faces(faces)
    if not faces:
        return []
    embeddings = np.stack([face.embedding for face in faces])
    matches = candidates.best_matches(embeddings, settings.attendance_ai_match_threshold)
    return [(face, match) for face, match in zip(faces, matches, strict=True) if match is not None]


async def _sample_attention(frame_bytes: bytes, matched: list[tuple[object, tuple]]) -> float | None:
    """None if no enrolled student was matched in this frame — nothing to
    sample this tick, not a zero score (a zero would incorrectly drag the
    running average down every time the classroom camera briefly sees no
    one)."""
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
    """(eni, bo'yi). JPEG sarlavhasidan — to'liq dekodlash (va event
    loop'ni to'xtatish) ikki son uchun ortiqcha (app/services/image_size.py)."""
    return jpeg_dimensions(frame_bytes)


async def _sample_activity(
    frame_a: bytes, frame_b: bytes, teacher_embedding: list[float], faces_b: list | None = None
) -> float | None:
    """None if the teacher's face couldn't be matched in frame_b, or no
    pose was found near them in either frame — nothing to sample this
    tick. Associates a detected FACE (InsightFace, pixel bbox) with a
    detected POSE (mediapipe, normalized landmarks) by normalizing the
    face's center using the frame's real dimensions — the two models
    don't share a coordinate system otherwise.

    `faces_b` — frame_b da allaqachon aniqlangan yuzlar. Ilgari shu kadr
    _match_enrolled da bir marta, bu yerda ikkinchi marta aniqlanardi."""
    if faces_b is None:
        faces_b = await detect_faces(frame_b)
    faces_b = recognizable_faces(faces_b)
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
    lesson_attendance_active: bool = True,
) -> None:
    """Samples both scores for one active LessonSession and commits any
    update — either signal can independently be "nothing to sample this
    tick" (see _sample_attention/_sample_activity), in which case that
    score is simply left unchanged. Dars davomati ham shu yerda qayd
    etiladi, xuddi o'sha bitta yuz solishtiruvidan."""
    # Bitta solishtiruv, ikkita iste'molchi. Faqat kerak bo'lsa
    # bajariladi — ikkala modul ham o'chirilgan bo'lsa, kadr umuman
    # tahlil qilinmaydi. frame_b dagi yuzlar ham bir marta aniqlanadi va
    # o'qituvchi faolligi (#21) uchun qayta ishlatiladi.
    teacher = session_row.teacher_ref
    wants_activity = (
        teacher_activity_module_active
        and teacher is not None
        and teacher.active  # faolsizlantirilgan odamning yuzi solishtirilmaydi
        and bool(teacher.biometric_embedding)
    )
    faces_b: list | None = None
    if attention_module_active or lesson_attendance_active or wants_activity:
        faces_b = await detect_faces(frame_b)

    matched: list[tuple[object, tuple]] = []
    if attention_module_active or lesson_attendance_active:
        matched = await _match_enrolled(frame_b, candidates, faces_b)

    if lesson_attendance_active and matched:
        # Faqat SHU GURUH talabalari. Auditoriyaga kirgan o'qituvchi ham,
        # boshqa guruh talabasi ham bu darsning davomat ro'yxatiga
        # tegishli emas — ular bu yerda shunchaki mavjud odamlar.
        roster_ids = await _group_student_ids(db, session_row.group_name)
        seen = {match[0] for _face, match in matched if match[0] in roster_ids}
        if seen:
            await record_sightings(db, session_row, seen)

    attention_sample = await _sample_attention(frame_b, matched) if attention_module_active else None
    if attention_sample is not None:
        session_row.attention_score = _running_average(
            session_row.attention_score, session_row.attention_samples, attention_sample
        )
        session_row.attention_samples += 1

    if wants_activity:
        teacher_embedding = json.loads(teacher.biometric_embedding)
        activity_sample = await _sample_activity(frame_a, frame_b, teacher_embedding, faces_b)
        if activity_sample is not None:
            session_row.teacher_activity_score = _running_average(
                session_row.teacher_activity_score, session_row.activity_samples, activity_sample
            )
            session_row.activity_samples += 1

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
        lesson_attendance_active = await is_module_active(db, STUDENT_ATTENDANCE_MODULE_CODE)
        if not attention_module_active and not teacher_activity_module_active and not lesson_attendance_active:
            return 0
        sessions = await _active_sessions(db)

    now = time.monotonic()
    interval = settings.lesson_sample_interval_seconds
    sessions = [row for row in sessions if now - _last_sampled.get(str(row.id), -interval) >= interval]
    if not sessions:
        return 0

    async def _process_one(session_row: LessonSession) -> bool:
        camera = session_row.camera
        if camera is None or not camera.stream_url or not is_reachable(camera.last_seen_at):
            return False
        # Kadr kutish slotdan tashqarida, tahlil esa slot ichida (ilgari
        # teskari edi: slot kalit kadrni kutib band turardi, model esa
        # slotsiz ishlardi).
        frames = await grab_frame_pair_for_camera(camera)
        if frames is None:
            return False
        stamp = time.monotonic()
        _last_sampled[str(session_row.id)] = stamp
        if len(_last_sampled) > 2000:
            # Tugagan darslar (kaliti dars id'si) — bir kundan eskisi kerak emas.
            for stale in [k for k, at in _last_sampled.items() if stamp - at > 86400]:
                del _last_sampled[stale]
        frame_a, frame_b = frames
        async with camera_sweep_slot(), session_factory() as db:
            row = await db.get(LessonSession, session_row.id)
            if row is None:
                return False
            candidates = await _lesson_gallery(db, row)
            await process_lesson_session(
                row,
                frame_a,
                frame_b,
                db,
                candidates,
                attention_module_active,
                teacher_activity_module_active,
                lesson_attendance_active,
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
