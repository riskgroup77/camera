import asyncio
import json
import logging
import uuid
from functools import partial
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.models import Faculty, OrgUnit, StudentStaff
from app.pagination import Page, PageParams, build_page, paginate
from app.schemas.student_staff import (
    BiometricsConfirmationOut,
    BiometricsCourseRowOut,
    BiometricsCoverageOut,
    BiometricsFacultyRowOut,
    StudentStaffCreateIn,
    StudentStaffDetailOut,
    StudentStaffExportIn,
    StudentStaffOut,
    StudentStaffSearchIn,
    StudentStaffUpdateIn,
    PeopleOverviewOut,
)
from app.schemas.base import CamelModel
from app.schemas.student_staff_import import StudentStaffImportResultOut
from app.services import person_dedupe
from app.services.privacy import clear_biometrics
from app.services.face_matching import announce_roster_change
from app.services.name_matching import name_key, name_tokens, names_match
from app.services.notifications.sms import normalize_phone
from app.services.face_recognition import NoFaceDetectedError, extract_embedding
from app.services.staff_export import (
    STATUS_LABELS,
    XLSX_MIME,
    Bucket,
    CoverageData,
    PersonRow,
    build_people_workbook,
    build_stats_workbook,
    course_label,
    person_sort_key,
    split_course,
)
from app.services.student_import import import_students_staff_csv
from app.storage import delete_files_quietly, object_last_modified, presigned_url, upload_file
from app.timezone import local_now, to_local, uz_datetime_parts
from app.utils import compute_initials

router = APIRouter(prefix="/api/students-staff", tags=["students-staff"])

logger = logging.getLogger("app.students_staff")

MAX_PHOTO_SIZE_BYTES = 10 * 1024 * 1024

# Audit jurnalida "kim o'chirildi" savoliga javob beradigan yorliq.
PERSON_TYPE_LABELS = {"talaba": "talaba", "xodim": "xodim"}


async def _resolve_faculty(db: AsyncSession, faculty_name: str) -> Faculty:
    result = await db.execute(select(Faculty).where(Faculty.name == faculty_name))
    faculty = result.scalar_one_or_none()
    if faculty is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"'{faculty_name}' nomli fakultet topilmadi")
    return faculty


def _clean_parent_phone(value: str | None) -> str | None:
    """Ota-ona telefoni: bo'sh — o'chiriladi; aks holda +998XXXXXXXXX."""
    if value is None or not value.strip():
        return None
    phone = normalize_phone(value)
    if phone is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Ota-ona telefon raqami noto'g'ri (masalan: +998 90 123 45 67)"
        )
    return phone


def _clean_card(value: str | None) -> str | None:
    """Karta raqami — turniket qanday o'qisa shunday (bo'shliqlarsiz)."""
    if value is None:
        return None
    card = "".join(value.split())
    return card or None


async def _ensure_card_free(db: AsyncSession, card: str | None, exclude_id: uuid.UUID | None = None) -> None:
    if card is None:
        return
    stmt = select(StudentStaff).where(StudentStaff.card_number == card)
    if exclude_id is not None:
        stmt = stmt.where(StudentStaff.id != exclude_id)
    other = (await db.execute(stmt)).scalars().first()
    if other is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Bu karta raqami boshqa yozuvga biriktirilgan: {other.full_name} ({other.group_or_position})",
        )


CARD_CONFLICT_MESSAGE = "Bu karta raqami boshqa yozuvga biriktirilgan"


def _confirmed_label(record: StudentStaff) -> str | None:
    """"14.09.2026 13:57" — Toshkent vaqti. Faqat yozilgan vaqt: eski
    tasdiqlashlar uchun rasm vaqtidan tiklash har qatorga ombor so'rovi
    bo'lardi, u "Aniqlash" oynasida bittalab qilinadi."""
    if record.biometrics_confirmed_at is None:
        return None
    return to_local(record.biometrics_confirmed_at).strftime("%d.%m.%Y %H:%M")


def _to_out(record: StudentStaff, faculty_name: str, org_unit: str | None = None) -> StudentStaffOut:
    course, group = split_course(record.group_or_position) if record.type == "talaba" else (None, None)
    return StudentStaffOut(
        org_unit=org_unit,
        position=record.position if record.type == "xodim" else None,
        photo_angles=sum(
            1 for key in (record.biometric_photo_key, record.biometric_photo_left_key, record.biometric_photo_right_key)
            if key
        ),
        id=str(record.id),
        full_name=record.full_name,
        type=record.type,
        faculty=faculty_name,
        group_or_position=record.group_or_position,
        biometrics_status=record.biometrics_status,
        initials=compute_initials(record.full_name),
        biometric_photo_url=presigned_url(record.biometric_photo_key) if record.biometric_photo_key else None,
        course=course,
        group=group or None,
        confirmed_label=_confirmed_label(record),
        self_registered=record.self_registered,
        awaiting_approval=record.awaiting_approval,
        review_reason=record.biometrics_review_reason if record.awaiting_approval else None,
        # HEMIS surati — administrator yuborilgan yuz bilan ko'z bilan solishtiradi.
        hemis_photo_url=record.hemis_photo_url if record.awaiting_approval else None,
        # Tasdiqlash oynasi uchun: chap va o'ng tomon (faqat kutayotganlarda).
        biometric_photo_left_url=(
            presigned_url(record.biometric_photo_left_key)
            if record.awaiting_approval and record.biometric_photo_left_key else None
        ),
        biometric_photo_right_url=(
            presigned_url(record.biometric_photo_right_key)
            if record.awaiting_approval and record.biometric_photo_right_key else None
        ),
    )


# "Fakultetsiz" — bu qiymat emas, qiymatning YO'QLIGI. Rektorat, texnik
# va xo'jalik bo'limlari xodimlarining fakulteti bo'lmaydi, lekin ular
# ham ro'yxatga kiradi va qamrov hisobiga qo'shiladi. Filtrda ularni
# tanlash uchun alohida kalit kerak, chunki bo'sh satr "filtr yo'q"
# degani.
NO_FACULTY_KEY = "__none__"
NO_FACULTY_LABEL = "Fakultetsiz"

