"""Public (no-auth) self-service biometric enrollment — lets a student/staff
member whose record was bulk-imported without a photo (see the Excel import
this backs) attach their own face, instead of every person needing an
admin operator to run them through AddStudentStaffModal.tsx by hand.

TIRIKLIK TEKSHIRUVI. Yuz kamera orqali, uch bosqichda olinadi: to'g'riga
qarash, chapga burilish, o'ngga burilish. Tayyor rasm yuklash bekor
qilindi — u zaif dalil edi: boshqa odamning rasmini, telefon ekranidagi
suratni yoki qog'ozga bosilgan fotosuratni yuborib bo'lardi.

Tekshiruv IKKI joyda bajariladi va bu takror emas. Mijoz jonli
yo'naltirish uchun /pose-check ni chaqiradi — bu odamga «hozir to'g'ri
turibsizmi» deb ko'rsatish uchun. Yakuniy hukm esa /submit da, serverda,
uch kadrning hammasi birga kelganda chiqariladi: mijozga ishonib
bo'lmaydi, u istalgan javobni o'zi yozib yuborishi mumkin.

Shaxs ikki yo'ldan biri bilan aniqlanadi: JSHSHIR (14 raqam) yoki
pasport seriyasi va raqami. Bu yozuvlarning o'z logini va paroli yo'q,
ya'ni bu JWT sessiya emas — shunchaki "qaysi mavjud qator bu odam" degan
savolga javob.

JSHSHIR asosiy yo'l: institut kadrlar ro'yxati aynan shu raqam bilan
yuritiladi va ommaviy import qilingan xodimlarda pasport ma'lumotlari
umuman yo'q. Pasport yo'li ilgari shu tarzda ro'yxatdan o'tganlar uchun
saqlanadi.

Ikkala endpoint ham IP bo'yicha cheklangan (app/rate_limit.py): bu
raqamlar kuchli sir emas va ommaviy taxmin qilishga yo'l qo'yib
bo'lmaydi.

/submit re-checks passport_series/passport_number itself (not just
record_id) so a client can't skip /lookup and brute-force record ids
directly, and refuses to overwrite an already-confirmed enrollment —
self-service is for filling in a MISSING photo, not for silently replacing
someone else's already-verified one; an admin has to do that deliberately
via the existing /api/students-staff/{id}/biometrics endpoint.
"""

import asyncio
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Faculty, StudentStaff
from app.rate_limit import limiter
from app.schemas.enrollment import (
    EnrollmentFacultyOut,
    PoseCheckOut,
    EnrollmentLookupIn,
    EnrollmentLookupOut,
    EnrollmentRegisterIn,
    EnrollmentSubmitOut,
)
from app.services.face_matching import invalidate_candidate_matrix_cache
from app.services.inference_gate import PRIORITY_LIVE
from app.services.face_recognition import (
    InconsistentFacesError,
    NoFaceDetectedError,
    detect_faces,
    extract_enrollment_embedding,
)
from app.services.head_pose import (
    DIRECTION_LABELS,
    direction_of,
    face_height,
    is_close_enough,
    turn_ratio,
)
from app.storage import delete_files_quietly, upload_file

logger = logging.getLogger("app.enrollment")

router = APIRouter(prefix="/api/public/enrollment", tags=["enrollment"])

MAX_PHOTO_SIZE_BYTES = 10 * 1024 * 1024
#: Jonli yo'naltirish kadri — kichraytirilgan holda keladi.
MAX_POSE_FRAME_BYTES = 2 * 1024 * 1024
MIN_FRAMES = 1
"""Bitta rasm ham yetarli.

Avval 2 ta talab qilinardi, chunki oqim faqat kameradan ko'p burchakli
suratga olishni bilardi va bir nechta kadr o'rtachasi bitta kadrdan
ishonchliroq. Endi odam tayyor rasmini yuklashi mumkin, va u yerda
"ikkinchi burchak" degan tushuncha yo'q.

E'tiborga loyiq narsa: yuklangan rasm jonli suratga olishdan ZAIFROQ
dalil — uni boshqa odamning rasmi bilan almashtirib bo'ladi. Bu mahsulot
qarori, xavfsizlik jihatidan emas: jarayonni oddiylashtirish uchun
qabul qilingan."""
MAX_FRAMES = 6

