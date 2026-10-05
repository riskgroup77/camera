"""Rozilik, shaxsiy ma'lumotlarni eksport/o'chirish, saqlash muddati.

Hamma boshqaruv endpointlari `managePrivacy` huquqini talab qiladi (standart
bo'yicha faqat bosh administrator) va har bir o'zgarish audit jurnaliga
yoziladi. Ochiq endpoint bitta: rozilik matni — uni ro'yxatdan o'tish
sahifasi hisobsiz odamga ko'rsatadi.

Biznes mantiq app/services/privacy.py da; avtomatik saqlash muddati —
app/jobs/cleanup.py.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.config import settings
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.models import StudentStaff
from app.pagination import Page, PageParams, build_page, paginate
from app.schemas.privacy import (
    ConsentRecordIn,
    ConsentSectionOut,
    ConsentTextOut,
    ErasureOut,
    PrivacyBiometricsOut,
    PrivacyFilter,
    PrivacyOverviewOut,
    PrivacyPeopleSearchIn,
    PrivacyPersonOut,
)
from app.services.face_matching import announce_roster_change
from app.services.privacy import (
    CONSENT_SOURCE_LABELS,
    CONSENT_STATEMENT,
    CONSENT_TITLE,
    biometric_purge_at,
    biometric_summary,
    build_export,
    clear_biometrics,
    compute_overview,
    consent_sections,
    erase_face_samples,
    finish_erasure,
    has_biometrics_clause,
    person_has_biometrics,
    record_consent,
    unique_keys,
    withdraw_consent,
)

logger = logging.getLogger("app.privacy")

router = APIRouter(tags=["privacy"])

AUDIT_MODULE = "Maxfiylik"


def _to_out(person: StudentStaff) -> PrivacyPersonOut:
    return PrivacyPersonOut(
        id=str(person.id),
        full_name=person.full_name,
        type=person.type,
        group_or_position=person.group_or_position,
        faculty_name=person.faculty.name if person.faculty else None,
        active=person.active,
        deactivated_at=person.deactivated_at,
        has_biometrics=person_has_biometrics(person),
        biometrics_status=person.biometrics_status,
        consent_given_at=person.consent_given_at,
        consent_version=person.consent_version,
        consent_source=person.consent_source,
        consent_current=person.consent_given_at is not None and person.consent_version == settings.consent_version,
        biometric_purge_at=biometric_purge_at(person),
    )


async def _erase(db: AsyncSession, person: StudentStaff) -> list[str]:
    """Yozuvdagi va undan tashqaridagi (galereya, biriktirilgan kadrlar)
    biometrikani tozalaydi; commit'dan keyin o'chiriladigan kalitlarni
    qaytaradi."""
    photo_keys = clear_biometrics(person)
    # Rozilik qaytarilgan / o'chirish so'ralgan: HEMIS suratidan yuz qayta
    # avtomatik kiritilmaydi (app/jobs/hemis_photos.py).
    person.biometrics_opt_out_at = datetime.now(timezone.utc)
    extra = await erase_face_samples(db, [person.id])
    return unique_keys([*photo_keys, *extra])


async def _get_person(db: AsyncSession, person_id: str) -> StudentStaff:
    try:
        key = uuid.UUID(person_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi") from None
    person = await db.get(StudentStaff, key)
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Yozuv topilmadi")
    return person


# ---------------------------------------------------------------------------
# Ochiq: rozilik matni
# ---------------------------------------------------------------------------


@router.get("/api/public/consent-text", response_model=ConsentTextOut)
async def get_consent_text() -> ConsentTextOut:
    """Ro'yxatdan o'tish sahifasidagi rozilik matni. Hisob talab
    qilinmaydi — odam yuzini yuborishdan OLDIN nimaga rozi bo'layotganini
    o'qishi kerak. Faqat sozlamalardan yig'iladigan statik matn: bazaga
    murojaat yo'q, shuning uchun alohida cheklov ham kerak emas."""
    return ConsentTextOut(
        version=settings.consent_version,
        required=settings.consent_required_for_enrollment,
        title=CONSENT_TITLE,
        controller=settings.org_name,
        sections=[ConsentSectionOut(title=t, body=b) for t, b in consent_sections()],
        statement=CONSENT_STATEMENT,
    )


# ---------------------------------------------------------------------------
# Umumiy holat va ro'yxat
# ---------------------------------------------------------------------------