# Import qilingan ismlarda tutuq belgisi oddiy "'" bilan saqlanadi, odam
# esa klaviaturaga qarab o‘, o`, oʻ yozadi.
_APOSTROPHES = "‘’`ʻʼ´"


def _search_words(search: str | None) -> list[str]:
    text = search or ""
    for ch in _APOSTROPHES:
        text = text.replace(ch, "'")
    return text.split()


# "Ro'yxatdan o'tmaganlar" — yuzi tasdiqlanmagan HAR KIM: "yo'q" ham,
# "kutilmoqda" ham. Faqat "yoq" bo'yicha filtrlansa, kutilmoqda
# holatidagilar ikkala ro'yxatdan ham tushib qolardi.
UNCONFIRMED_FILTER = "tasdiqlanmagan"
# O'zini o'zi ro'yxatdan o'tkazib, yuzini yuborgan va administrator
# qarorini kutayotganlar (enrollment.register_self).
AWAITING_APPROVAL_FILTER = "tasdiq_kutmoqda"

BIOMETRICS_FILTER_LABELS = {
    "tasdiqlangan": "Ro'yxatdan o'tganlar (yuzi tasdiqlangan)",
    UNCONFIRMED_FILTER: "Ro'yxatdan o'tmaganlar (yuzi tasdiqlanmagan)",
    AWAITING_APPROVAL_FILTER: "Yuzi tasdiq kutmoqda",
}

# Ro'yxatdagi odam ham shu yerga tushadi: yuzi boshqasiga o'xshab qolsa
# (self_enrollment.decide_status) — aks holda uni tasdiqlab ham, rad etib
# ham bo'lmasdi.
AWAITING_APPROVAL = and_(
    StudentStaff.biometrics_status == "kutilmoqda",
    StudentStaff.biometric_embedding.is_not(None),
)


def _filtered_query(
    type: str | None,
    faculty: str | None,
    search: str | None,
    biometrics: str | None,
    course: int | None = None,
    sort: str = "name",
):
    """Ro'yxat va eksport AYNAN bir xil filtrdan foydalanadi.

    Alohida yozilsa, ikkalasi vaqt o'tib bir-biridan farq qila boshlardi
    va yuklab olingan fayl ekranda ko'rinayotgan ro'yxatga mos
    kelmasdi — bu hisobot uchun jiddiy nuqson."""
    # Reestr — faol odamlar (bitirgan/ishdan ketganlar Maxfiylik sahifasida "Faol emas").
    stmt = select(StudentStaff).options(selectinload(StudentStaff.faculty)).where(StudentStaff.active.is_(True))
    if type:
        stmt = stmt.where(StudentStaff.type == type)
    if faculty == NO_FACULTY_KEY:
        stmt = stmt.where(StudentStaff.faculty_id.is_(None))
    elif faculty:
        stmt = stmt.join(Faculty).where(Faculty.name == faculty)
    # JSHSHIR bo'yicha ham qidiriladi: kadrlar bo'limi odamni ko'pincha
    # aynan raqami bilan izlaydi. Har bir so'z alohida mos kelishi kerak,
    # tartibi esa muhim emas: bazada "Familiya Ism", odam esa ko'pincha
    # "Ism Familiya" deb yozadi.
    for word in _search_words(search):
        term = f"%{word}%"
        stmt = stmt.where(
            or_(StudentStaff.full_name.ilike(term), StudentStaff.pinfl.ilike(term))
        )
    if biometrics == UNCONFIRMED_FILTER:
        stmt = stmt.where(StudentStaff.biometrics_status != "tasdiqlangan")
    elif biometrics == AWAITING_APPROVAL_FILTER:
        stmt = stmt.where(AWAITING_APPROVAL)
    elif biometrics:
        stmt = stmt.where(StudentStaff.biometrics_status == biometrics)
    if course:
        # Kurs group_or_position boshida yoziladi ("2-kurs, DI-1625") —
        # qarang staff_export.split_course. "1-kurs%" "11-kurs" ga mos kelmaydi.
        stmt = stmt.where(StudentStaff.type == "talaba").where(
            StudentStaff.group_or_position.ilike(f"{course}-kurs%")
        )
    if sort == "confirmed":
        stmt = stmt.order_by(StudentStaff.biometrics_confirmed_at.desc().nulls_last(), StudentStaff.full_name)
    elif sort == "faculty":
        # Fakultet filtri bo'lsa Faculty allaqachon ulangan (join); aks holda
        # fakultetsizlar ham ro'yxatda qolishi uchun outer join.
        if not faculty or faculty == NO_FACULTY_KEY:
            stmt = stmt.outerjoin(Faculty, StudentStaff.faculty_id == Faculty.id)
        stmt = stmt.order_by(Faculty.name.asc().nulls_last(), StudentStaff.full_name)
    else:
        stmt = stmt.order_by(StudentStaff.full_name)
    return stmt


@router.get("", response_model=Page[StudentStaffOut])
async def list_students_staff(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
    page_params: Annotated[PageParams, Depends()],
    type: Annotated[str | None, Query()] = None,
    faculty: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    biometrics: Annotated[str | None, Query(alias="biometricsStatus")] = None,
    course: Annotated[int | None, Query(ge=1, le=10)] = None,
) -> Page[StudentStaffOut]:
    stmt = _filtered_query(type, faculty, search, biometrics, course)

    records, total = await paginate(db, stmt, page_params)
    return build_page(await _outs(db, records), total, page_params)


async def _outs(db: AsyncSession, records: list[StudentStaff]) -> list[StudentStaffOut]:
    """Ro'yxat qatorlari + xodimning HEMIS bo'linmasi nomi (bitta so'rovda)."""
    unit_ids = {r.org_unit_id for r in records if r.org_unit_id}
    names: dict = {}
    if unit_ids:
        names = dict((await db.execute(select(OrgUnit.id, OrgUnit.name).where(OrgUnit.id.in_(unit_ids)))).all())
    return [_to_out(r, r.faculty.name if r.faculty else "", names.get(r.org_unit_id)) for r in records]