#: Tiriklik tekshiruvining bosqichlari — AYNAN shu tartibda.
#:
#: Uch bosqich tanlangani tasodif emas. Bitta kadr statik rasmni
#: ajratmaydi. Ikkita kadr (to'g'ri + burilgan) allaqachon ancha kuchli,
#: lekin ikkala tomonga burish yuzning har ikki yon tomonini ham
#: ko'rsatadi va o'rtacha vektorni sezilarli aniqroq qiladi — keyinchalik
#: kamera odamni qaysi tomondan ko'rishidan qat'i nazar taniydi.
LIVENESS_STEPS: tuple[str, ...] = ("front", "left", "right")


def _pose_hint(faces: int, direction: str | None, close: bool, expected: str) -> str:
    """Foydalanuvchiga nima qilish kerakligini bir jumlada aytadi."""
    if faces == 0:
        return "Yuzingiz ko'rinmayapti — kameraga qarang"
    if faces > 1:
        return "Kadrda bir nechta odam bor — yolg'iz qoling"
    if not close:
        return "Yaqinroq keling"
    if direction == expected:
        return "Yaxshi, shu holatda turing"
    label = DIRECTION_LABELS.get(expected, expected)
    if direction is None:
        return f"Biroz ko'proq buring — {label}"
    return label.capitalize()



def _normalize(series: str | None, number: str | None) -> tuple[str, str]:
    return (series or "").strip().upper(), (number or "").strip()


def _normalize_pinfl(value: str | None) -> str:
    """JSHSHIR dan raqamdan boshqa hamma narsani olib tashlaymiz.

    Odam uni ko'chirib qo'yganda bo'sh joy, chiziqcha yoki ko'rinmas
    belgilar qo'shilib qolishi juda tez-tez uchraydi. Bu yerda ularni
    tashlab yubormasak, raqami to'g'ri bo'lgan odam "topilmadi" degan
    javob olardi va sababini tushunmasdi."""
    return "".join(ch for ch in (value or "") if ch.isdigit())


async def _find_by_pinfl(db: AsyncSession, pinfl: str) -> StudentStaff | None:
    result = await db.execute(select(StudentStaff).where(StudentStaff.pinfl == pinfl))
    return result.scalar_one_or_none()


async def _find_by_passport(db: AsyncSession, series: str, number: str) -> StudentStaff | None:
    result = await db.execute(
        select(StudentStaff)
        .where(StudentStaff.passport_series == series)
        .where(StudentStaff.passport_number == number)
    )
    return result.scalar_one_or_none()


async def _find_person(
    db: AsyncSession, pinfl: str | None, series: str | None, number: str | None
) -> StudentStaff | None:
    """JSHSHIR yoki pasport bo'yicha qidiradi — qaysi biri berilgan bo'lsa."""
    clean_pinfl = _normalize_pinfl(pinfl)
    if clean_pinfl:
        return await _find_by_pinfl(db, clean_pinfl)
    s, n = _normalize(series, number)
    if s and n:
        return await _find_by_passport(db, s, n)
    return None


def _lookup_out(record: StudentStaff) -> EnrollmentLookupOut:
    return EnrollmentLookupOut(
        record_id=str(record.id),
        full_name=record.full_name,
        type_label="Talaba" if record.type == "talaba" else "Xodim",
        group_or_position=record.group_or_position,
        already_enrolled=record.biometrics_status == "tasdiqlangan",
    )


@router.post("/lookup", response_model=EnrollmentLookupOut)
@limiter.limit("5/minute")
async def lookup_person(
    request: Request,
    body: EnrollmentLookupIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EnrollmentLookupOut:
    record = await _find_person(db, body.pinfl, body.passport_series, body.passport_number)
    if record is None:
        detail = (
            "Bunday JSHSHIR bilan yozuv topilmadi"
            if body.pinfl
            else "Bunday pasport ma'lumotlari bilan yozuv topilmadi"
        )
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail)
    return _lookup_out(record)


@router.get("/faculties", response_model=list[EnrollmentFacultyOut])
async def list_faculties(db: Annotated[AsyncSession, Depends(get_db)]) -> list[EnrollmentFacultyOut]:
    """Ro'yxatdan o'tish formasidagi fakultet ro'yxati.

    Ochiq, chunki forma ham ochiq — hisobi yo'q odam aynan shu yerda
    ro'yxatdan o'tadi. Faqat id va nom qaytariladi: talabalar soni kabi
    ichki ko'rsatkichlar bu yerga kerak emas."""
    result = await db.execute(select(Faculty).order_by(Faculty.name))
    return [EnrollmentFacultyOut(id=str(f.id), name=f.name) for f in result.scalars().all()]


