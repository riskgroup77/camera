"""Unified face-based AI sweep — TT kriteriya 1 (begona shaxs) and 20
(uyqu) in one pass.

Replaced three independent loops (attendance_ai, unauthorized_person_ai,
vision_ai) that each grabbed frames and ran detect_faces() on the same
cameras every ~30s. One tick per camera:

  1. Grab frame(s) once (burst when sleep needs it)
  2. Run detect_faces() once per distinct frame
  3. Feed results into each active module's existing processor

KELISH ISTALGAN KAMERADA (2026-09-26, institut talabi): odam bugun
birinchi marta QAYSI kamerada aniq tanilsa — o'sha payt kelgan vaqti
(settings.attendance_any_camera). Kirish kuzatuvchisi bor kamerani bu yerda
qayta tahlil qilinmaydi (u o'zi yozadi); yuzi tanib bo'lmas darajada kichik
kameralar kun davomida o'tkazib yuboriladi (recognition_stats.is_face_blind).

TARIX: 2026-09-18 da kunlik davomat faqat kirish kameralariga cheklangan edi. Ilgari xona kameralari
ham kunlik davomat uchun aylanardi: bir kunda ~5 kishini tanib, AI
vaqtining katta qismini olardi (yuzlar 8-20 px). Endi kunlik davomat faqat
kirish kameralarining doimiy kuzatuvchilarida (app/jobs/attendance_ai.py),
xona kameralari esa darsni jadval orqali tekshiradi (lesson_quality_ai.py).

Qaysi kamerada qaysi modul — app/services/camera_roles.py: uyqu faqat
auditoriyada, begona shaxs kirish/perimetr/cheklangan xonada.

Non-face modules (fire, pose, etc.) stay on their own loops.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.jobs.attendance_ai import (
    STAFF_ATTENDANCE_MODULE_CODE,
    STUDENT_ATTENDANCE_MODULE_CODE,
    _note_static_faces,
    is_watched,
    upsert_attendance_from_recognition,
)
from app.services import static_faces
from app.jobs.camera_health import is_reachable
from app.jobs.module_status import (
    camera_allows_module,
    camera_can_report_unauthorized,
    is_module_active,
    is_unauthorized_alert_time,
    load_suppressed_pairs,
)
from app.jobs.sweep_guard import SweepGuard
from app.jobs.sweep_concurrency import camera_sweep_slot
from app.jobs.unauthorized_person_ai import UNAUTHORIZED_MODULE_CODE, process_camera_frame_pair_for_unauthorized
from app.jobs.vision_ai import SLEEP_MODULE_CODE, process_camera_frame_for_sleep
from app.models import Camera, LessonSession
from app.services.camera_roles import role_allows
from app.services.face_matching import CandidateMatrix, load_candidate_matrix_for_sweep
from app.services import recognition_stats
from app.services.face_recognition import detect_faces
from app.services.face_recognition import recognizable_faces
from app.services.frame_grabber import (
    grab_frame_burst_for_camera,
    grab_frame_for_camera,
    grab_frame_pair_for_camera,
)
from app.services.presence import record_visit
from app.services.sweep_result_cache import record_camera_sweep
from app.timezone import local_now

logger = logging.getLogger("app.unified_face_sweep")

_sweep_guard = SweepGuard("unified_face_sweep")

# Nechanchi aylanish ketyapti — "ko'r" kameralarni vaqti-vaqti bilan
# qayta tekshirish uchun (recognition_stats.is_face_blind izohiga qarang).
# Ro'yxat sifatida: `global` e'lonisiz o'zgartirish uchun.
_sweep_round = [0]


def reset_sweep_round_for_tests() -> None:
    _sweep_round[0] = 0


def _skip_face_blind(camera: Camera, *, recheck: bool) -> bool:
    """Bu kamerani shu aylanishda o'tkazib yuboramizmi.

    Yuzi 8-20 pikselda ko'rinadigan kamera hech kimni tanimaydi, lekin
    har aylanishda kadr olish va model chaqirishni talab qiladi. Uni
    tashlab ketish sweep aylanishini qisqartiradi, ya'ni HAQIQATAN yuz
    ko'rinadigan kirish kameralari tezroq navbatga keladi."""
    if recheck:
        return False
    return recognition_stats.is_face_blind(str(camera.id))


def _allows(camera: Camera, module_code: int) -> bool:
    excluded = camera.excluded_module_codes
    return excluded is None or module_code not in excluded