@router.post("/search", response_model=Page[StudentStaffOut])
async def search_students_staff(
    body: StudentStaffSearchIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
) -> Page[StudentStaffOut]:
    """GET ro'yxat bilan bir xil, lekin filtr (JSHSHIR bo'lishi mumkin bo'lgan
    qidiruv matni bilan) so'rov tanasida — URL/access logga tushmaydi."""
    page_params = PageParams(page=body.page, page_size=body.page_size)
    stmt = _filtered_query(body.type, body.faculty, body.search, body.biometrics_status, body.course, body.sort)
    records, total = await paginate(db, stmt, page_params)
    return build_page(await _outs(db, records), total, page_params)


@router.get("/biometrics-coverage", response_model=BiometricsCoverageOut)
async def biometrics_coverage(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
    type: Annotated[str | None, Query()] = None,
) -> BiometricsCoverageOut:
    return await _coverage(db, type)


@router.get("/overview", response_model=PeopleOverviewOut)
async def people_overview(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
) -> PeopleOverviewOut:
    """Ikkala tur qamrovi bitta javobda — sahifa tepasi va tablar soni uchun."""
    return PeopleOverviewOut(xodim=await _coverage(db, "xodim"), talaba=await _coverage(db, "talaba"))


async def _coverage(db: AsyncSession, type: str | None) -> BiometricsCoverageOut:
    """Yuzni kim tasdiqlagani va kim tasdiqlamagani — fakultetlar kesimida.

    Bu savol tizim ishga tushgandan keyin eng ko'p beriladigan savol:
    ro'yxatdagi 688 xodimdan nechtasi haqiqatan yuzini yuklagan. Uni
    ro'yxatni varaqlab sanab bo'lmaydi, shuning uchun alohida
    hisoblanadi."""
    stmt = select(
        Faculty.name,
        StudentStaff.biometrics_status,
        func.count(StudentStaff.id),
    ).select_from(StudentStaff).outerjoin(Faculty, StudentStaff.faculty_id == Faculty.id)
    stmt = stmt.where(StudentStaff.active.is_(True))
    if type:
        stmt = stmt.where(StudentStaff.type == type)
    stmt = stmt.group_by(Faculty.name, StudentStaff.biometrics_status)

    buckets: dict[str, dict[str, int]] = {}
    for faculty_name, bio_status, count in (await db.execute(stmt)).all():
        key = faculty_name or NO_FACULTY_LABEL
        buckets.setdefault(key, {}).update({bio_status: count})

    rows: list[BiometricsFacultyRowOut] = []
    totals = {"tasdiqlangan": 0, "kutilmoqda": 0, "yoq": 0}
    for name in sorted(buckets, key=lambda n: (n == NO_FACULTY_LABEL, n)):
        counts = buckets[name]
        confirmed = counts.get("tasdiqlangan", 0)
        pending = counts.get("kutilmoqda", 0)
        missing = counts.get("yoq", 0)
        total = confirmed + pending + missing
        for k, v in (("tasdiqlangan", confirmed), ("kutilmoqda", pending), ("yoq", missing)):
            totals[k] += v
        rows.append(
            BiometricsFacultyRowOut(
                faculty=name,
                total=total,
                confirmed=confirmed,
                pending=pending,
                missing=missing,
                percent=round(confirmed * 100 / total, 1) if total else None,
            )
        )

    # Faqat faol odamlar — ro'yxat (va "Ko'rib chiqish" tugmasi) bilan bir xil to'plam.
    awaiting_stmt = (
        select(func.count()).select_from(StudentStaff).where(AWAITING_APPROVAL).where(StudentStaff.active.is_(True))
    )
    if type:
        awaiting_stmt = awaiting_stmt.where(StudentStaff.type == type)
    grand = sum(totals.values())
    return BiometricsCoverageOut(
        total=grand,
        confirmed=totals["tasdiqlangan"],
        pending=totals["kutilmoqda"],
        missing=totals["yoq"],
        percent=round(totals["tasdiqlangan"] * 100 / grand, 1) if grand else None,
        by_faculty=rows,
        by_course=await _course_rows(db) if type == "talaba" else [],
        awaiting_approval=await db.scalar(awaiting_stmt) or 0,
    )


async def _course_rows(db: AsyncSession) -> list[BiometricsCourseRowOut]:
    """Talabalar kurslar kesimida. Guruhlar soni bir necha yuz — ularni
    Python'da kursga yig'ish SQL'da matnni kesishdan soddaroq va
    staff_export.split_course bilan AYNAN bir xil qoidada ishlaydi."""
    stmt = (
        select(StudentStaff.group_or_position, StudentStaff.biometrics_status, func.count(StudentStaff.id))
        .where(StudentStaff.type == "talaba", StudentStaff.active.is_(True))
        .group_by(StudentStaff.group_or_position, StudentStaff.biometrics_status)
    )
    buckets: dict[int | None, Bucket] = {}
    for unit, bio_status, count in (await db.execute(stmt)).all():
        course, _group = split_course(unit)
        buckets.setdefault(course, Bucket()).add(bio_status, count)

    return [
        BiometricsCourseRowOut(
            course=course_label(course),
            course_number=course,
            total=bucket.total,
            confirmed=bucket.confirmed,
            pending=bucket.pending,
            missing=bucket.missing,
            percent=round(bucket.confirmed * 100 / bucket.total, 1) if bucket.total else None,
        )
        for course, bucket in sorted(buckets.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))
    ]


async def _coverage_data(db: AsyncSession, type: str | None) -> CoverageData:
    """Fakultet, kurs/guruh yoki kafedra kesimidagi holatlar — bitta GROUP BY so'rov bilan."""
    stmt = (
        select(Faculty.name, StudentStaff.group_or_position, StudentStaff.biometrics_status,
               func.count(StudentStaff.id))
        .select_from(StudentStaff)
        .outerjoin(Faculty, StudentStaff.faculty_id == Faculty.id)
        .where(StudentStaff.active.is_(True))
        .group_by(Faculty.name, StudentStaff.group_or_position, StudentStaff.biometrics_status)
    )
    if type:
        stmt = stmt.where(StudentStaff.type == type)

    data = CoverageData()
    for faculty_name, unit, bio_status, count in (await db.execute(stmt)).all():
        data.add(type, faculty_name or NO_FACULTY_LABEL, unit, bio_status, count)
    return data


