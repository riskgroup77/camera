"""TT kriteriya 22 ("O'qituvchining darsga aniq kelishi") va 26
("O'qituvchi o'rniga boshqasi kirgani") — checks whether the scheduled
teacher was actually seen (via face recognition) at the assigned camera
by the end of a grace period after the lesson's scheduled start time,
and if not, whether somebody else on staff was there instead.

Ikkala kriteriya bitta kadr va bitta detect_faces() chaqiruvidan
foydalanadi — #26 qo'shimcha kamera so'rovi ham, qo'shimcha inference
ham keltirmaydi.

Reuses the same InsightFace pipeline as app/jobs/attendance_ai.py rather
than introducing anything new — a single frame grab + detect_faces +
match against the teacher's own enrolled embedding is enough. Doesn't
reuse attendance_ai's AttendanceRecord upsert logic, though: that's a
building-wide "first sighting of the day" signal, not "is this specific
person in this specific room at this specific time", which is what this
criterion actually asks.

A LessonSession only becomes checkable once teacher_id/camera_id/
scheduled_start_time are all set (see app/models/lesson_session.py) —
rows missing any of the three (the common case today, since no
scheduling UI exists yet to populate them) are simply invisible to this
job, same "not configured yet" behavior as a camera with no stream_url
in the other AI jobs.

Checked exactly ONCE, settings.teacher_punctuality_grace_minutes after
the scheduled start — not polled continuously through the grace window —
so a teacher arriving with a minute to spare and one arriving right at
the bell both read as "on time", matching how the TT criterion is
phrased (present by lesson start, not present impossibly early).

Ikki-kadrli tasdiqlash (2026-09-07 dan). Ilgari bu tekshiruv BITTA
kadrga asoslanardi va bu jiddiy nuqson edi: o'sha bir kadrda o'qituvchi
doskaga o'girilib turgan, boshqa odam ortida qolgan yoki ko'zini yumgan
bo'lishi — ya'ni yuz aniqlanmasligi — mumkin, va natijada haqiqatan
darsda bo'lgan odam "kelmadi" deb yozilardi. Endi kamera bir necha
soniya oralig'ida ikkita kadr beradi va o'qituvchi IKKALASIDA ham
topilmasagina yo'q deb hisoblanadi. Odatiy holatda (o'qituvchi joyida)
narx o'zgarmaydi: ikkinchi kadr faqat birinchisi uni topmagandagina
tahlil qilinadi.

Xuddi shu tasdiqlash #26 ga ham tegishli, undan ham qattiqroq shaklda:
almashinuv deb hisoblash uchun AYNAN BIR XIL boshqa xodim ikkala kadrda
ham tanilishi kerak. Sababi aniq — auditoriyada boshqa xodimning bir
lahzaga ko'rinib o'tishi (laborant, kolleg) tabiiy hodisa; darsni olib
borayotgan odam esa ikkala kadrda ham o'sha yerda bo'ladi.

Honest scope note: if the camera is unreachable or no frame is available
at check time, this does NOT mark the teacher absent — accusing someone
of missing a class because the camera itself failed would be a real
false-accusation risk, worse than just not knowing. Those rows are
marked checked (so they aren't retried forever) but raise no Event and
leave teacher_on_time at its default. Only a genuine "camera worked,
face detection ran, this specific teacher's embedding didn't match
any detected face" produces a "not on time" Event — still a single-frame
signal (unlike attendance_ai's off-hours rule, which is 100%-confidence
because it's pure arithmetic on a timestamp), so its confidence is set
accordingly lower, not treated as certain.
"""

import asyncio
import json
import logging
import uuid
from datetime import timedelta

import numpy as np

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.services.confidence import exceed_confidence
from app.database import SessionLocal
from app.jobs.camera_health import is_reachable
from app.jobs.module_status import is_module_active
from app.jobs.sweep_guard import SweepGuard
from app.models import FaceGalleryEmbedding, LessonSession, StudentStaff
from app.services.event_bus import raise_event
from app.services.face_matching import (
    CandidateMatrix,
    find_best_match,
    load_candidate_matrix_for_sweep,
)
from app.services.face_recognition import detect_faces, recognizable_faces
from app.services.frame_grabber import grab_frame_pair_for_camera
from app.timezone import local_now, to_local

logger = logging.getLogger("app.teacher_punctuality_ai")

PUNCTUALITY_MODULE_CODE = 22
PUNCTUALITY_MODULE_NAME = "O'qituvchining darsga aniq kelishi"

