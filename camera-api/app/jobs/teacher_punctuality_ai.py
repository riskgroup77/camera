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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.jobs.camera_health import is_reachable
from app.jobs.module_status import is_module_active
from app.jobs.sweep_guard import SweepGuard
from app.jobs.sweep_concurrency import camera_sweep_slot
from app.models import Event, LessonSession, StudentStaff
from app.schemas.event import EventOut
from app.services.event_bus import raise_event
from app.services.face_matching import (
    CandidateMatrix,
    find_best_match,
    load_candidate_matrix_for_sweep,
)
from app.services.face_recognition import detect_faces
from app.services.frame_grabber import grab_frame_pair_for_camera
from app.timezone import local_now, to_local
from app.ws import manager

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
    cutoff = local_now()
    result = await db.execute(
        select(LessonSession)
        .where(LessonSession.teacher_id.is_not(None))
        .where(LessonSession.camera_id.is_not(None))
        .where(LessonSession.scheduled_start_time.is_not(None))
        .where(LessonSession.punctuality_checked_at.is_(None))
    )
    due = []
    for row in result.scalars().all():
        if row.camera is None or PUNCTUALITY_MODULE_CODE in (row.camera.excluded_module_codes or []):
            continue
        deadline = row.scheduled_start_time + timedelta(minutes=settings.teacher_punctuality_grace_minutes)
        if deadline <= cutoff:
            due.append(row)
    return due


async def _find_known_staff(db: AsyncSession, faces, *, exclude_id) -> StudentStaff | None:
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
    matches = candidates.best_matches(embeddings, settings.attendance_ai_match_threshold)
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
            return person
    return None


def _matches_teacher(faces, teacher) -> bool:
    """Kadrda aynan rejadagi o'qituvchi bormi."""
    candidate = [(str(teacher.id), json.loads(teacher.biometric_embedding))]
    for face in faces:
        if find_best_match(face.embedding.tolist(), candidate, settings.attendance_ai_match_threshold) is not None:
            return True
    return False


async def check_lesson_session(session_row: LessonSession, db: AsyncSession) -> bool:
    """Grabs one frame from the session's assigned camera and checks
    whether the scheduled teacher is in it — see the module docstring for
    the full contract, including why a failed/unavailable check does NOT
    count as "absent". Returns True if an Event was raised."""
    camera = session_row.camera
    teacher = session_row.teacher_ref

    ran_check = False
    seen = False
    substitute: StudentStaff | None = None
    evidence_frame: bytes | None = None

    if camera and camera.stream_url and is_reachable(camera.last_seen_at) and teacher and teacher.biometric_embedding:
        async with camera_sweep_slot():
            frames = await grab_frame_pair_for_camera(camera)
        if frames is not None:
            frame_a, frame_b = frames
            evidence_frame = frame_b
            ran_check = True

            # Yangiroq kadrdan boshlaymiz. O'qituvchi shu yerda topilsa —
            # tekshiruv tugadi va ikkinchi kadr umuman tahlil qilinmaydi.
            faces_b = await detect_faces(frame_b)
            seen = bool(faces_b) and _matches_teacher(faces_b, teacher)

            if not seen:
                faces_a = await detect_faces(frame_a)
                seen = bool(faces_a) and _matches_teacher(faces_a, teacher)

                if not seen:
                    # Ikkala kadrda ham yo'q. Endi almashinuvni
                    # tekshiramiz: BIR XIL boshqa xodim ikkalasida ham
                    # bo'lsagina almashinuv deb hisoblanadi.
                    substitute_b = await _find_known_staff(db, faces_b, exclude_id=teacher.id)
                    if substitute_b is not None:
                        substitute_a = await _find_known_staff(db, faces_a, exclude_id=teacher.id)
                        if substitute_a is not None and substitute_a.id == substitute_b.id:
                            substitute = substitute_b

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
        # savolga faqat rasm javob beradi. #22 esa tarixiy sabablarga
        # ko'ra Event'ni qo'lda quradi (pastda).
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
            confidence=85,
            severity="o'rta",
            frame_bytes=evidence_frame,
            person_name=f"{substitute.full_name} ({teacher.full_name} o'rniga)",
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

    event = Event(
        camera_id=camera.id,
        camera_name=camera.name,
        building=camera.building.name if camera.building else "",
        module_code=PUNCTUALITY_MODULE_CODE,
        module_name=PUNCTUALITY_MODULE_NAME,
        group="E",
        confidence=70,  # a real single-frame detection attempt, not a pure rule — see module docstring
        severity="o'rta",
        person_name=teacher.full_name if teacher else None,
        status="yangi",
    )
    db.add(event)
    await db.flush()
    event_out = EventOut(
        id=str(event.id),
        timestamp=to_local(event.occurred_at).strftime("%Y-%m-%d %H:%M"),
        camera_id=str(event.camera_id) if event.camera_id else "",
        camera_name=event.camera_name,
        building=event.building,
        module_code=event.module_code,
        module_name=event.module_name,
        group=event.group,
        confidence=event.confidence,
        severity=event.severity,
        status=event.status,
        person_name=event.person_name,
        reviewed_by=event.reviewed_by,
    )
    await db.commit()
    await manager.broadcast(event_out.model_dump(by_alias=True))
    return True


async def run_teacher_punctuality_sweep_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """Checks every due LessonSession (see _due_sessions), one DB session
    per row (matches the other AI sweep loops' pattern — see
    app/jobs/attendance_ai.py's run_attendance_ai_sweep_once). Returns how
    many "not on time" Events were raised."""
    async with session_factory() as db:
        if not await is_module_active(db, PUNCTUALITY_MODULE_CODE):
            return 0
        due = await _due_sessions(db)

    if not due:
        return 0

    async def _process_one(session_id) -> bool:
        async with session_factory() as db:
            row = await db.get(LessonSession, session_id)
            if row is None or row.punctuality_checked_at is not None:
                return False  # already handled by a previous tick/another worker
            return await check_lesson_session(row, db)

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