PERSON_TYPE_TITLES = {"talaba": "Talabalar", "xodim": "Xodimlar"}
PERSON_TYPE_SLUGS = {"talaba": "talabalar", "xodim": "xodimlar"}


def _people_title(type: str | None, biometrics: str | None) -> str:
    base = f"{PERSON_TYPE_TITLES[type]} ro'yxati" if type in PERSON_TYPE_TITLES else "Talabalar va xodimlar ro'yxati"
    if biometrics == "tasdiqlangan":
        return f"{base} — ro'yxatdan o'tganlar"
    if biometrics in (UNCONFIRMED_FILTER, "yoq"):
        return f"{base} — ro'yxatdan o'tmaganlar"
    if biometrics == "kutilmoqda":
        return f"{base} — tasdiqlash kutilmoqda"
    return base


def _filter_label(type: str | None, faculty: str | None, search: str | None,
                  biometrics: str | None, course: int | None = None) -> str:
    """Faylga qaysi filtr bilan tuzilgani yoziladi — keyin ochgan odam
    "bu to'liq ro'yxatmi yoki bir qismimi" deb adashmasligi uchun."""
    parts = []
    if type:
        parts.append(f"Turi: {'Talaba' if type == 'talaba' else 'Xodim'}")
    if faculty == NO_FACULTY_KEY:
        parts.append(f"Fakultet: {NO_FACULTY_LABEL}")
    elif faculty:
        parts.append(f"Fakultet: {faculty}")
    if course:
        parts.append(f"Kurs: {course_label(course)}")
    if biometrics:
        label = BIOMETRICS_FILTER_LABELS.get(biometrics) or STATUS_LABELS.get(biometrics, biometrics)
        parts.append(f"Yuz holati: {label}")
    if search and search.strip():
        parts.append(f"Qidiruv: «{search.strip()}»")
    return "Filtr: " + "; ".join(parts) if parts else "Filtr qo'llanmagan — to'liq ro'yxat"


@router.get("/export")
async def export_students_staff(
    db: Annotated[AsyncSession, Depends(get_db)],
    # Faylda JSHSHIR va shaxs ma'lumotlari bor — reestrni ko'rish huquqi
    # yetarli emas, alohida "Ma'lumotlarni eksport qilish" huquqi kerak.
    _: Annotated[CurrentUser, Depends(require_permission("exportData"))],
    kind: Annotated[Literal["people", "stats"], Query()] = "people",
    type: Annotated[Literal["talaba", "xodim"] | None, Query()] = None,
    faculty: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    biometrics: Annotated[str | None, Query(alias="biometricsStatus")] = None,
    course: Annotated[int | None, Query(ge=1, le=10)] = None,
) -> Response:
    """Excel (.xlsx) fayl — ikki xil.

    kind=people — har bir odam alohida qator, tanlangan filtr bo'yicha:
    turi (talaba/xodim), fakultet, kurs, yuz holati ("tasdiqlanmagan" —
    ro'yxatdan o'tmagan har kim) va qidiruv. Talabalar faylida Kurs va
    Guruh, xodimlar faylida Kafedra alohida ustunda; qatorlar fakultet,
    kurs, guruh va ism bo'yicha tartiblangan.

    kind=stats — qamrov statistikasi. Faqat "turi" filtri qo'llanadi:
    statistika butun manzarani ko'rsatish uchun, va bitta fakultetga
    qisqartirilgan "umumiy statistika" o'z nomiga zid bo'lardi. Talabalar
    uchun kurs va guruh kesimi, xodimlar uchun kafedra kesimi.

    CSV nima uchun almashtirilgani — app/services/staff_export.py
    docstringida."""
    return await _export_response(db, kind, type, faculty, search, biometrics, course)


@router.post("/export")
async def export_students_staff_post(
    body: StudentStaffExportIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    # GET /export bilan bir xil fayl (JSHSHIR bor) — huquq ham bir xil.
    _: Annotated[CurrentUser, Depends(require_permission("exportData"))],
) -> Response:
    """GET /export bilan bir xil fayl; filtr so'rov tanasida (URL'da JSHSHIR qolmaydi)."""
    return await _export_response(
        db, body.kind, body.type, body.faculty, body.search, body.biometrics_status, body.course
    )