@router.get("/api/privacy/overview", response_model=PrivacyOverviewOut)
async def privacy_overview(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission("managePrivacy"))],
) -> PrivacyOverviewOut:
    return PrivacyOverviewOut.model_validate(await compute_overview(db))


@router.get("/api/privacy/people", response_model=Page[PrivacyPersonOut])
async def list_privacy_people(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission("managePrivacy"))],
    page_params: Annotated[PageParams, Depends()],
    search: Annotated[str | None, Query(max_length=100)] = None,
    filter_: Annotated[PrivacyFilter | None, Query(alias="filter")] = None,
) -> Page[PrivacyPersonOut]:
    stmt = _people_query(search, filter_)
    records, total = await paginate(db, stmt, page_params)
    return build_page([_to_out(p) for p in records], total, page_params)


@router.post("/api/privacy/people/search", response_model=Page[PrivacyPersonOut])
async def search_privacy_people(
    body: PrivacyPeopleSearchIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission("managePrivacy"))],
) -> Page[PrivacyPersonOut]:
    """GET bilan bir xil, filtr so'rov tanasida — JSHSHIR URL'ga tushmaydi."""
    page_params = PageParams(page=body.page, page_size=body.page_size)
    stmt = _people_query(body.search, body.filter)
    records, total = await paginate(db, stmt, page_params)
    return build_page([_to_out(p) for p in records], total, page_params)


def _people_query(search: str | None, filter_: PrivacyFilter | None):
    stmt = select(StudentStaff)
    if filter_ == "no_consent":
        # Amaliy xavf ro'yxati: yuzi saqlangan, lekin rozilik qayd
        # etilmagan. Biometrikasi yo'q odamga biometrik rozilik kerak emas.
        stmt = stmt.where(and_(has_biometrics_clause(), StudentStaff.consent_given_at.is_(None)))
    elif filter_ == "inactive":
        stmt = stmt.where(StudentStaff.active.is_(False))
    elif filter_ == "with_biometrics":
        stmt = stmt.where(has_biometrics_clause())

    term = (search or "").strip()
    if term:
        digits = "".join(ch for ch in term if ch.isdigit())
        conditions = [StudentStaff.full_name.ilike(f"%{term}%")]
        if len(digits) >= 4:
            conditions.append(StudentStaff.pinfl.startswith(digits))
        conditions.append(StudentStaff.hemis_id == term)
        stmt = stmt.where(or_(*conditions))

    return stmt.order_by(StudentStaff.full_name, StudentStaff.id)


# ---------------------------------------------------------------------------
# Rozilik
# ---------------------------------------------------------------------------


@router.post("/api/privacy/people/{person_id}/consent", response_model=PrivacyPersonOut)
async def record_person_consent(
    person_id: str,
    body: ConsentRecordIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("managePrivacy"))],
) -> PrivacyPersonOut:
    """Qog'ozdagi yoki og'zaki (administrator orqali) rozilikni qayd etish.
    Joriy matn versiyasi yoziladi."""
    person = await _get_person(db, person_id)
    record_consent(person, body.source)
    note = (body.note or "").strip()
    action = f"Biometrik rozilikni qayd etdi ({CONSENT_SOURCE_LABELS[body.source]}): {person.full_name}"
    if note:
        action += f" — {note}"
    await log_action(db, request, current_user.id, action, AUDIT_MODULE)
    await db.commit()
    return _to_out(person)


@router.delete("/api/privacy/people/{person_id}/consent", response_model=ErasureOut)
async def withdraw_person_consent(
    person_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("managePrivacy"))],
) -> ErasureOut:
    """Rozilikni qaytarib olish. Qonun bo'yicha rozilik qaytarilgach
    biometrik ma'lumotni qayta ishlashga asos qolmaydi, shuning uchun yuz
    rasmi va vektori SHU ZAHOTI o'chiriladi — keyingi tozalash siklini
    kutmasdan."""
    person = await _get_person(db, person_id)
    withdraw_consent(person)
    keys = await _erase(db, person)
    await log_action(
        db,
        request,
        current_user.id,
        f"Biometrik rozilik qaytarib olindi, yuz ma'lumotlari o'chirildi: {person.full_name}",
        AUDIT_MODULE,
    )
    await db.commit()
    deleted = await finish_erasure(keys)
    return ErasureOut(person=_to_out(person), photo_deleted=deleted >= len(keys))


# ---------------------------------------------------------------------------
# Faollik
# ---------------------------------------------------------------------------