SUBSTITUTION_MODULE_CODE = 26
SUBSTITUTION_MODULE_NAME = "O'qituvchi o'rniga boshqasi kirgani"
"""Rejadagi o'qituvchi o'rniga boshqa xodim darsga kirgani.

Bu #22 bilan bitta kadrdan aniqlanadi va qo'shimcha protsessor yuki
talab qilmaydi: kadr allaqachon olingan, unda topilgan yuzlar
allaqachon hisoblangan. Farq faqat solishtirish doirasida — #22 faqat
rejadagi o'qituvchini qidiradi, bu esa BARCHA ro'yxatdan o'tgan
xodimlarni.

Uch xil natija bir-biridan aniq ajratiladi:

  rejadagi o'qituvchi bor            -> hodisa yo'q, dars o'z holida
  u yo'q, boshqa tanilgan xodim bor  -> #26 almashinuv
  u yo'q, tanilgan hech kim yo'q     -> #22 kelmagan

Uchinchi holat ikkinchisidan jiddiy farq qiladi: birida dars o'tilyapti,
faqat boshqa odam tomonidan; ikkinchisida xonada mas'ul shaxs umuman
yo'q. Ilgari ikkalasi ham bir xil "kelmadi" signali edi."""

# See app/jobs/attendance_ai.py's _camera_semaphore docstring — same
# rationale, own semaphore so this job can't starve (or be starved by)
# the other AI sweep loops' camera slots.
_sweep_guard = SweepGuard("teacher_punctuality_ai")


async def _due_sessions(db: AsyncSession) -> list[LessonSession]:
    """Sessions ready to be checked: fully scheduled, not yet checked, and
    past their grace deadline (scheduled_start_time + grace). Filtered in
    Python (not the query) against the camera's excluded_module_codes —
    LessonSession.camera is lazy="joined" so this is free (already loaded,
    no extra query), and the "due" set is small (only sessions past their
    deadline right now), unlike the hundreds-of-cameras case the other
    sweep loops' queries are optimizing for."""
    now = local_now()
    started_before = now - timedelta(minutes=settings.teacher_punctuality_grace_minutes)
    oldest_checkable = started_before - timedelta(minutes=settings.teacher_punctuality_check_window_minutes)
    unchecked = (
        LessonSession.teacher_id.is_not(None),
        LessonSession.camera_id.is_not(None),
        LessonSession.punctuality_checked_at.is_(None),
    )

    # Tekshiruv payti allaqachon o'tib ketgan darslar: hozirgi kadr ular
    # haqida hech narsa demaydi (o'tgan sana bilan import qilingan jadval,
    # yoki server o'sha paytda ishlamagan). Tekshirilmagan holda yopiladi —
    # teacher_on_time o'zgarmaydi, signal yozilmaydi.
    expired = await db.execute(
        update(LessonSession)
        .where(*unchecked)
        .where(LessonSession.scheduled_start_time < oldest_checkable)
        .values(punctuality_checked_at=now)
    )
    if expired.rowcount:
        await db.commit()
        logger.warning(
            "lessons past their punctuality check window closed without a check",
            extra={"lessons": expired.rowcount, "window_minutes": settings.teacher_punctuality_check_window_minutes},
        )

    # Dam olish kuni / bayram: jadvalda dars tursa ham bo'sh xona "kelmadi" emas.
    from app.models import AttendanceRecord
    from app.services.attendance_policy import load_policy
    from app.timezone import business_date

    today = business_date(now)
    if not (await load_policy(db)).is_work_day(today):
        return []

    result = await db.execute(
        select(LessonSession)
        .where(*unchecked)
        .where(LessonSession.scheduled_start_time <= started_before)
        .where(LessonSession.scheduled_start_time >= oldest_checkable)
    )
    rows = [
        row
        for row in result.scalars().unique().all()
        if row.camera is not None and PUNCTUALITY_MODULE_CODE not in (row.camera.excluded_module_codes or [])
    ]
    if not rows:
        return rows
    # Ta'tildagi (admin "dam_olish" kiritgan) o'qituvchi darsi tekshirilmaydi.
    on_leave = set(
        (
            await db.execute(
                select(AttendanceRecord.student_staff_id).where(
                    AttendanceRecord.date == today,
                    AttendanceRecord.status == "dam_olish",
                    AttendanceRecord.student_staff_id.in_({row.teacher_id for row in rows}),
                )
            )
        ).scalars()
    )
    return [row for row in rows if row.teacher_id not in on_leave]