async def _export_response(
    db: AsyncSession,
    kind: str,
    type: str | None,
    faculty: str | None,
    search: str | None,
    biometrics: str | None,
    course: int | None,
) -> Response:
    now = local_now()
    stamp = now.strftime("%Y-%m-%d")
    slug = PERSON_TYPE_SLUGS.get(type, "talabalar-va-xodimlar")

    if kind == "stats":
        data = await _coverage_data(db, type)
        scope = f"Turi: {PERSON_TYPE_TITLES[type]}" if type else "Barcha turdagi shaxslar"
        content = await asyncio.to_thread(build_stats_workbook, data, scope, now, type)
        filename = f"{slug}-statistika-{stamp}.xlsx"
    else:
        records = (await db.execute(_filtered_query(type, faculty, search, biometrics, course))).scalars().all()
        rows = sorted(
            (
                PersonRow(
                    full_name=r.full_name,
                    pinfl=r.pinfl or "",
                    type=r.type,
                    faculty=r.faculty.name if r.faculty else NO_FACULTY_LABEL,
                    unit=r.group_or_position,
                    biometrics_status=r.biometrics_status,
                    confirmed_at=_confirmed_label(r) or "",
                )
                for r in records
            ),
            key=person_sort_key,
        )
        content = await asyncio.to_thread(
            partial(
                build_people_workbook,
                rows,
                _filter_label(type, faculty, search, biometrics, course),
                now,
                person_type=type,
                title=_people_title(type, biometrics),
            )
        )
        filename = f"{slug}-{stamp}.xlsx"

    return Response(
        content=content,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


SIMILAR_LIMIT = 10


async def _find_similar(db: AsyncSession, full_name: str, type: str | None) -> list[StudentStaff]:
    """Bazadagi shu (yoki boshqacha yozilgan) ismli odamlar — rasmiy JSHSHIRli
    yozuvlar birinchi. Qoida app/services/name_matching.py da, dublikatlarni
    birlashtiruvchi skript bilan bir xil."""
    key, tokens = name_key(full_name), name_tokens(full_name)
    stmt = select(StudentStaff.id, StudentStaff.full_name)
    if type:
        stmt = stmt.where(StudentStaff.type == type)
    ids = [
        row_id
        for row_id, name in (await db.execute(stmt)).all()
        if name_key(name) == key or names_match(tokens, name_tokens(name))
    ]
    if not ids:
        return []
    records = (
        await db.execute(select(StudentStaff).options(selectinload(StudentStaff.faculty)).where(StudentStaff.id.in_(ids[:50])))
    ).scalars().all()
    return sorted(records, key=lambda r: (r.pinfl is None, r.biometrics_status != "tasdiqlangan", r.full_name))[:SIMILAR_LIMIT]


class _DupPersonOut(CamelModel):
    id: str
    full_name: str
    type: str
    group_or_position: str
    has_pinfl: bool
    biometrics_status: str
    self_registered: bool
    attendance: int
    created_at: str | None
    # Yuz rasmi — "yuz bo'yicha" guruhni ko'z bilan tekshirish uchun.
    photo_url: str | None = None


class _DupGroupOut(CamelModel):
    keeper: _DupPersonOut
    duplicates: list[_DupPersonOut]
    reason: str = "ism"
    face_similarity: float | None = None
    mergeable: bool = True


class _MergeGroupIn(CamelModel):
    keep_id: uuid.UUID
    remove_ids: list[uuid.UUID]


class _MergeIn(CamelModel):
    groups: list[_MergeGroupIn]


class _MergeOut(CamelModel):
    merged_groups: int
    removed: int
    errors: list[str]


def _dup_person(row: dict) -> _DupPersonOut:
    created = row.get("created_at")
    return _DupPersonOut(
        id=str(row["id"]),
        full_name=row["full_name"],
        type=row["type"],
        group_or_position=row.get("group_or_position") or "",
        # JSHSHIR raqamining o'zi chiqarilmaydi — faqat bor/yo'qligi.
        has_pinfl=bool(row.get("pinfl")),
        biometrics_status=row.get("biometrics_status") or "yoq",
        self_registered=bool(row.get("self_registered")),
        attendance=int(row.get("att") or 0),
        created_at=to_local(created).strftime("%d.%m.%Y") if created else None,
        photo_url=presigned_url(row["biometric_photo_key"]) if row.get("biometric_photo_key") else None,
    )


@router.get("/dublikatlar", response_model=list[_DupGroupOut])
async def duplicate_people(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
) -> list[_DupGroupOut]:
    """Bir odamning bir nechta faol yozuvi (app/services/person_dedupe.py)."""
    groups = await person_dedupe.find_duplicates(db)
    return [
        _DupGroupOut(
            keeper=_dup_person(g.keeper),
            duplicates=[_dup_person(d) for d in g.duplicates],
            reason=g.reason,
            face_similarity=g.face_similarity,
            mergeable=g.mergeable,
        )
        for g in groups
    ]


@router.post("/dublikatlar/birlashtirish", response_model=_MergeOut)
async def merge_duplicate_people(
    body: _MergeIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
) -> _MergeOut:
    """Har guruh — alohida tranzaksiya: bittasi xato bersa, qolganlari davom etadi."""
    merged = removed = 0
    errors: list[str] = []
    for group in body.groups[:500]:
        try:
            names = []
            for dup_id in group.remove_ids:
                dup = await db.get(StudentStaff, dup_id)
                label = dup.full_name if dup else str(dup_id)
                moved = await person_dedupe.merge_people(db, group.keep_id, dup_id)
                names.append(f"{label} ({', '.join(f'{k}: {v}' for k, v in moved.items()) or 'bo‘sh'})")
            keeper = await db.get(StudentStaff, group.keep_id)
            await log_action(
                db, request, current_user.id,
                f"Dublikat birlashtirildi: {keeper.full_name if keeper else group.keep_id} ← {'; '.join(names)}",
                "Shaxslar reestri",
            )
            await db.commit()
            merged += 1
            removed += len(group.remove_ids)
        except person_dedupe.MergeError as exc:
            await db.rollback()
            errors.append(str(exc))
        except Exception:
            await db.rollback()
            logger.exception("duplicate merge failed", extra={"keep_id": str(group.keep_id)})
            errors.append(f"{group.keep_id}: birlashtirib bo'lmadi")
    if merged:
        # Yuz va galereya o'zgardi — tanish matritsasi yangilansin.
        await announce_roster_change()
    return _MergeOut(merged_groups=merged, removed=removed, errors=errors)


@router.get("/similar", response_model=list[StudentStaffOut])
async def similar_people(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
    full_name: Annotated[str, Query(alias="fullName", min_length=2, max_length=200)],
    type: Annotated[Literal["talaba", "xodim"] | None, Query()] = None,
) -> list[StudentStaffOut]:
    """"Yangi biriktirish" 1-qadamida: bu odam bazada allaqachon bormi.

    Import qilingan xodimlarning bir qismi shu oyna orqali qayta qo'shilgan
    va yuzi yangi (JSHSHIRsiz) yozuvda tasdiqlangan edi — natijada bir odam
    ikki marta sanalardi (scripts/merge_duplicate_people.py)."""
    return [_to_out(r, r.faculty.name if r.faculty else "") for r in await _find_similar(db, full_name, type)]


@router.post("", response_model=StudentStaffOut, status_code=status.HTTP_201_CREATED)
async def create_student_staff(
    body: StudentStaffCreateIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
) -> StudentStaffOut:
    # Oynadagi ogohlantirish chetlab o'tilsa ham (eski sahifa, to'g'ridan-
    # to'g'ri so'rov) dublikat jimgina yaratilmasin: admin "bu boshqa odam"
    # deb aniq tasdiqlagandagina (allowDuplicate) yaratiladi.
    if not body.allow_duplicate:
        similar = await _find_similar(db, body.full_name, body.type)
        if similar:
            listed = "; ".join(f"{r.full_name} ({r.group_or_position})" for r in similar[:3])
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Bazada shu ismli {'talaba' if body.type == 'talaba' else 'xodim'} bor: {listed}. "
                "Mavjud yozuvga yuz biriktiring yoki bu boshqa odam ekanini tasdiqlang.",
            )
    faculty = await _resolve_faculty(db, body.faculty)
    card = _clean_card(body.card_number)
    await _ensure_card_free(db, card)
    record = StudentStaff(
        full_name=body.full_name,
        type=body.type,
        faculty_id=faculty.id,
        group_or_position=body.group_or_position,
        biometrics_status=body.biometrics_status,
        parent_phone=_clean_parent_phone(body.parent_phone),
        parent_notify_enabled=body.parent_notify_enabled and body.type == "talaba",
        card_number=card,
    )
    db.add(record)
    label = "Talaba" if body.type == "talaba" else "Xodim"
    await log_action(db, request, current_user.id, f"{label} qo'shdi: {body.full_name}", "Talabalar")
    try:
        await db.commit()
    except IntegrityError:
        # Parallel so'rov xuddi shu kartani oldinroq yozib ulgurdi.
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, CARD_CONFLICT_MESSAGE) from None
    await db.refresh(record)
    return _to_out(record, faculty.name)