@router.post("/api/privacy/people/{person_id}/deactivate", response_model=PrivacyPersonOut)
async def deactivate_person(
    person_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("managePrivacy"))],
) -> PrivacyPersonOut:
    """Bitirgan / ishdan ketgan odam: kameralar uni endi tanimaydi,
    biometrikasi saqlash muddatidan keyin avtomatik o'chiriladi. Yozuv va
    uning davomat tarixi o'chirilmaydi."""
    person = await _get_person(db, person_id)
    if not person.active:
        return _to_out(person)
    person.active = False
    person.deactivated_at = datetime.now(timezone.utc)
    # HEMIS sinxroni admin qarorini bekor qilmasin (hemis._apply_update).
    person.manually_deactivated = True
    await log_action(db, request, current_user.id, f"Faolsizlantirildi: {person.full_name}", AUDIT_MODULE)
    await db.commit()
    if person_has_biometrics(person):
        await announce_roster_change()
    return _to_out(person)


@router.post("/api/privacy/people/{person_id}/activate", response_model=PrivacyPersonOut)
async def activate_person(
    person_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("managePrivacy"))],
) -> PrivacyPersonOut:
    person = await _get_person(db, person_id)
    if person.active:
        return _to_out(person)
    person.active = True
    person.deactivated_at = None
    person.manually_deactivated = False
    await log_action(db, request, current_user.id, f"Qayta faollashtirildi: {person.full_name}", AUDIT_MODULE)
    await db.commit()
    if person_has_biometrics(person):
        await announce_roster_change()
    return _to_out(person)


# ---------------------------------------------------------------------------
# O'chirish va eksport
# ---------------------------------------------------------------------------


@router.post("/api/privacy/people/{person_id}/erase-biometrics", response_model=ErasureOut)
async def erase_person_biometrics(
    person_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("managePrivacy"))],
) -> ErasureOut:
    """Biometrik ma'lumotni o'chirish (sub'ekt talabi bo'yicha). Yozuv,
    davomat tarixi va rozilik qaydi qoladi — faqat yuz rasmi va vektori
    ketadi. Odam keyin qayta ro'yxatdan o'tishi mumkin."""
    person = await _get_person(db, person_id)
    had_biometrics = person_has_biometrics(person)
    keys = await _erase(db, person)
    await log_action(
        db,
        request,
        current_user.id,
        f"Biometrik ma'lumotlar o'chirildi: {person.full_name}"
        + ("" if had_biometrics or keys else " (saqlangan ma'lumot yo'q edi)"),
        AUDIT_MODULE,
    )
    await db.commit()
    deleted = await finish_erasure(keys)
    if deleted < len(keys):
        logger.warning("biometric photo could not be deleted from storage", extra={"person_id": person_id})
    return ErasureOut(person=_to_out(person), photo_deleted=deleted >= len(keys))


@router.get("/api/privacy/people/{person_id}/biometrics", response_model=PrivacyBiometricsOut)
async def person_biometrics(
    person_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("managePrivacy"))],
) -> PrivacyBiometricsOut:
    """Odam haqida nima saqlanayotgani: yuz rasmi, galereya namunalari,
    so'nggi ko'rinishlar. Yuz rasmini ochish ham ma'lumotni oshkor qilish —
    audit jurnaliga yoziladi (eksport bilan bir xil sabab)."""
    person = await _get_person(db, person_id)
    summary = await biometric_summary(db, person)
    await log_action(
        db, request, current_user.id, f"Biometrik ma'lumotlar ko'rildi: {person.full_name}", AUDIT_MODULE
    )
    await db.commit()
    return PrivacyBiometricsOut(person=_to_out(person), **summary)


@router.get("/api/privacy/people/{person_id}/export")
async def export_person_data(
    person_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("managePrivacy"))],
) -> JSONResponse:
    """Sub'ektning o'z ma'lumotlari bilan tanishish huquqi: tizimda u
    haqida saqlanayotgan hamma narsa bitta JSON faylda. Eksportning o'zi
    ham shaxsiy ma'lumotni oshkor qilish, shuning uchun audit jurnaliga
    yoziladi."""
    person = await _get_person(db, person_id)
    payload = await build_export(db, person)
    await log_action(
        db, request, current_user.id, f"Shaxsiy ma'lumotlar eksport qilindi: {person.full_name}", AUDIT_MODULE
    )
    await db.commit()
    filename = f"shaxsiy-malumot-{person.id}.json"
    return JSONResponse(
        payload,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