async def _find_known_staff(db: AsyncSession, faces, *, exclude_id) -> tuple[StudentStaff, float] | None:
    """Kadrdagi yuzlar orasidan ro'yxatdan o'tgan XODIMni topadi.

    Faqat xodimlar tekshiriladi: auditoriyada talaba bo'lishi tabiiy va u
    darsni olib borayotgan shaxs emas — talabalarni ham qidirish har bir
    darsni "almashinuv" deb e'lon qilardi. Rejadagi o'qituvchining o'zi
    chiqarib tashlanadi: u allaqachon tekshirilgan va topilmagan.

    Butun tizim ishlatadigan bitta keshlangan CandidateMatrix ustida
    ishlaydi (app/services/face_matching.py) — alohida SQL so'rovi emas.
    Bu ikki jihatdan muhim: kesh FAISS indeksidan foydalanadi, va
    embeddinglar bir joyda yuklanadi, ya'ni bu kriteriya minglab
    ro'yxatdagi odam bo'lganda ham qo'shimcha yuk bermaydi.
    """
    if not faces:
        return None

    candidates: CandidateMatrix = await load_candidate_matrix_for_sweep(db)
    if candidates.is_empty:
        return None

    exclude = str(exclude_id)
    embeddings = np.stack([face.embedding for face in faces])
    # #26 signali aniq odamni nomlaydi ("o'qituvchi o'rniga X kirgan"),
    # shuning uchun noaniq moslik umuman qabul qilinmaydi.
    matches = candidates.best_matches(
        embeddings, settings.attendance_ai_match_threshold, margin=settings.attendance_ai_strict_margin
    )
    for match in matches:
        if match is None:
            continue
        person_id = match[0]
        if person_id == exclude:
            continue
        if candidates.person_types.get(person_id) != "xodim":
            continue
        person = await db.get(StudentStaff, uuid.UUID(person_id))
        if person is not None:
            return person, float(match[1])
    return None


def _substitution_confidence(similarity: float | None) -> int:
    """Boshqa xodimning yuz mosligi qanchalik kuchli: chegarada 70, 0.9+ da 95."""
    threshold = settings.attendance_ai_match_threshold
    if similarity is None or threshold <= 0:
        return 70
    return exceed_confidence(similarity, threshold, floor=70, ceiling=95, full_at=0.9 / threshold)


async def _teacher_embeddings(db: AsyncSession, teacher) -> list[list[float]]:
    """O'qituvchining asosiy rasmi VA kamera galereyasidagi namunalari.

    Ilgari faqat ro'yxatdan o'tish rasmi bilan solishtirilardi: doskaga
    qarab turgan yoki kamera burchagidan ko'ringan o'qituvchi tanilmay,
    "darsga kelmadi" hodisasi yozilardi. Galereya — shu kameralardan
    olingan, tasdiqlangan yuzlar."""
    vectors = [json.loads(teacher.biometric_embedding)]
    rows = await db.execute(
        select(FaceGalleryEmbedding.embedding).where(FaceGalleryEmbedding.student_staff_id == teacher.id)
    )
    for raw in rows.scalars().all():
        try:
            vectors.append(json.loads(raw))
        except (TypeError, ValueError):
            continue
    return vectors


def _matches_teacher(faces, teacher, embeddings: list[list[float]] | None = None) -> bool:
    """Kadrda aynan rejadagi o'qituvchi bormi.

    Bitta odamga solishtirilgani uchun (8000 kishilik ro'yxatga emas)
    yumshoq chegara xavfsiz: boshqa odam bilan adashish ehtimoli yo'q."""
    vectors = embeddings or [json.loads(teacher.biometric_embedding)]
    candidate = [(str(teacher.id), vector) for vector in vectors]
    threshold = min(settings.attendance_ai_match_threshold, settings.attendance_ai_relaxed_threshold)
    for face in faces:
        if find_best_match(face.embedding.tolist(), candidate, threshold) is not None:
            return True
    return False


def _has_judgeable_face(*face_lists) -> bool:
    """Kadrda tanish mumkin bo'lgan darajada yirik yuz bormi. Bo'lmasa
    "o'qituvchi yo'q" degan xulosa asossiz — kamera shunchaki hech kimni
    aniq ko'rmagan (productionda yuzlarning 97% i 40 px dan kichik)."""
    return any(
        (face.bbox[3] - face.bbox[1]) >= settings.attendance_min_face_px
        for faces in face_lists
        for face in faces or []
        if getattr(face, "bbox", None) is not None
    )