@router.post("/import", response_model=StudentStaffImportResultOut)
async def import_students_staff(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
    file: Annotated[UploadFile, File(description="UTF-8 CSV: full_name,type,faculty,group_or_position")],
) -> StudentStaffImportResultOut:
    """Bulk-import talaba/xodim rows from CSV. Biometrics are NOT imported —
    each row starts with biometrics_status=yoq."""
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "CSV hajmi 5 MB dan oshmasligi kerak")
    result = await import_students_staff_csv(db, raw)
    if result.imported:
        await announce_roster_change()
    await log_action(
        db,
        request,
        current_user.id,
        f"CSV import: {result.imported} qo'shildi, {result.skipped} o'tkazib yuborildi, {len(result.errors)} xato",
        "Talabalar",
    )
    await db.commit()
    if result.imported:
        logger.info("CSV import complete", extra={"imported": result.imported, "skipped": result.skipped})
    return result


def _to_detail(record: StudentStaff) -> StudentStaffDetailOut:
    base = _to_out(record, record.faculty.name if record.faculty else "")
    return StudentStaffDetailOut(
        **base.model_dump(),
        pinfl=record.pinfl,
        passport_series=record.passport_series,
        passport_number=record.passport_number,
        parent_phone=record.parent_phone,
        parent_notify_enabled=record.parent_notify_enabled,
        parent_telegram_linked=bool(record.parent_telegram_chat_id),
        card_number=record.card_number,
    )


async def _load_record(db: AsyncSession, record_id: str) -> StudentStaff:
    try:
        record_uuid = uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi") from None
    result = await db.execute(
        select(StudentStaff)
        .options(selectinload(StudentStaff.faculty))
        .where(StudentStaff.id == record_uuid)
        .execution_options(populate_existing=True)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")
    return record


@router.get("/{record_id}/details", response_model=StudentStaffDetailOut)
async def student_staff_details(
    record_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
) -> StudentStaffDetailOut:
    """Tahrirlash oynasi: JSHSHIR va pasport bilan bitta yozuv."""
    return _to_detail(await _load_record(db, record_id))


def _clean_pinfl(value: str) -> str | None:
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return None
    if len(digits) != 14:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "JSHSHIR 14 ta raqamdan iborat bo'lishi kerak")
    return digits


def _clean_passport(series: str, number: str) -> tuple[str | None, str | None]:
    clean_series = "".join(ch for ch in series if ch.isalpha()).upper()
    clean_number = "".join(ch for ch in number if ch.isdigit())
    if not clean_series and not clean_number:
        return None, None
    if len(clean_series) != 2 or len(clean_number) != 7:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Pasport seriyasi 2 ta harf, raqami 7 ta raqam bo'lishi kerak (masalan: AD 1234567)",
        )
    return clean_series, clean_number


def _compose_unit(body: StudentStaffUpdateIn) -> str:
    if body.type == "talaba" and body.course is not None:
        group = (body.group or "").strip()
        return f"{body.course}-kurs, {group}" if group else f"{body.course}-kurs"
    unit = body.group_or_position.strip()
    if not unit and body.type == "talaba":
        unit = (body.group or "").strip()
    if not unit:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Kurs yoki guruh kiritilishi shart" if body.type == "talaba" else "Lavozim kiritilishi shart",
        )
    return unit


@router.patch("/{record_id}", response_model=StudentStaffDetailOut)
async def update_student_staff(
    record_id: str,
    body: StudentStaffUpdateIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
) -> StudentStaffDetailOut:
    record = await _load_record(db, record_id)
    faculty = await _resolve_faculty(db, body.faculty)
    sent = body.model_fields_set
    changed_identity: list[str] = []

    if "pinfl" in sent:
        pinfl = _clean_pinfl(body.pinfl or "")
        if pinfl != record.pinfl:
            if pinfl is not None:
                other = (
                    await db.execute(
                        select(StudentStaff).where(StudentStaff.pinfl == pinfl).where(StudentStaff.id != record.id)
                    )
                ).scalar_one_or_none()
                if other is not None:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        f"Bu JSHSHIR boshqa yozuvga biriktirilgan: {other.full_name} ({other.group_or_position})",
                    )
            record.pinfl = pinfl
            changed_identity.append("JSHSHIR")

    if "passport_series" in sent or "passport_number" in sent:
        series, number = _clean_passport(
            (body.passport_series or "") if "passport_series" in sent else (record.passport_series or ""),
            (body.passport_number or "") if "passport_number" in sent else (record.passport_number or ""),
        )
        if (series, number) != (record.passport_series, record.passport_number):
            if series is not None:
                other = (
                    await db.execute(
                        select(StudentStaff)
                        .where(StudentStaff.passport_series == series)
                        .where(StudentStaff.passport_number == number)
                        .where(StudentStaff.id != record.id)
                    )
                ).scalars().first()
                if other is not None:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        f"Bu pasport boshqa yozuvga biriktirilgan: {other.full_name} ({other.group_or_position})",
                    )
            record.passport_series = series
            record.passport_number = number
            changed_identity.append("pasport")

    if "card_number" in sent:
        card = _clean_card(body.card_number)
        if card != record.card_number:
            await _ensure_card_free(db, card, exclude_id=record.id)
            record.card_number = card
            changed_identity.append("karta")

    if "parent_phone" in sent:
        phone = _clean_parent_phone(body.parent_phone)
        if phone != record.parent_phone:
            record.parent_phone = phone
            changed_identity.append("ota-ona telefoni")
    if "parent_notify_enabled" in sent and body.parent_notify_enabled is not None:
        record.parent_notify_enabled = body.parent_notify_enabled

    type_changed = record.type != body.type
    record.full_name = body.full_name
    record.type = body.type
    record.faculty_id = faculty.id
    record.group_or_position = _compose_unit(body)
    if body.type != "talaba":
        # Ota-ona xabarnomasi faqat talabalar uchun.
        record.parent_notify_enabled = False

    # Audit jurnaliga raqamlarning o'zi emas, faqat NIMA o'zgargani yoziladi.
    suffix = f" ({', '.join(changed_identity)} yangilandi)" if changed_identity else ""
    await log_action(db, request, current_user.id, f"Yozuvni tahrirladi: {body.full_name}{suffix}", "Talabalar")
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Karta raqami yoki JSHSHIR boshqa yozuvga biriktirilgan"
        ) from None
    if type_changed and record.biometric_embedding:
        # Xodim/talaba ajratmasi yuz matritsasida saqlanadi (#6/#7 davomati,
        # #26 faqat xodimlarni qidiradi) — eski tur bilan qolmasin.
        await announce_roster_change()
    return _to_detail(await _load_record(db, record_id))


