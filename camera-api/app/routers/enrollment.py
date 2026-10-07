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

Ro'yxatdan o'tish hujjatdagi JSHSHIR yoki pasport ma'lumotlari bilan
amalga oshadi. Yakuniy yuborishda ular yana solishtiriladi, tiriklik va
boshqa odam yuziga o'xshashlik tekshiriladi.

ROZILIK. /submit biometrik ma'lumotni qayta ishlashga rozilik belgisini
(`consent=true`) kutadi — settings.consent_required_for_enrollment
yoqilgan bo'lsa, usiz kadrlar umuman o'qilmaydi. Rozilik vaqti va matn
versiyasi yozuvga saqlanadi; matnning o'zi — GET /api/public/consent-text
(app/routers/privacy.py).

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
import uuid
from datetime import datetime, timezone
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit import log_action
from app.config import settings
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.models import Faculty, OrgUnit, StudentGroup, StudentStaff
from app.services.staff_export import split_course
from app.rate_limit import limiter
from app.schemas.enrollment import (
    EnrollmentFacultyOut,
    PoseCheckOut,
    EnrollmentLookupIn,
    EnrollmentLookupOut,
    EnrollmentRegisterIn,
    EnrollmentSubmitOut,
)
from app.services.face_matching import announce_roster_change
from app.services.hemis_reconcile import NOT_IN_HEMIS, hemis_groups, match_hemis_group
from app.services.integrations.hemis import hemis_configured
from app.services.inference_gate import PRIORITY_LIVE
from app.services.privacy import record_consent
from app.services.self_enrollment import decide_status
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



def _as_uuid(value: str | None) -> uuid.UUID | None:
    """Noto'g'ri shakldagi identifikator — None.

    Bu endpointlar OCHIQ: xom satrni to'g'ridan-to'g'ri so'rovga
    qo'yganda Postgres "invalid input syntax for type uuid" bilan
    yiqilardi va mijoz 500 olardi (sessiya esa buzilgan holda qolardi).
    Noma'lum identifikator "topilmadi" bo'lishi kerak, xato emas."""
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


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
    """Pasport bo'yicha eng eski yozuv.

    JSHSHIR dan farqli o'laroq, pasport ustunlarida unikal indeks YO'Q
    (ommaviy importda takror pasport uchrashi mumkin). Ilgari bu yerda
    scalar_one_or_none() turardi — ikkita mos yozuv bo'lsa u istisno
    ko'tarib, o'sha odam uchun ro'yxatdan o'tishni butunlay buzardi.
    Eng eskisini tanlash — barqaror: har chaqiruvda bir xil yozuv
    qaytadi, ya'ni yuz har safar boshqa dublikatga yopishib qolmaydi."""
    result = await db.execute(
        select(StudentStaff)
        .where(StudentStaff.passport_series == series)
        .where(StudentStaff.passport_number == number)
        .order_by(StudentStaff.created_at, StudentStaff.id)
        .limit(1)
    )
    return result.scalars().first()


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


def mask_name(full_name: str) -> str:
    """Ochiq sahifa uchun ism: odam o'zini taniydi, begona esa JSHSHIR
    orqali to'liq ism-sharifni bilib ololmaydi. "Aliyev Anvar Valijon o'g'li"
    -> "A*** Anvar V*** o***" (ikkinchi so'z — ism — ochiq)."""
    words = full_name.split()
    return " ".join(w if i == 1 else f"{w[0]}***" for i, w in enumerate(words))


def _public_unit(record: StudentStaff) -> str:
    """Talabaning faqat kursi (guruhi emas), xodimning lavozimi yo'q."""
    if record.type == "talaba":
        course, _group = split_course(record.group_or_position)
        return f"{course}-kurs" if course else ""
    return ""


def _lookup_out(record: StudentStaff) -> EnrollmentLookupOut:
    return EnrollmentLookupOut(
        record_id=str(record.id),
        full_name=mask_name(record.full_name),
        type_label="Talaba" if record.type == "talaba" else "Xodim",
        group_or_position=_public_unit(record),
        already_enrolled=record.biometrics_status == "tasdiqlangan",
        awaiting_approval=record.awaiting_approval,
    )