async def check_lesson_session(
    session_row: LessonSession,
    db: AsyncSession,
    *,
    punctuality_active: bool = True,
    substitution_active: bool = True,
) -> bool:
    """Grabs one frame from the session's assigned camera and checks
    whether the scheduled teacher is in it — see the module docstring for
    the full contract, including why a failed/unavailable check does NOT
    count as "absent". Returns True if an Event was raised."""
    camera = session_row.camera
    teacher = session_row.teacher_ref

    ran_check = False
    seen = False
    substitute: StudentStaff | None = None
    substitute_similarity: float | None = None
    # Ikkala kadrda ham odam yuzlari bor, lekin o'qituvchi ular orasida yo'q —
    # "kamera hech kimni ko'rmadi" holatidan kuchliroq dalil.
    faces_in_both = False
    judgeable = True
    evidence_frame: bytes | None = None

    # Faolsizlantirilgan o'qituvchining yuzi solishtirilmaydi (app/routers/privacy.py).
    if (
        camera
        and camera.stream_url
        and is_reachable(camera.last_seen_at)
        and teacher
        and teacher.active
        and teacher.biometric_embedding
    ):
        # Slot kalit kadrni kutish uchun olinmaydi: tekshiruv darsga bir marta,
        # model chaqiruvlarini esa face_inference_gate cheklaydi.
        frames = await grab_frame_pair_for_camera(camera)
        if frames is not None:
            frame_a, frame_b = frames
            evidence_frame = frame_b
            ran_check = True

            # Yangiroq kadrdan boshlaymiz. O'qituvchi shu yerda topilsa —
            # tekshiruv tugadi va ikkinchi kadr umuman tahlil qilinmaydi.
            # Solishtirish faqat tahlil qilingan (yetarlicha katta) yuzlar
            # bilan; "kadrda odam bor" degan xulosa esa barcha yuzlardan.
            teacher_vectors = await _teacher_embeddings(db, teacher)
            faces_b = await detect_faces(frame_b)
            usable_b = recognizable_faces(faces_b)
            seen = bool(usable_b) and _matches_teacher(usable_b, teacher, teacher_vectors)

            if not seen:
                faces_a = await detect_faces(frame_a)
                usable_a = recognizable_faces(faces_a)
                seen = bool(usable_a) and _matches_teacher(usable_a, teacher, teacher_vectors)

                if not seen:
                    # Bo'sh xona (hech qanday yuz yo'q) — o'zi dalil. Faqat
                    # yuzlar BOR-u, hammasi mayda bo'lsa, xulosa chiqarilmaydi.
                    judgeable = not (faces_a or faces_b) or _has_judgeable_face(faces_a, faces_b)
                    faces_in_both = bool(faces_a) and bool(faces_b)
                    # Ikkala kadrda ham yo'q. Endi almashinuvni
                    # tekshiramiz: BIR XIL boshqa xodim ikkalasida ham
                    # bo'lsagina almashinuv deb hisoblanadi (#26 o'chirilgan
                    # bo'lsa umuman qidirilmaydi).
                    found_b = (
                        await _find_known_staff(db, usable_b, exclude_id=teacher.id) if substitution_active else None
                    )
                    if found_b is not None:
                        found_a = await _find_known_staff(db, usable_a, exclude_id=teacher.id)
                        if found_a is not None and found_a[0].id == found_b[0].id:
                            substitute = found_b[0]
                            substitute_similarity = min(found_a[1], found_b[1])

    session_row.punctuality_checked_at = local_now()

    if not ran_check:
        logger.info(
            "teacher punctuality check skipped (camera/frame/enrollment unavailable)",
            extra={"lesson_session_id": str(session_row.id)},
        )
        await db.commit()
        return False

    session_row.teacher_on_time = seen
    if seen:
        await db.commit()
        return False

    if substitute is not None:
        # Almashinuv hodisasi raise_event orqali yoziladi, chunki bu yerda
        # DALIL RASM hal qiluvchi ahamiyatga ega: "kim kirgan" degan
        # savolga faqat rasm javob beradi.
        event = await raise_event(
            db,
            camera=camera,
            module_code=SUBSTITUTION_MODULE_CODE,
            module_name=SUBSTITUTION_MODULE_NAME,
            group="E",
            # Ikki mustaqil dalil: rejadagi o'qituvchi ikkala kadrda ham
            # yo'q, VA bir xil boshqa xodim ikkalasida ham bor. Ikkinchisi
            # ijobiy yuz mosligi — tizimdagi eng ishonchli signal turi.
            # 100 emas: "boshqa xodim xonada" va "u dars o'tyapti" bir xil
            # narsa emas, buni faqat operator rasmga qarab hal qiladi.
            confidence=_substitution_confidence(substitute_similarity),
            severity="o'rta",
            frame_bytes=evidence_frame,
            person_name=f"{substitute.full_name} ({teacher.full_name} o'rniga)",
            details={
                "reason": (
                    "Jadvaldagi o'qituvchi ikkala kadrda ham yo'q, o'rniga boshqa xodim bor"
                    + (f" (o'xshashlik {substitute_similarity:.2f})" if substitute_similarity is not None else "")
                ),
            },
        )
        logger.info(
            "teacher substitution detected",
            extra={
                "lesson_session_id": str(session_row.id),
                "scheduled": teacher.full_name,
                "present": substitute.full_name,
                "suppressed_by_threshold": event is None,
            },
        )
        # Chegara hodisani rad etgan bo'lsa (event is None) ham qaytarish
        # True: tekshiruv o'z ishini bajardi va #22 "kelmadi" hodisasi bu
        # yerda YOZILMASLIGI kerak — o'qituvchi o'rniga odam bor, bu
        # "hech kim kelmadi" bilan bir xil holat emas.
        await db.commit()
        return event is not None

    if not punctuality_active:
        await db.commit()
        return False

    if not judgeable:
        # Kamera birorta ham aniq yuz ko'rmadi — "kelmadi" deb ayblab
        # bo'lmaydi. Holat noma'lum qoladi (operator jadvalda ko'radi).
        session_row.teacher_on_time = None
        logger.info(
            "teacher punctuality undetermined: no face large enough to judge",
            extra={"lesson_session_id": str(session_row.id)},
        )
        await db.commit()
        return False

    # raise_event orqali — boshqa modullar kabi sinov rejimi, modul chegarasi
    # va dalil rasmi shu yerda ham qo'llanadi. Ilgari Event bevosita
    # yaratilardi: #22 sinovga o'tkazilsa ham signal operatorga ketardi.
    event = await raise_event(
        db,
        camera=camera,
        module_code=PUNCTUALITY_MODULE_CODE,
        module_name=PUNCTUALITY_MODULE_NAME,
        group="E",
        confidence=80 if faces_in_both else 70,
        severity="o'rta",
        frame_bytes=evidence_frame,
        person_name=teacher.full_name if teacher else None,
        details={
            "reason": "Dars boshlanganidan keyin o'qituvchi xonada ko'rinmadi"
            + (" — xonada boshqa odamlar bor" if faces_in_both else ""),
        },
    )
    await db.commit()
    return event is not None