@router.get("/{record_id}/biometrics-confirmation", response_model=BiometricsConfirmationOut)
async def biometrics_confirmation(
    record_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
) -> BiometricsConfirmationOut:
    """Odam yuzini aniq qachon tasdiqlagani — Toshkent vaqtida."""
    try:
        record_uuid = uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi") from None
    result = await db.execute(
        select(StudentStaff).options(selectinload(StudentStaff.faculty)).where(StudentStaff.id == record_uuid)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")

    moment, source = await _confirmation_moment(record)
    parts = uz_datetime_parts(moment) if moment is not None else None
    base = _to_out(record, record.faculty.name if record.faculty else "")
    return BiometricsConfirmationOut(
        id=base.id,
        full_name=base.full_name,
        type=base.type,
        faculty=base.faculty,
        group_or_position=base.group_or_position,
        biometrics_status=base.biometrics_status,
        initials=base.initials,
        biometric_photo_url=base.biometric_photo_url,
        confirmed_at=parts.iso if parts else None,
        confirmed_date=parts.date if parts else None,
        confirmed_weekday=parts.weekday if parts else None,
        confirmed_time=parts.time if parts else None,
        source=source,
    )


async def _confirmation_moment(record: StudentStaff) -> tuple[datetime | None, str]:
    """Tasdiqlash vaqti va u qayerdan olingani.

    biometrics_confirmed_at ustuni paydo bo'lishidan oldin tasdiqlaganlar
    uchun eng aniq manba — yuz rasmi omborga yozilgan payt: rasm aynan
    tasdiqlash so'rovi ichida saqlanadi. Qayta tasdiqlashda rasm
    almashtiriladi, ya'ni bu har doim OXIRGI tasdiqlash vaqti — ustun
    ham xuddi shunday ishlaydi. Tiklangan vaqt bazaga yozilmaydi: u
    boshqa manbadan olingani javobda ko'rinib turishi kerak."""
    if record.biometrics_status != "tasdiqlangan":
        return None, "tasdiqlanmagan"
    if record.biometrics_confirmed_at is not None:
        return record.biometrics_confirmed_at, "tizim"
    if record.biometric_photo_key:
        try:
            moment = await asyncio.to_thread(object_last_modified, record.biometric_photo_key)
        except Exception:
            logger.warning(
                "could not read biometric photo timestamp", extra={"record_id": str(record.id)}, exc_info=True
            )
            moment = None
        if moment is not None:
            return moment, "rasm"
    return None, "nomalum"


@router.post("/{record_id}/biometrics", response_model=StudentStaffOut)
async def enroll_biometrics(
    record_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
    photo: Annotated[UploadFile, File(description="Kamerada suratga olingan jonli yuz — ro'yxatdan o'tkazish vizardining yakuniy bosqichi")],
) -> StudentStaffOut:
    """Persists what AddStudentStaffModal.tsx's face-match step used to
    throw away: the enrollment photo (to MinIO) and its ArcFace embedding
    (to the DB, JSON-encoded) — see biometric_photo_key/biometric_embedding
    on the model for why. A pure /api/face/compare call never touches this
    endpoint; this only runs once the wizard's match step has passed."""
    # Shu fayldagi boshqa endpointlar bilan bir xil yo'l: _load_record
    # identifikator shaklini tekshiradi. Xom satr UUID ustuniga
    # solishtirilganda Postgres darajasida xato bo'lib, 404 o'rniga 500
    # qaytardi.
    record = await _load_record(db, record_id)
    # Yuz faqat 3 burchakdan (ro'yxatdan o'tish havolasi: old, chap, o'ng)
    # kiritiladi — bitta surat bilan "tasdiqlangan" yuz yaratilmaydi.
    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Yuz faqat 3 tomondan (old, chap, o'ng) kiritiladi — odamga ro'yxatdan o'tish havolasini bering",
    )

    data = await photo.read()
    if len(data) > MAX_PHOTO_SIZE_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Fayl hajmi 10 MB dan oshmasligi kerak")

    try:
        embedding = await extract_embedding(data)
    except NoFaceDetectedError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    # upload_file is a blocking boto3 network call — off the event loop,
    # same as app/services/event_bus.py's snapshot upload. On a busy API
    # process a synchronous S3 round trip here stalls every other request.
    previous_key = record.biometric_photo_key
    _file_id, key = await asyncio.to_thread(
        upload_file, data, photo.filename or "face.jpg", photo.content_type or "image/jpeg", "biometrics"
    )
    record.biometric_photo_key = key
    record.biometric_embedding = json.dumps(embedding)
    record.biometrics_status = "tasdiqlangan"
    record.biometrics_confirmed_at = datetime.now(timezone.utc)

    await log_action(db, request, current_user.id, f"Biometrik ma'lumot saqlandi: {record.full_name}", "Talabalar")
    await db.commit()
    await db.refresh(record)
    # Re-enrollment replaces the key on the row; without this the previous
    # photo stays in object storage with nothing referencing it, forever.
    if previous_key and previous_key != key:
        await delete_files_quietly([previous_key])
    await announce_roster_change()
    return _to_out(record, record.faculty.name if record.faculty else "")


async def _awaiting_record(db: AsyncSession, record_id: str) -> StudentStaff:
    record = await _load_record(db, record_id)
    if not record.awaiting_approval:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu yozuv tasdiqlashni kutmayapti")
    return record


class BulkApproveOut(CamelModel):
    approved: int
    skipped_angles: int


@router.post("/biometrics/approve-all", response_model=BulkApproveOut)
async def approve_all_awaiting(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
    type: Annotated[Literal["talaba", "xodim"] | None, Query()] = None,
) -> BulkApproveOut:
    """Tasdiq kutayotgan barcha yuzlarni bir bosishda tasdiqlash (administrator
    qarori). Uch tomoni (old, chap, o'ng) to'liq bo'lmaganlar tasdiqlanmaydi."""
    stmt = select(StudentStaff).where(AWAITING_APPROVAL, StudentStaff.active.is_(True))
    if type:
        stmt = stmt.where(StudentStaff.type == type)
    rows = (await db.execute(stmt)).scalars().all()
    now = datetime.now(timezone.utc)
    approved = skipped = 0
    for record in rows:
        if not record.has_all_angles:
            skipped += 1
            continue
        record.biometrics_status = "tasdiqlangan"
        record.biometrics_confirmed_at = now
        record.biometrics_review_reason = None
        approved += 1
    await log_action(
        db, request, current_user.id,
        f"Tasdiq kutayotganlar ommaviy tasdiqlandi: {approved} ta (3 tomoni yo'q: {skipped})", "Talabalar",
    )
    await db.commit()
    if approved:
        await announce_roster_change()
    return BulkApproveOut(approved=approved, skipped_angles=skipped)


@router.post("/{record_id}/biometrics/approve", response_model=StudentStaffOut)
async def approve_self_enrollment(
    record_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
) -> StudentStaffOut:
    """O'zini o'zi ro'yxatdan o'tkazgan odamning yuzini tasdiqlash.

    Shu paytdan u davomatga tushadi va kameralar uni begona deb
    hisoblamaydi. Qaror audit jurnaliga yoziladi."""
    record = await _awaiting_record(db, record_id)
    if not record.has_all_angles:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Yuz 3 tomondan olinmagan — tasdiqlab bo'lmaydi. Odam ro'yxatdan o'tish havolasi orqali qayta o'tsin",
        )
    record.biometrics_status = "tasdiqlangan"
    record.biometrics_confirmed_at = datetime.now(timezone.utc)
    record.biometrics_review_reason = None
    await log_action(
        db, request, current_user.id, f"O'zi ro'yxatdan o'tgan odamni tasdiqladi: {record.full_name}", "Talabalar"
    )
    await db.commit()
    await announce_roster_change()
    return _to_out(record, record.faculty.name if record.faculty else "")