@router.post("/register", response_model=EnrollmentLookupOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
async def register_self(
    request: Request,
    body: EnrollmentRegisterIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EnrollmentLookupOut:
    """Tizimda yozuvi yo'q odam o'zini o'zi ro'yxatdan o'tkazadi.

    Ilgari bunday odam uchun yo'l yo'q edi: pasport topilmasa 404 qaytardi
    va jarayon shu yerda tugardi — administrator qo'lda kiritishi kerak
    edi.

    Yaratilgan yozuv biometrics_status='yoq' bilan boshlanadi: bu faqat
    shaxs ma'lumoti, hali yuz emas. Yuz keyingi qadamda qo'shiladi va
    aynan o'sha yerda 'tasdiqlangan' bo'ladi.

    Cheklov (3/minute) va pasport takrorlanmasligi tekshiruvi ataylab:
    endpoint ochiq, ya'ni uni bazani to'ldirish uchun ishlatib bo'lmasligi
    kerak."""
    pinfl = _normalize_pinfl(body.pinfl)
    series, number = _normalize(body.passport_series, body.passport_number)

    existing = await _find_person(db, body.pinfl, body.passport_series, body.passport_number)
    if existing is not None:
        # Yozuv allaqachon bor — yangisini yaratmaymiz, borini qaytaramiz.
        # Aks holda bitta odam uchun ikkita yozuv paydo bo'lardi va
        # davomat ikkiga bo'linib ketardi.
        return _lookup_out(existing)

    faculty_id = None
    if body.faculty_id:
        faculty = await db.get(Faculty, body.faculty_id)
        if faculty is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Bunday fakultet topilmadi")
        faculty_id = faculty.id

    record = StudentStaff(
        full_name=body.full_name.strip(),
        type=body.type,
        group_or_position=body.group_or_position.strip(),
        faculty_id=faculty_id,
        pinfl=pinfl or None,
        passport_series=series or None,
        passport_number=number or None,
        biometrics_status="yoq",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    logger.info("self-service registration created", extra={"record_id": str(record.id)})

    return _lookup_out(record)


async def _verify_liveness(frames: list[bytes]) -> None:
    """Uch kadr talab qilingan burilishlarni haqiqatan ko'rsatganini tekshiradi.

    Xato bo'lsa QAYSI bosqich o'tmaganini aytadi. Umumiy «tekshiruvdan
    o'tmadingiz» xabari foydalanuvchini nima qilishni bilmay qoldirardi
    va u boshidan qayta-qayta urinaverardi.
    """
    for index, (frame, expected) in enumerate(zip(frames, LIVENESS_STEPS, strict=True), 1):
        try:
            faces = await detect_faces(frame, priority=PRIORITY_LIVE)
        except NoFaceDetectedError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{index}-kadrni o'qib bo'lmadi",
            ) from exc

        if not faces:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{index}-kadrda ({DIRECTION_LABELS[expected]}) yuz aniqlanmadi",
            )
        if len(faces) > 1:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{index}-kadrda bir nechta yuz bor — kadrda yolg'iz bo'lishingiz kerak",
            )

        face = faces[0]
        if not is_close_enough(face.bbox):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{index}-kadrda yuz juda kichik ({int(face_height(face.bbox))} piksel) — "
                "kameraga yaqinroq keling",
            )

        actual = direction_of(face.landmarks_68)
        if actual != expected:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{index}-kadr talabga mos kelmadi: {DIRECTION_LABELS[expected]}",
            )


@router.post("/pose-check", response_model=PoseCheckOut)
@limiter.limit("240/minute")
async def pose_check(
    request: Request,
    expected: Annotated[str, Form(alias="expected")],
    photo: Annotated[UploadFile, File(description="Kichik o'lchamli joriy kadr")],
) -> PoseCheckOut:
    """Jonli yo'naltirish: hozirgi kadrda yuz qaysi tomonga qaragan.

    Bu endpoint ATAYLAB yengil: mijoz kichraytirilgan kadr yuboradi va
    javobni ekrandagi ko'rsatma uchun ishlatadi. Bazaga hech narsa
    yozilmaydi va hech qanday qaror qabul qilinmaydi.

    Cheklov yuqori (240/daqiqa), chunki bu sekundiga bir-ikki marta
    chaqiriladi — lekin cheksiz emas: har bir chaqiruv yuz aniqlash
    hisobini talab qiladi va uni nazoratsiz qoldirib bo'lmaydi.
    """
    if expected not in LIVENESS_STEPS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Noma'lum bosqich")

    data = await photo.read()
    if len(data) > MAX_POSE_FRAME_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Kadr juda katta")

    try:
        faces = await detect_faces(data, priority=PRIORITY_LIVE)
    except NoFaceDetectedError:
        return PoseCheckOut(face_found=False, faces=0, hint="Kadrni o'qib bo'lmadi")

    if not faces:
        return PoseCheckOut(
            face_found=False, faces=0,
            hint=_pose_hint(0, None, False, expected),
        )

    # Eng katta yuz — ro'yxatdan o'tayotgan odam kameraga eng yaqin
    # turadi. Ortdagi tasodifiy odam qaror qabul qilmaydi, lekin
    # kadrdagi yuzlar soni foydalanuvchiga aytiladi.
    face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    direction = direction_of(face.landmarks_68)
    close = is_close_enough(face.bbox)
    ok = close and len(faces) == 1 and direction == expected

    return PoseCheckOut(
        face_found=True,
        faces=len(faces),
        direction=direction,
        ratio=round(turn_ratio(face.landmarks_68), 3),
        close_enough=close,
        ok=ok,
        hint=_pose_hint(len(faces), direction, close, expected),
    )