async def run_teacher_punctuality_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """Checks every due LessonSession (see _due_sessions), one DB session
    per row (matches the other AI sweep loops' pattern — see
    app/jobs/attendance_ai.py's run_attendance_ai_sweep_once). Returns how
    many "not on time" Events were raised."""
    async with session_factory() as db:
        punctuality_active = await is_module_active(db, PUNCTUALITY_MODULE_CODE)
        substitution_active = await is_module_active(db, SUBSTITUTION_MODULE_CODE)
        if not punctuality_active and not substitution_active:
            return 0
        due = await _due_sessions(db)

    if not due:
        return 0

    async def _process_one(session_id) -> bool:
        async with session_factory() as db:
            row = await db.get(LessonSession, session_id)
            if row is None or row.punctuality_checked_at is not None:
                return False  # already handled by a previous tick/another worker
            return await check_lesson_session(
                row,
                db,
                punctuality_active=punctuality_active,
                substitution_active=substitution_active,
            )

    results = await asyncio.gather(*(_process_one(row.id) for row in due), return_exceptions=True)

    raised = 0
    for row, result in zip(due, results, strict=True):
        if isinstance(result, BaseException):
            logger.exception(
                "teacher punctuality check failed", extra={"lesson_session_id": str(row.id)}, exc_info=result
            )
            continue
        if result:
            raised += 1
    return raised


async def teacher_punctuality_ai_loop() -> None:
    while True:
        try:
            count = await _sweep_guard.run(run_teacher_punctuality_sweep_once)
            if count:
                logger.info("teacher punctuality sweep raised events", extra={"events": count})
        except Exception:
            logger.exception("teacher punctuality sweep failed")
        await asyncio.sleep(settings.teacher_punctuality_interval_seconds)