@router.post("/lookup", response_model=EnrollmentLookupOut)
# Institut Wi-Fi: yuzlab talaba BITTA tashqi IP bilan chiqadi — QR bilan
# ommaviy topshirishda 3/minute talabalarni bloklardi (2026-09-19).
@limiter.limit("60/minute")
async def lookup_person(
    request: Request,
    body: EnrollmentLookupIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EnrollmentLookupOut:
    """Shaxsni JSHSHIR yoki pasport ma'lumotlari orqali topadi.

    Ochiq ro'yxatdan o'tishda guruh kodi ishlatilmaydi: hujjatdagi
    identifikatorning o'zi yetarli. So'rov soni cheklangan, yakuniy
    biometrika topshirishda ham shu identifikator qayta tekshiriladi.
    """
    record = await _find_person(db, body.pinfl, body.passport_series, body.passport_number)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ma'lumot topilmadi. JSHSHIR yoki pasport ma'lumotini tekshiring.")
    return _lookup_out(record)


@router.get("/faculties", response_model=list[EnrollmentFacultyOut])
async def list_faculties(db: Annotated[AsyncSession, Depends(get_db)]) -> list[EnrollmentFacultyOut]:
    """Ro'yxatdan o'tish formasidagi fakultet ro'yxati.

    Ochiq, chunki forma ham ochiq — hisobi yo'q odam aynan shu yerda
    ro'yxatdan o'tadi. Faqat id va nom qaytariladi: talabalar soni kabi
    ichki ko'rsatkichlar bu yerga kerak emas."""
    result = await db.execute(select(Faculty).order_by(Faculty.name))
    return [EnrollmentFacultyOut(id=str(f.id), name=f.name) for f in result.scalars().all()]


@router.get("/groups")
async def list_groups(db: Annotated[AsyncSession, Depends(get_db)]) -> list[dict]:
    """Guruhlar (HEMIS) — ro'yxatdan o'tishda guruhni tanlash uchun.
    Ochiq: faqat nom, kurs va fakultet id si."""
    rows = await db.execute(select(StudentGroup.name, StudentGroup.course, StudentGroup.faculty_id).order_by(StudentGroup.name))
    return [{"name": name, "course": course, "facultyId": str(fid) if fid else None} for name, course, fid in rows.all()]


@router.get("/units")
async def list_units(db: Annotated[AsyncSession, Depends(get_db)]) -> list[dict]:
    """Institut bo'linmalari (HEMIS) — xodim o'z kafedra/bo'limini tanlaydi."""
    rows = await db.execute(
        select(OrgUnit.id, OrgUnit.name, OrgUnit.kind).where(OrgUnit.active.is_(True)).order_by(OrgUnit.name)
    )
    return [{"id": str(uid), "name": name, "kind": kind} for uid, name, kind in rows.all()]


@router.post("/register", response_model=EnrollmentLookupOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
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
    shaxs ma'lumoti, hali yuz emas. Yuz keyingi qadamda qo'shiladi, lekin
    'tasdiqlangan' EMAS, 'kutilmoqda' bo'ladi (self_registered): bu odam
    institut ro'yxatida yo'q, ya'ni u kimligini hech kim tasdiqlamagan.
    Aks holda istalgan begona o'zini shu yerda ro'yxatdan o'tkazib,
    "begona shaxs" tekshiruvidan chiqib ketardi. Administrator
    "Talabalar va Xodimlar" sahifasida tasdiqlaydi yoki rad etadi.

    Cheklov (3/minute) va pasport takrorlanmasligi tekshiruvi ataylab:
    endpoint ochiq, ya'ni uni bazani to'ldirish uchun ishlatib bo'lmasligi
    kerak.

    Pasport yoki JSHSHIR tekshiruvi bu oqimning yagona identifikatsiya
    vositasi; guruh kodi talab qilinmaydi."""

    pinfl = _normalize_pinfl(body.pinfl)
    series, number = _normalize(body.passport_series, body.passport_number)

    existing = await _find_person(db, body.pinfl, body.passport_series, body.passport_number)
    if existing is not None:
        # Yozuv allaqachon bor — yangisini yaratmaymiz, borini qaytaramiz.
        # Aks holda bitta odam uchun ikkita yozuv paydo bo'lardi va
        # davomat ikkiga bo'linib ketardi.
        #
        return _lookup_out(existing)

    faculty_id = None
    if body.faculty_id:
        faculty = await db.get(Faculty, _as_uuid(body.faculty_id)) if _as_uuid(body.faculty_id) else None
        if faculty is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Bunday fakultet topilmadi")
        faculty_id = faculty.id

    group_or_position = body.group_or_position.strip()
    reported_group = None
    org_unit_id = None
    position = None
    if body.type == "talaba":
        # HEMIS guruhi bilan mos kelsa — "N-kurs, GURUH" (import bilan bir xil
        # ko'rinish): kurs filtri va guruh sahifasi uni shunda topadi.
        group = (
            await db.execute(select(StudentGroup).where(func.lower(StudentGroup.name) == group_or_position.lower()))
        ).scalars().first()
        if group is not None:
            group_or_position = f"{group.course}-kurs, {group.name}"
            faculty_id = faculty_id or group.faculty_id
        elif hemis_configured():
            # HEMIS ulangan: qo'lda yozilgan, HEMIS'da yo'q guruh ("20.26
            # gurux") Nazoratda bir kishilik soxta guruh bo'lmasin — bitta
            # "HEMIS'da topilmadi" ro'yxati, yozgani reported_group'da.
            known = match_hemis_group(group_or_position, await hemis_groups(db))
            if known is not None:
                group_or_position = known
            else:
                reported_group = group_or_position[:300]
                group_or_position = NOT_IN_HEMIS
    else:
        position = group_or_position
        if body.org_unit_id:
            unit = await db.get(OrgUnit, _as_uuid(body.org_unit_id)) if _as_uuid(body.org_unit_id) else None
            if unit is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Bunday bo'linma topilmadi")
            org_unit_id = unit.id

    record = StudentStaff(
        full_name=body.full_name.strip(),
        type=body.type,
        group_or_position=group_or_position,
        reported_group=reported_group,
        org_unit_id=org_unit_id,
        position=position,
        faculty_id=faculty_id,
        pinfl=pinfl or None,
        passport_series=series or None,
        passport_number=number or None,
        biometrics_status="yoq",
        self_registered=True,
    )
    db.add(record)
    try:
        await db.commit()
    except IntegrityError:
        # JSHSHIR ustuni unikal: bir vaqtda kelgan ikkita so'rov ikkalasi
        # ham "yozuv yo'q" deb topib, ikkalasi ham qo'shishga urinadi.
        # Yutqazgani 500 emas, mavjud yozuvni olishi kerak.
        await db.rollback()
        existing = await _find_person(db, body.pinfl, body.passport_series, body.passport_number)
        if existing is None:
            raise
        return _lookup_out(existing)
    await db.refresh(record)
    logger.info("self-service registration created", extra={"record_id": str(record.id)})

    return _lookup_out(record)


#: Ro'yxatga olish kadrining eng uzun tomoni (piksel).
ENROLL_FRAME_MAX_SIDE = 640


def _downscale(frame: bytes) -> bytes:
    import cv2
    import numpy as np

    try:
        img = cv2.imdecode(np.frombuffer(frame, np.uint8), cv2.IMREAD_COLOR)
    except cv2.error:
        img = None
    if img is None:
        return frame  # o'qilmaydigan kadr — tiriklik tekshiruvi aniq xabar beradi
    h, w = img.shape[:2]
    side = max(h, w)
    if side <= ENROLL_FRAME_MAX_SIDE:
        return frame
    scale = ENROLL_FRAME_MAX_SIDE / side
    img = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return buf.tobytes() if ok else frame


def _log_frame_shape(index: int, frame: bytes) -> None:
    """Yuz topilmagan kadr haqida faqat raqamlar (rasm saqlanmaydi): o'lcham,
    fayl hajmi, o'rtacha yorqinlik — qora/bo'sh kadrni ajratish uchun."""
    try:
        import cv2
        import numpy as np

        img = cv2.imdecode(np.frombuffer(frame, np.uint8), cv2.IMREAD_COLOR)
        shape = None if img is None else img.shape[:2]
        mean = None if img is None else round(float(img.mean()), 1)
    except Exception:
        shape, mean = None, None
    logger.warning(
        "enrollment frame without face",
        extra={"index": index, "bytes": len(frame), "shape": str(shape), "mean": mean, "head": frame[:4].hex()},
    )


async def _verify_liveness(frames: list[bytes]) -> None:
    """Uch kadr talab qilingan burilishlarni haqiqatan ko'rsatganini tekshiradi.

    Xato bo'lsa QAYSI bosqich o'tmaganini aytadi. Umumiy «tekshiruvdan
    o'tmadingiz» xabari foydalanuvchini nima qilishni bilmay qoldirardi
    va u boshidan qayta-qayta urinaverardi.
    """
    for index, (frame, expected) in enumerate(zip(frames, LIVENESS_STEPS, strict=True), 1):
        try:
            # Ro'yxatga olishda har yuz tahlil qilinadi — burchak landmarklardan o'lchanadi.
            faces = await detect_faces(frame, priority=PRIORITY_LIVE, min_face_px=0, enrollment=True)
        except NoFaceDetectedError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{index}-kadrni o'qib bo'lmadi",
            ) from exc

        if not faces:
            _log_frame_shape(index, frame)
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
        if actual is None and expected in ("left", "right"):
            # Oraliq holat, lekin TO'G'RI tomonga burilgan: yo'naltirish bu
            # burilishni allaqachon tasdiqlagan, to'liq kadr esa bir lahza
            # keyin olinadi — odam boshini qaytara boshlagan bo'ladi.
            # Qarama-qarshi tomon yoki to'g'ri qarash baribir rad etiladi.
            ratio = turn_ratio(face.landmarks_68)
            if (ratio > 0) == (expected == "left"):
                actual = expected
        if actual != expected:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{index}-kadr talabga mos kelmadi: {DIRECTION_LABELS[expected]}",
            )


@router.post("/pose-check", response_model=PoseCheckOut)
@limiter.limit("600/minute")  # institut Wi-Fi: ko'p telefon bitta IP dan (NAT)
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
        # Faqat burchak kerak — vektor (ArcFace) hisoblanmaydi.
        faces = await detect_faces(
            data, priority=PRIORITY_LIVE, min_face_px=0, enrollment=True, embed=False,
            det_max_side=settings.enrollment_pose_det_max_side,
        )
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
@limiter.limit("90/minute")
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
    consent: Annotated[bool, Form(alias="consent")] = False,
) -> EnrollmentSubmitOut:
    # Shaxs ma'lumoti umuman yuborilmagan bo'lsa — bu so'rovning o'z
    # shakli haqidagi xato va u hech narsa oshkor qilmaydi.
    if not _normalize_pinfl(pinfl) and not all(_normalize(passport_series, passport_number)):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "JSHSHIR yoki pasport ma'lumotlari yuborilishi kerak",
        )

    record_uuid = _as_uuid(record_id)
    record = None
    if record_uuid is not None:
        result = await db.execute(
            select(StudentStaff).options(selectinload(StudentStaff.faculty)).where(StudentStaff.id == record_uuid)
        )
        record = result.scalar_one_or_none()

    if record is None:
        # Yo'q yozuv va noto'g'ri JSHSHIR bir xil javob beradi — identifikatorlarni
        # birma-bir sinab kim bor-yo'qligini aniqlab bo'lmasin.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "JSHSHIR mos kelmadi")

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

    if not record.active:
        # Faolsizlantirilgan (bitirgan, ishdan ketgan) odam kameralar
        # tomonidan tanilmaydi, yuzi esa saqlash muddatidan keyin
        # o'chiriladi — unga yangi biometrika yig'ishning maqsadi yo'q.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Yozuvingiz faol emas. Ma'lumot uchun administratorga murojaat qiling.",
        )

    # Rozilik yuz kadrlari O'QILISHIDAN OLDIN tekshiriladi: biometrik
    # ma'lumotni qayta ishlash (yuz aniqlash ham shunga kiradi) rozilikdan
    # keyingina boshlanishi mumkin ("Shaxsga doir ma'lumotlar
    # to'g'risida"gi Qonun). Matn — GET /api/public/consent-text.
    if settings.consent_required_for_enrollment and not consent:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Davom etish uchun biometrik ma'lumotlarni qayta ishlashga rozilik berishingiz kerak",
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
    # Telefon selfisi (720x1280, yuz kadrning katta qismi) to'liq o'lchamda
    # detektordan o'tmay qolardi — "1-kadrda yuz aniqlanmadi" hammada.
    # Yo'naltirish (pose-check) kichik kadrda muvaffaqiyatli ishlaydi,
    # shuning uchun saqlash kadrlari ham o'sha o'lchamga keltiriladi.
    frames = await asyncio.to_thread(lambda: [_downscale(frame) for frame in frames])
    await _verify_liveness(frames)

    try:
        embedding = await extract_enrollment_embedding(frames)
    except (NoFaceDetectedError, InconsistentFacesError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    # Blocking boto3 call kept off the event loop, and the photo this
    # replaces (a re-enrollment) removed afterwards so it doesn't sit in
    # object storage unreferenced — see app/storage.py's
    # delete_files_quietly for why both matter.
    #
    # ESKI RASM YANGISI SAQLANGUNCHA O'CHIRILMAYDI. Bu tartib majburiy:
    # "kutilmoqda" holatidagi yozuv ustiga qayta topshirilganda eski rasm
    # oldin o'chirilsa va yangisini saqlash (yoki commit) yiqilsa, odam
    # umuman rasmsiz qolardi — ya'ni bitta muvaffaqiyatsiz so'rov
    # birovning yuzini yo'q qilib yuborardi.
    # Uchala tomon ham saqlanadi (LIVENESS_STEPS: to'g'ri, chap, o'ng) — keyin
    # operator tekshirishi va qayta hisoblash uchun.
    previous_keys = [record.biometric_photo_key, record.biometric_photo_left_key, record.biometric_photo_right_key]
    _file_id, key = await asyncio.to_thread(upload_file, frames[0], "face.jpg", "image/jpeg", "biometrics")
    side_keys: list[str | None] = [None, None]
    for index, name in ((1, "face-left.jpg"), (2, "face-right.jpg")):
        if index < len(frames):
            _fid, side_keys[index - 1] = await asyncio.to_thread(upload_file, frames[index], name, "image/jpeg", "biometrics")
    record.biometric_photo_key = key
    record.biometric_photo_left_key, record.biometric_photo_right_key = side_keys
    record.biometric_embedding = json.dumps(embedding)
    if consent:
        record_consent(record, "royxatdan_otish")
    # Avtomatik tasdiqlash HAMMA uchun bir xil tekshiruvdan o'tadi (2026-09-20).
    # Sabab: JSHSHIR sir emas (hujjatda va ro'yxatlarda bor), tiriklik
    # tekshiruvi esa "tirik odam"ni isbotlaydi, "AYNAN SHU odam"ni emas.
    # Shusiz begona odam birovning JSHSHIRi bilan o'z yuzini uning nomiga
    # bog'lab, davomat va turniketda o'sha odam bo'lib ko'rinardi. Halol
    # topshirgan odamning yuzi hech kimga o'xshamaydi, shuning uchun
    # tekshiruvga faqat o'zgalashtirish holati tushadi.
    new_status, reason = await decide_status(db, record, embedding)
    record.biometrics_status = new_status
    record.biometrics_review_reason = reason[:300] if reason else None
    record.biometrics_confirmed_at = datetime.now(timezone.utc) if new_status == "tasdiqlangan" else None
    if reason:
        logger.warning(
            "enrollment held for review",
            extra={"record_id": record_id, "self_registered": record.self_registered, "reason": reason},
        )

    try:
        await db.commit()
    except Exception:
        # Commit yiqildi — bazada hali ESKI kalit turibdi, ya'ni eski
        # rasmga hech narsa tegmaydi. Yangi yuklangan fayl esa
        # ortiqcha bo'lib qoladi va o'sha o'chiriladi.
        await db.rollback()
        await delete_files_quietly([k for k in (key, *side_keys) if k])
        raise
    new_keys = {key, *side_keys}
    stale = [k for k in previous_keys if k and k not in new_keys]
    if stale:
        await delete_files_quietly(stale)
    logger.info(
        "self-service biometric enrollment completed",
        extra={"record_id": record_id, "biometrics_status": record.biometrics_status},
    )
    if record.biometrics_status == "tasdiqlangan":
        await announce_roster_change()
    return EnrollmentSubmitOut(
        full_name=mask_name(record.full_name),
        biometrics_status=record.biometrics_status,
        awaiting_approval=record.awaiting_approval,
    )