async def _load_module_flags(db: AsyncSession) -> dict[str, bool]:
    staff = await is_module_active(db, STAFF_ATTENDANCE_MODULE_CODE)
    student = await is_module_active(db, STUDENT_ATTENDANCE_MODULE_CODE)
    return {
        "unauthorized": await is_module_active(db, UNAUTHORIZED_MODULE_CODE),
        "sleep": await is_module_active(db, SLEEP_MODULE_CODE),
        "attendance": settings.attendance_any_camera and (staff or student),
        # Tur bo'yicha (kirish kuzatuvchisi bilan bir qoida): 7-modul o'chiq
        # bo'lsa talabalar kelishi yozilmaydi, 6 — xodimlar.
        "staff_attendance": staff,
        "student_attendance": student,
    }


def _any_face_module(flags: dict[str, bool]) -> bool:
    return any(flags.get(k) for k in ("unauthorized", "sleep", "attendance"))


async def record_arrivals(
    db: AsyncSession,
    camera: Camera,
    faces: list,
    candidates: CandidateMatrix,
    flags: dict[str, bool] | None = None,
) -> int:
    """Kadrdagi ANIQ tanilgan (qat'iy chegara va ikkinchi nomzoddan uzoq)
    odamlar — tashrif va kunlik davomat (kunning birinchi ko'rinishi "keldi").
    Qaytaradi: nechta odam. Commit shu yerda.

    Kirish kuzatuvchisi (attendance_ai.process_camera_frame) bilan bir xil
    himoyalar: kamerada 6/7-modul ruxsati, odam turi bo'yicha modul, kichik
    yuz uchun yuqoriroq chegara va devordagi rasmlar (static_faces) — aks
    holda eshik oldidagi rektor portreti har kuni "keldi" yozardi."""
    flags = flags or {}
    staff_ok = flags.get("staff_attendance", True) and _allows(camera, STAFF_ATTENDANCE_MODULE_CODE)
    student_ok = flags.get("student_attendance", True) and _allows(camera, STUDENT_ATTENDANCE_MODULE_CODE)
    if not (staff_ok or student_ok):
        return 0
    camera_key = str(camera.id)
    faces, _skipped = static_faces.static_face_store.split(camera_key, faces)
    usable = recognizable_faces(faces)
    if not usable or candidates.is_empty:
        _note_static_faces(camera, camera_key, faces, [])
        return 0
    import numpy as np

    graded = candidates.graded_matches(
        np.stack([face.embedding for face in usable]),
        strict_threshold=settings.attendance_ai_match_threshold,
        relaxed_threshold=2.0,  # yumshoq moslik bu yerda qabul qilinmaydi
        margin=1.0,
        strict_margin=settings.attendance_ai_strict_margin,
    )
    moment = local_now()
    seen: set[str] = set()
    matched_boxes: list = []
    for face, match in zip(usable, graded, strict=True):
        if match.grade != "strict" or not match.person_id or match.person_id in seen:
            continue
        person_type = candidates.person_type(match.person_id)
        if (person_type == "xodim" and not staff_ok) or (person_type == "talaba" and not student_ok):
            continue
        if (
            recognition_stats.face_height_px(face) < settings.attendance_min_face_px
            and match.similarity < settings.attendance_small_face_match_threshold
        ):
            continue
        seen.add(match.person_id)
        matched_boxes.append(face.bbox)
        await record_visit(db, match.person_id, camera.id, moment, match.similarity)
        await upsert_attendance_from_recognition(db, match.person_id, moment, camera, off_hours_module_active=False)
    # Tanilgan joylar "tirik", qolganlari devordagi rasm nomzodi sifatida kuzatiladi.
    _note_static_faces(camera, camera_key, faces, matched_boxes)
    if seen:
        await db.commit()
    return len(seen)