@router.post("/{record_id}/submit", response_model=EnrollmentSubmitOut)
@limiter.limit("3/minute")
async def submit_enrollment(
    request: Request,
    record_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    photos: Annotated[
        list[UploadFile],
        File(description="Turli burchaklardan olingan yuz kadrlari — birinchisi to'g'ridan qaragan holat"),
    ],
    pinfl: Annotated[str | None, Form(alias="pinfl")] = None,
    passport_series: Annotated[str | None, Form(alias="passportSeries")] = None,
    passport_number: Annotated[str | None, Form(alias="passportNumber")] = None,
) -> EnrollmentSubmitOut:
    result = await db.execute(
        select(StudentStaff).options(selectinload(StudentStaff.faculty)).where(StudentStaff.id == record_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")

    # Identifikatsiya /lookup dagi bilan AYNAN bir xil tekshiriladi.
    # Bu ataylab: aks holda /lookup ni chetlab o'tib, to'g'ridan-to'g'ri
    # yozuv identifikatorini taxmin qilish orqali begona yozuvga rasm
    # yuklab bo'lardi.
    clean_pinfl = _normalize_pinfl(pinfl)
    series, number = _normalize(passport_series, passport_number)
    if clean_pinfl:
        if not record.pinfl or record.pinfl != clean_pinfl:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "JSHSHIR mos kelmadi")
    elif series and number:
        if record.passport_series != series or record.passport_number != number:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Pasport ma'lumotlari mos kelmadi")
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "JSHSHIR yoki pasport ma'lumotlari yuborilishi kerak",
        )

    if record.biometrics_status == "tasdiqlangan":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Siz allaqachon ro'yxatdan o'tgansiz. O'zgartirish uchun administratorga murojaat qiling.",
        )

    if len(photos) != len(LIVENESS_STEPS):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{len(LIVENESS_STEPS)} ta kadr yuborilishi kerak: "
            + ", ".join(DIRECTION_LABELS[s] for s in LIVENESS_STEPS),
        )

    frames: list[bytes] = []
    for photo in photos:
        data = await photo.read()
        if len(data) > MAX_PHOTO_SIZE_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Har bir kadr 10 MB dan oshmasligi kerak")
        frames.append(data)

    # Tiriklik tekshiruvi SERVERDA qayta bajariladi. Mijoz bosqichlarni
    # o'zi ham tekshiradi, lekin u faqat foydalanuvchini yo'naltirish
    # uchun — bu yerga kelgan kadrlar boshqa yo'l bilan ham yuborilishi
    # mumkin, shuning uchun yakuniy hukm faqat shu yerda chiqariladi.
    await _verify_liveness(frames)

    try:
        embedding = await extract_enrollment_embedding(frames)
    except (NoFaceDetectedError, InconsistentFacesError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    # Blocking boto3 call kept off the event loop, and the photo this
    # replaces (a re-enrollment) removed afterwards so it doesn't sit in
    # object storage unreferenced — see app/storage.py's
    # delete_files_quietly for why both matter.
    previous_key = record.biometric_photo_key
    _file_id, key = await asyncio.to_thread(upload_file, frames[0], "face.jpg", "image/jpeg", "biometrics")
    record.biometric_photo_key = key
    record.biometric_embedding = json.dumps(embedding)
    record.biometrics_status = "tasdiqlangan"

    await db.commit()
    if previous_key and previous_key != key:
        await delete_files_quietly([previous_key])
    logger.info("self-service biometric enrollment completed", extra={"record_id": record_id})
    invalidate_candidate_matrix_cache()
    return EnrollmentSubmitOut(full_name=record.full_name, biometrics_status=record.biometrics_status)