@router.post("/{record_id}/biometrics/reject", response_model=StudentStaffOut)
async def reject_self_enrollment(
    record_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
) -> StudentStaffOut:
    """Yuborilgan yuzni rad etish: rasm va yuz vektori o'chiriladi, yozuv
    "yo'q" holatiga qaytadi (odam qayta yuborishi mumkin). Yozuvning
    o'zini butunlay o'chirish — DELETE."""
    record = await _awaiting_record(db, record_id)
    photo_keys = clear_biometrics(record)
    record.biometrics_review_reason = None
    await log_action(
        db, request, current_user.id, f"O'zi ro'yxatdan o'tgan odamning yuzini rad etdi: {record.full_name}", "Talabalar"
    )
    await db.commit()
    if photo_keys:
        await delete_files_quietly(photo_keys)
    return _to_out(record, record.faculty.name if record.faculty else "")


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student_staff(
    record_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("registerPeople"))],
) -> None:
    """Odamni ro'yxatdan butunlay o'chiradi.

    Qator bilan birga unga bog'liq yozuvlar ham ketadi (FK ON DELETE
    CASCADE): kunlik davomat, tashriflar va dars davomati. Dars jadvali
    yozuvining o'zi qoladi, faqat o'qituvchi maydoni bo'shaydi (SET
    NULL) — o'tilgan dars tarixi odam o'chirilgani uchun yo'qolmasligi
    kerak.

    Yuz rasmi ombordan ham o'chiriladi: bazada unga ishora qolmagach, u
    faqat egasiz biometrik ma'lumot bo'lib qolardi. Yuz vektorlari keshi
    esa darhol bekor qilinadi — aks holda o'chirilgan odam keyingi bir
    necha daqiqa davomida kameralarda tanilishda davom etardi
    (app/services/face_matching.py sweep keshi).

    Yumshoq o'chirish (arxivga olish) ataylab emas: tizimda bunday naqsh
    yo'q va "o'chirildi, lekin hali ham tanilyapti" holati odamni
    chalkashtiradi. Amal audit jurnaliga yoziladi."""
    record = await _load_record(db, record_id)
    # Qiymatlar O'CHIRISHDAN OLDIN olinadi: commit'dan keyin obyekt
    # maydonlariga murojaat qilish bazadan yo'q qatorni qayta o'qishga
    # urinadi va xato beradi.
    photo_key = record.biometric_photo_key
    person_type = record.type
    label = f"{record.full_name} ({PERSON_TYPE_LABELS.get(person_type, person_type)})"

    await log_action(db, request, current_user.id, f"Ro'yxatdan o'chirdi: {label}", "Talabalar")
    await db.delete(record)
    await db.commit()

    if photo_key:
        await delete_files_quietly([photo_key])
    await announce_roster_change()
    logger.info("person deleted", extra={"record_id": record_id, "type": person_type})