async def _process_camera(
    camera: Camera,
    flags: dict[str, bool],
    candidates: CandidateMatrix,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, int]:
    counts = {"unauthorized": 0, "sleep": 0, "arrivals": 0}

    # Kunduzgi ko'rib chiqish ham xuddi shu kadr juftligini ishlatadi —
    # farqi faqat natijada (hodisa emas, ro'yxatga yozuv).
    review = flags.get("review", False)
    needs_unauthorized = (flags["unauthorized"] or review) and _allows(camera, UNAUTHORIZED_MODULE_CODE)
    needs_sleep = flags["sleep"] and _allows(camera, SLEEP_MODULE_CODE)
    needs_arrival = flags.get("arrival", False)

    if not any((needs_unauthorized, needs_sleep, needs_arrival)):
        return counts

    # Kadrlar SLOTDAN TASHQARIDA olinadi. Kalit kadr 4-8 s da bir keladi,
    # ya'ni 4 kadrlik burst 12-16 s kutadi — ilgari kamera shu vaqt
    # davomida umumiy slotlardan birini band qilib turardi va boshqa
    # kameralar shunchaki navbatda turardi. Kutish CPU olmaydi; slot faqat
    # tahlil (model + baza) uchun kerak.
    sleep_frames: list[bytes] = []
    pair: tuple[bytes, bytes] | None = None
    if needs_sleep:
        sleep_frames = await grab_frame_burst_for_camera(
            camera,
            count=settings.sleep_confirmation_frame_count,
            gap_seconds=settings.sleep_confirmation_gap_seconds,
        )

    if needs_unauthorized:
        # Reuse the sleep burst when there is one instead of grabbing a
        # SECOND set of frames from the same camera a second later. The
        # unauthorized check wants two frames far enough apart that one bad
        # angle can't fail both (see its module docstring) — the burst's
        # first and last are the most separated frames available.
        if len(sleep_frames) >= 2:
            pair = (sleep_frames[0], sleep_frames[-1])
        else:
            pair = await grab_frame_pair_for_camera(camera)

    arrival_frame: bytes | None = None
    if needs_arrival:
        arrival_frame = pair[0] if pair is not None else (sleep_frames[0] if sleep_frames else None)
        if arrival_frame is None:
            arrival_frame = await grab_frame_for_camera(camera)
        if arrival_frame is None:
            needs_arrival = False

    if not sleep_frames and pair is None and arrival_frame is None:
        return counts

    pre_detected: dict[int, list] = {}
    async with camera_sweep_slot():
        if needs_sleep and len(sleep_frames) >= 2:
            # Uyqu faqat yirik yuzda o'lchanadi (sleep_min_face_height_px).
            # Birinchi kadrda bunday yuz bo'lmasa, qolgan 3 kadrni tahlil
            # qilish befoyda — productionda (2026-09-24) yuzlarning 97% i
            # 40 px dan kichik edi, ya'ni har dars kamerasi har 30 s da 4
            # ta behuda tahlil olardi. Natija inference_cache'da qoladi:
            # quyida o'sha kadr qayta hisoblanmaydi.
            first = await detect_faces(sleep_frames[0])
            pre_detected[id(sleep_frames[0])] = first
            if not any(
                float(face.bbox[3] - face.bbox[1]) >= settings.sleep_min_face_height_px for face in first
            ):
                needs_sleep = False
                if not needs_unauthorized and not needs_arrival:
                    return counts
        # Every frame (the unauthorized pair, the sleep burst) needs its own
        # detect_faces() call, but they're independent inference calls on
        # independent frames — gathered concurrently, deduplicated by object
        # identity (the pair reuses burst frames, detected once).
        frames_needing_faces: list[bytes] = []
        if needs_unauthorized and pair is not None:
            for frame in pair:
                if not any(frame is f for f in frames_needing_faces):
                    frames_needing_faces.append(frame)
        if needs_sleep and len(sleep_frames) >= 2:
            for frame in sleep_frames:
                if not any(frame is f for f in frames_needing_faces):
                    frames_needing_faces.append(frame)
        if needs_arrival and arrival_frame is not None and not any(arrival_frame is f for f in frames_needing_faces):
            frames_needing_faces.append(arrival_frame)
        if not frames_needing_faces:
            return counts

        remaining = [frame for frame in frames_needing_faces if id(frame) not in pre_detected]
        detected = await asyncio.gather(*(detect_faces(frame) for frame in remaining))
        faces_by_frame_id = dict(pre_detected)
        faces_by_frame_id.update({id(frame): faces for frame, faces in zip(remaining, detected, strict=True)})

        async with session_factory() as db:
            if needs_arrival and arrival_frame is not None:
                try:
                    counts["arrivals"] = await record_arrivals(
                        db, camera, faces_by_frame_id[id(arrival_frame)], candidates, flags
                    )
                except Exception:
                    await db.rollback()
                    logger.warning("arrival recording failed", extra={"camera_id": str(camera.id)}, exc_info=True)
            if needs_unauthorized and pair is not None:
                frame_a, frame_b = pair
                if await process_camera_frame_pair_for_unauthorized(
                    frame_a,
                    frame_b,
                    db,
                    camera,
                    candidates=candidates,
                    faces_a=faces_by_frame_id[id(frame_a)],
                    faces_b=faces_by_frame_id[id(frame_b)],
                    review=review and not flags["unauthorized"],
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
        if needs_unauthorized:
            modules_run.append("unauthorized")
        if needs_sleep:
            modules_run.append("sleep")
        await record_camera_sweep(
            str(camera.id),
            face_count=len(faces_by_frame_id[id(frames_needing_faces[0])]),
            modules=modules_run,
            events_raised=sum(counts.values()),
        )

    return counts


async def cameras_in_lesson(db: AsyncSession) -> set[str]:
    """Hozir jadvaldagi darsi davom etayotgan kameralar."""
    now = local_now()
    result = await db.execute(
        select(LessonSession.camera_id)
        .where(LessonSession.camera_id.is_not(None))
        .where(LessonSession.scheduled_start_time <= now)
        .where(LessonSession.scheduled_start_time >= now - timedelta(minutes=settings.lesson_duration_minutes))
    )
    return {str(camera_id) for camera_id in result.scalars().all()}


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
                    camera_allows_module(UNAUTHORIZED_MODULE_CODE),
                    camera_allows_module(SLEEP_MODULE_CODE),
                    # Kelishni istalgan kamerada yozish — barcha faol kameralar.
                    true() if flags.get("attendance") else false(),
                )
            )
        )
        reachable_cameras = [c for c in result.scalars().all() if c.stream_url and is_reachable(c.last_seen_at)]
        candidates = await load_candidate_matrix_for_sweep(db)
        suppressed = await load_suppressed_pairs(db)
        lesson_cameras = await cameras_in_lesson(db) if flags["sleep"] and settings.sleep_only_during_lessons else None

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

    # Yuzi tanib bo'lmaydigan kameralarni shu aylanishda tashlab ketamiz
    # (_skip_face_blind izohiga qarang). Sanoq har aylanishda oshadi,
    # shuning uchun ular vaqti-vaqti bilan qayta tekshiriladi.
    _sweep_round[0] += 1
    recheck = (
        settings.face_blind_recheck_every <= 1
        or _sweep_round[0] % settings.face_blind_recheck_every == 0
    )
    cameras = [camera for camera in reachable_cameras if not _skip_face_blind(camera, recheck=recheck)]
    skipped_blind = len(reachable_cameras) - len(cameras)
    if skipped_blind:
        logger.info(
            "unified face sweep skipped cameras with no recognisable faces today",
            extra={"skipped": skipped_blind, "swept": len(cameras)},
        )

    totals = {"unauthorized": 0, "sleep": 0, "arrivals": 0}
    if not cameras:
        return totals

    # Begona shaxs (#1) faqat ruxsat etilgan vaqtda va kirish/perimetr
    # kamerasida tekshiriladi; uyqu (#20) faqat auditoriyada
    # (app/services/camera_roles.py); avtomatik o'chirilgan kamera×modul
    # juftliklari (app/jobs/module_suppression.py) tashlab ketiladi.
    alert_time = is_unauthorized_alert_time()

    def camera_flags(camera: Camera) -> dict[str, bool]:
        camera_id = str(camera.id)
        eligible = camera_can_report_unauthorized(camera) and role_allows(camera, UNAUTHORIZED_MODULE_CODE)
        return {
            "unauthorized": flags["unauthorized"]
            and alert_time
            and eligible
            and (camera_id, UNAUTHORIZED_MODULE_CODE) not in suppressed,
            # Kunduzi: signal emas, notanishlar ro'yxati. Avtomatik
            # o'chirilgan kameralar HAM qatnashadi — ular aynan yuzi
            # kiritilmagan talabalar ko'p ko'rinadigan joylar, ro'yxat esa
            # hech kimni bezovta qilmaydi va qamrovni o'stirish manbai.
            # Davomat kuzatuvchisi bu kamerani allaqachon tahlil qilsa, u
            # notanish yuzlarni o'zi yozadi (attendance_ai._review_unknown_faces)
            # — bu yerda o'sha kamerani ikkinchi marta tahlil qilish AI
            # vaqtini behuda yeydi.
            "review": flags["unauthorized"]
            and settings.unknown_review_enabled
            and not alert_time
            and eligible
            and not (settings.unknown_review_all_cameras and is_watched(camera_id)),
            # Kirish kuzatuvchisi bor kamerani qayta tahlil qilmaymiz.
            "arrival": flags.get("attendance", False)
            and not is_watched(camera_id)
            # Admin 6 va 7-modulni shu kamerada o'chirgan bo'lsa — kelish yozilmaydi.
            and (_allows(camera, STAFF_ATTENDANCE_MODULE_CODE) or _allows(camera, STUDENT_ATTENDANCE_MODULE_CODE)),
            "staff_attendance": flags.get("staff_attendance", False),
            "student_attendance": flags.get("student_attendance", False),
            "sleep": flags["sleep"]
            and role_allows(camera, SLEEP_MODULE_CODE)
            and (lesson_cameras is None or camera_id in lesson_cameras)
            and (camera_id, SLEEP_MODULE_CODE) not in suppressed,
        }

    results = await asyncio.gather(
        *(_process_camera(camera, camera_flags(camera), candidates, session_factory) for camera in cameras),
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
