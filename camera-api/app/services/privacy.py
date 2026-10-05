"""Shaxsga doir ma'lumotlar: rozilik, biometrikani o'chirish, eksport.

O'zbekiston Respublikasining "Shaxsga doir ma'lumotlar to'g'risida"gi
Qonuni (O'RQ-547) biometrik ma'lumotni alohida toifa sifatida ko'radi:
uni qayta ishlash uchun sub'ektning roziligi kerak, u rozilikni istalgan
vaqtda qaytarib olishi, o'zi haqidagi ma'lumot bilan tanishishi va
maqsadga erishilgach ma'lumot yo'q qilinishini talab qilishi mumkin.

Bu modul shu talablarning texnik tomoni. HTTP qismi —
app/routers/privacy.py, avtomatik saqlash muddati — app/jobs/cleanup.py.
Ikkalasi ham biometrikani AYNAN bir xil yo'l bilan o'chiradi
(clear_biometrics + finish_erasure): aks holda "qo'lda o'chirish" va
"muddat o'tgani uchun o'chirish" vaqt o'tib bir-biridan farqlanib qolardi.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy import ColumnElement, and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    AccessDevice,
    AccessEvent,
    AttendanceRecord,
    Camera,
    Event,
    FaceGalleryEmbedding,
    LessonAttendance,
    LessonSession,
    PresenceVisit,
    StudentStaff,
    UnknownSighting,
)
from app.services.face_matching import announce_roster_change
from app.storage import delete_files_quietly, presigned_url

#: Rozilik qayerdan kelgani (students_staff.consent_source).
CONSENT_SOURCE_LABELS: dict[str, str] = {
    "royxatdan_otish": "Ochiq ro'yxatdan o'tish sahifasi",
    "qogoz": "Qog'ozdagi yozma rozilik",
    "admin": "Administrator qayd etgan",
    "hemis": "HEMIS orqali",
}

#: Eksportdagi har bir bo'limning yuqori chegarasi. Sub'ekt so'rovi to'liq
#: bo'lishi kerak, lekin bitta so'rov serverni osib qo'ymasligi ham kerak —
#: chegaraga yetilsa javobda "truncated" belgisi bo'ladi.
EXPORT_SECTION_LIMIT = 50_000


def has_biometrics_clause() -> ColumnElement[bool]:
    """Yozuvda biometrik ma'lumotning BIRORTA qismi bor: yuz vektori yoki
    rasm. Faqat vektorni tekshirish yetmaydi — rasm o'zi ham biometrik
    ma'lumot."""
    return or_(StudentStaff.biometric_embedding.is_not(None), StudentStaff.biometric_photo_key.is_not(None))


def person_has_biometrics(person: StudentStaff) -> bool:
    return person.biometric_embedding is not None or person.biometric_photo_key is not None


def biometric_purge_at(person: StudentStaff) -> datetime | None:
    """Faol emas odamning biometrikasi qachon avtomatik o'chiriladi.

    None — o'chirish rejalashtirilmagan: odam faol, biometrikasi yo'q
    yoki saqlash muddati 0 (o'chirish o'chirilgan)."""
    days = settings.biometric_retention_days_after_inactive
    if person.active or days <= 0 or not person_has_biometrics(person):
        return None
    start = person.deactivated_at or datetime.now(timezone.utc)
    return start + timedelta(days=days)


def clear_biometrics(person: StudentStaff) -> list[str]:
    """Yozuvdan biometrik ma'lumotni olib tashlaydi va rasm kalitini
    qaytaradi — obyektning o'zini chaqiruvchi COMMIT'dan KEYIN
    finish_erasure() bilan o'chiradi: ombordagi xato baza o'zgarishini
    orqaga qaytarmasligi kerak (app/storage.py, delete_files_quietly)."""
    keys = [k for k in (person.biometric_photo_key, person.biometric_photo_left_key, person.biometric_photo_right_key) if k]
    person.biometric_photo_key = None
    person.biometric_photo_left_key = None
    person.biometric_photo_right_key = None
    person.biometric_embedding = None
    person.biometrics_status = "yoq"
    person.biometrics_confirmed_at = None
    return keys


async def erase_face_samples(db: AsyncSession, person_ids: Sequence[uuid.UUID]) -> list[str]:
    """Asosiy rasmdan TASHQARI saqlangan yuz namunalarini o'chiradi va
    ombordagi rasm kalitlarini qaytaradi (commit'dan keyin finish_erasure).

    * face_gallery_embeddings — kamerada tanilgan kadrlardan olingan
      vektorlar. Bazadagi trigger ularni asosiy vektor o'zgarganda o'zi
      o'chiradi, lekin trigger faqat migratsiya bilan yaratiladi va vektor
      allaqachon bo'sh bo'lsa ishlamaydi — o'chirish kafolati bitta
      joyga (triggerga) bog'lanib qolmasin.
    * unknown_sightings — operator shu odamga biriktirgan kamera kadrlari:
      har birida yuz rasmi (crop_key) va vektori bor, ya'ni bu ham shu
      odamning biometrikasi."""
    ids = list(person_ids)
    if not ids:
        return []
    await db.execute(delete(FaceGalleryEmbedding).where(FaceGalleryEmbedding.student_staff_id.in_(ids)))
    crop_keys = (
        (await db.execute(delete(UnknownSighting).where(UnknownSighting.person_id.in_(ids)).returning(UnknownSighting.crop_key)))
        .scalars()
        .all()
    )
    return [key for key in crop_keys if key]


def unique_keys(keys: Sequence[str | None]) -> list[str]:
    """Bo'sh va takroriy kalitlarsiz: biriktirilgan kamera kadri odamning
    asosiy rasmi ham bo'lishi mumkin (unknown_sightings.assign_to_person)."""
    return list(dict.fromkeys(key for key in keys if key))


async def finish_erasure(photo_keys: Sequence[str | None]) -> int:
    """Commit'dan keyin: rasmlarni ombordan o'chiradi va barcha
    jarayonlardagi yuz keshini yangilatadi — o'chirilgan odam keshda
    qolib, yana bir necha daqiqa tanilib yurmasligi uchun."""
    deleted = await delete_files_quietly(unique_keys(photo_keys))
    await announce_roster_change()
    return deleted


def record_consent(person: StudentStaff, source: str) -> None:
    person.consent_given_at = datetime.now(timezone.utc)
    person.consent_version = settings.consent_version
    person.consent_source = source
    # Yangi rozilik — avtomatik kiritish (HEMIS surati) yana mumkin.
    person.biometrics_opt_out_at = None


def withdraw_consent(person: StudentStaff) -> None:
    person.consent_given_at = None
    person.consent_version = None
    person.consent_source = None


def _days_phrase(days: int, fallback: str) -> str:
    return f"{days} kun" if days > 0 else fallback


def consent_sections() -> list[tuple[str, str]]:
    """Rozilik matni — bo'limlar ro'yxati (sarlavha, matn).

    Matndagi muddatlar sozlamalardan olinadi, ya'ni odam aynan hozir amal
    qilayotgan shartlarni o'qiydi. Matnning MAZMUNI o'zgarsa,
    settings.consent_version oshirilishi kerak — eski versiyaga berilgan
    rozilik "Maxfiylik" sahifasida eskirgan deb ko'rsatiladi."""
    org = settings.org_name
    biometric_days = settings.biometric_retention_days_after_inactive
    biometric_retention = (
        f"o'qish yoki ishlash faoliyatingiz tugaganidan (yozuvingiz faolsizlantirilganidan) so'ng "
        f"{biometric_days} kun ichida avtomatik ravishda o'chiriladi"
        if biometric_days > 0
        else "o'qish yoki ishlash faoliyatingiz tugaganidan so'ng ma'lumotlar operatori tomonidan o'chiriladi"
    )
    snapshot_days = settings.snapshot_retention_days or settings.event_retention_days
    return [
        (
            "Ma'lumotlar operatori",
            f"{org} (\"{settings.org_system_name}\" axborot tizimi). Ma'lumotlaringiz shu muassasa "
            "serverlarida saqlanadi va uning ma'muriyati tomonidan qayta ishlanadi.",
        ),
        (
            "Qanday ma'lumotlar yig'iladi",
            "Ro'yxatdan o'tishda kamera orqali olingan yuzingiz tasviri va undan hisoblanadigan raqamli yuz "
            "shabloni (512 ta sondan iborat vektor — undan rasmni qayta tiklab bo'lmaydi). Shuningdek, "
            "F.I.Sh., JSHSHIR yoki pasport ma'lumotlari, guruh yoki lavozimingiz hamda kameralar sizni "
            "tanigan vaqt va joy (davomat, bino ichidagi tashriflar) qayd etiladi.",
        ),
        (
            "Qayta ishlash maqsadi",
            "Faqat ikki maqsadda: (1) darslar va ish vaqtidagi davomatni avtomatik hisobga olish; "
            "(2) bino xavfsizligini ta'minlash — begona shaxslarni aniqlash va hodisalarni tekshirish. "
            "Ma'lumotlaringiz boshqa maqsadda ishlatilmaydi, sotilmaydi va uchinchi shaxslarga berilmaydi, "
            "qonunda nazarda tutilgan hollar bundan mustasno.",
        ),
        (
            "Saqlash muddati",
            f"Yuz tasviri va shabloni muassasada o'qish yoki ishlash davomida saqlanadi va {biometric_retention}. "
            f"Hodisa suratlari {_days_phrase(snapshot_days, 'hodisa bilan birga')}, turniket orqali "
            f"kirish-chiqish qaydlari {_days_phrase(settings.access_event_retention_days, 'muassasa belgilagan muddat')} "
            "saqlanadi, so'ng avtomatik o'chiriladi.",
        ),
        (
            "Sizning huquqlaringiz",
            "Siz istalgan vaqtda: o'zingiz haqingizdagi ma'lumotlar bilan tanishish va ularning nusxasini olish; "
            "noto'g'ri ma'lumotni tuzattirish; biometrik ma'lumotlaringizni o'chirishni talab qilish; "
            "rozilikni qaytarib olish huquqiga egasiz. Rozilik qaytarib olinganda yuz tasviri va shabloningiz "
            "darhol o'chiriladi, davomatingiz esa boshqa usulda (qo'lda) yuritiladi. Rozilikni qaytarib olish "
            "undan oldin amalga oshirilgan qayta ishlashning qonuniyligiga ta'sir qilmaydi.",
        ),
        (
            "Murojaat qilish tartibi",
            f"Ma'lumotlaringiz nusxasini olish, ularni o'chirish yoki rozilikni qaytarib olish uchun {org} "
            "ma'muriyatiga (Situatsion markazga) shaxsan yoki yozma ariza bilan murojaat qiling.",
        ),
        (
            "Huquqiy asos",
            "O'zbekiston Respublikasining 2019-yil 2-iyuldagi \"Shaxsga doir ma'lumotlar to'g'risida\"gi "
            "O'RQ-547-son Qonuni.",
        ),
    ]


CONSENT_TITLE = "Biometrik shaxsga doir ma'lumotlarni qayta ishlashga rozilik"
CONSENT_STATEMENT = (
    "\"Roziman\" belgisini qo'yish orqali men yuqoridagi shartlar bilan tanishganimni va yuz tasvirim hamda "
    "undan olingan raqamli shablonni ko'rsatilgan maqsadlarda qayta ishlashga ixtiyoriy ravishda rozilik "
    "berishimni tasdiqlayman."
)


async def compute_overview(db: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    biometrics = has_biometrics_clause()
    row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(StudentStaff.active.is_(True)),
                func.count().filter(biometrics),
                func.count().filter(and_(biometrics, StudentStaff.consent_given_at.is_(None))),
                func.count().filter(
                    and_(
                        biometrics,
                        StudentStaff.consent_given_at.is_not(None),
                        or_(
                            StudentStaff.consent_version.is_(None),
                            StudentStaff.consent_version != settings.consent_version,
                        ),
                    )
                ),
                func.count().filter(and_(biometrics, StudentStaff.active.is_(False))),
                func.min(StudentStaff.deactivated_at).filter(and_(biometrics, StudentStaff.active.is_(False))),
            ).select_from(StudentStaff)
        )
    ).one()
    total, active, with_bio, without_consent, outdated, inactive_bio, oldest_deactivation = row

    days = settings.biometric_retention_days_after_inactive
    next_purge_at: datetime | None = None
    overdue = 0
    if days > 0 and inactive_bio:
        # Faolsizlantirish vaqti yozilmagan (masalan to'g'ridan-to'g'ri
        # bazada o'zgartirilgan) yozuvlar uchun hisob hozirdan boshlanadi —
        # cleanup ham ularga birinchi aylanishda vaqt belgisini qo'yadi.
        start = oldest_deactivation or now
        next_purge_at = start + timedelta(days=days)
        overdue = (
            await db.execute(
                select(func.count())
                .select_from(StudentStaff)
                .where(
                    biometrics,
                    StudentStaff.active.is_(False),
                    StudentStaff.deactivated_at < now - timedelta(days=days),
                )
            )
        ).scalar_one()

    snapshot_count, oldest_snapshot = (
        await db.execute(
            select(func.count(), func.min(Event.occurred_at)).where(Event.snapshot_key.is_not(None))
        )
    ).one()

    return {
        "people_total": total,
        "people_active": active,
        "people_inactive": total - active,
        "with_biometrics": with_bio,
        "biometrics_without_consent": without_consent,
        "consent_outdated": outdated,
        "inactive_with_biometrics": inactive_bio,
        "next_biometric_purge_at": next_purge_at,
        "biometric_purge_overdue": overdue,
        "snapshot_count": snapshot_count,
        "oldest_snapshot_at": oldest_snapshot,
        "consent_version": settings.consent_version,
        "consent_required": settings.consent_required_for_enrollment,
        "retention": {
            "event_retention_days": settings.event_retention_days,
            "snapshot_retention_days": settings.snapshot_retention_days,
            "audit_log_retention_days": settings.audit_log_retention_days,
            "biometric_retention_days_after_inactive": settings.biometric_retention_days_after_inactive,
            "access_event_retention_days": settings.access_event_retention_days,
            "notification_log_retention_days": settings.notification_log_retention_days,
            "presence_visit_retention_days": settings.presence_visit_retention_days,
            "unknown_sighting_retention_days": settings.unknown_sighting_retention_days,
            "recording_retention_hours": settings.recording_retention_hours,
            "event_clip_retention_days": settings.event_clip_retention_days,
        },
    }


#: "So'nggi ko'rinishlar" oynasi — maxfiylik sahifasidagi qisqa ko'rsatkich.
RECENT_SIGHTINGS_DAYS = 30


async def biometric_summary(db: AsyncSession, person: StudentStaff) -> dict:
    """Odam haqida qaysi biometrik ma'lumot saqlanayotgani — o'chirishdan
    oldin administrator nimani o'chirayotganini ko'rishi uchun."""
    since = datetime.now(timezone.utc) - timedelta(days=RECENT_SIGHTINGS_DAYS)
    gallery = (
        await db.execute(
            select(func.count()).select_from(FaceGalleryEmbedding).where(FaceGalleryEmbedding.student_staff_id == person.id)
        )
    ).scalar_one()
    linked = (
        await db.execute(select(func.count()).select_from(UnknownSighting).where(UnknownSighting.person_id == person.id))
    ).scalar_one()
    visits, sightings, last_seen = (
        await db.execute(
            select(
                func.count().filter(PresenceVisit.first_seen_at >= since),
                func.coalesce(func.sum(PresenceVisit.sightings).filter(PresenceVisit.first_seen_at >= since), 0),
                func.max(PresenceVisit.last_seen_at),
            ).where(PresenceVisit.student_staff_id == person.id)
        )
    ).one()
    def signed(key: str | None) -> str | None:
        if not key:
            return None
        try:
            return presigned_url(key)
        except Exception:
            return None

    return {
        "photo_url": signed(person.biometric_photo_key),
        # Ro'yxatdan o'tishdagi 3 tomon: chap va o'ng (old — photo_url).
        "photo_left_url": signed(person.biometric_photo_left_key),
        "photo_right_url": signed(person.biometric_photo_right_key),
        "face_template_stored": person.biometric_embedding is not None,
        "biometrics_confirmed_at": person.biometrics_confirmed_at,
        "gallery_samples": gallery,
        "linked_sightings": linked,
        "recent_days": RECENT_SIGHTINGS_DAYS,
        "recent_visits": visits,
        "recent_sightings": int(sightings or 0),
        "last_seen_at": last_seen,
    }


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


async def _limited(db: AsyncSession, stmt) -> tuple[list, bool]:
    rows = (await db.execute(stmt.limit(EXPORT_SECTION_LIMIT + 1))).all()
    return rows[:EXPORT_SECTION_LIMIT], len(rows) > EXPORT_SECTION_LIMIT


async def build_export(db: AsyncSession, person: StudentStaff) -> dict:
    """Sub'ekt so'rovi uchun: tizimda shu odam haqida saqlanayotgan
    HAMMA ma'lumot bitta JSON'da.

    Ataylab chiqarilmaydiganlar: yuz vektorining o'zi (u yuzni tanish
    uchun kalit — faylga chiqarilsa, uni boshqa tizimda ishlatish
    mumkin; buning o'rniga "saqlanadi" degan belgi beriladi) va Telegram
    bog'lash kodi (maxfiy kalit). Ota-onaning Telegram chat
    identifikatori o'rniga faqat "bog'langanmi" belgisi beriladi."""
    now = datetime.now(timezone.utc)
    truncated: list[str] = []

    attendance_rows, cut = await _limited(
        db,
        select(
            AttendanceRecord.date,
            AttendanceRecord.status,
            AttendanceRecord.check_in,
            AttendanceRecord.check_out,
            AttendanceRecord.source,
        )
        .where(AttendanceRecord.student_staff_id == person.id)
        .order_by(AttendanceRecord.date),
    )
    if cut:
        truncated.append("attendance")

    lesson_rows, cut = await _limited(
        db,
        select(
            LessonSession.date,
            LessonSession.subject,
            LessonSession.group_name,
            LessonSession.teacher,
            LessonAttendance.status,
            LessonAttendance.first_seen_at,
            LessonAttendance.last_seen_at,
            LessonAttendance.sightings,
        )
        .join(LessonSession, LessonSession.id == LessonAttendance.lesson_session_id)
        .where(LessonAttendance.student_staff_id == person.id)
        .order_by(LessonSession.date, LessonAttendance.first_seen_at),
    )
    if cut:
        truncated.append("lessonAttendance")

    visit_rows, cut = await _limited(
        db,
        select(
            PresenceVisit.first_seen_at,
            PresenceVisit.last_seen_at,
            PresenceVisit.sightings,
            PresenceVisit.best_similarity,
            Camera.name,
        )
        .outerjoin(Camera, Camera.id == PresenceVisit.camera_id)
        .where(PresenceVisit.student_staff_id == person.id)
        .order_by(PresenceVisit.first_seen_at),
    )
    if cut:
        truncated.append("presenceVisits")

    # Hodisalar odamga faqat ism orqali bog'lanadi (events.person_name —
    # aniqlangan paytdagi nusxa), shuning uchun aniq ism mosligi olinadi.
    event_rows, cut = await _limited(
        db,
        select(
            Event.id,
            Event.occurred_at,
            Event.module_name,
            Event.camera_name,
            Event.building,
            Event.severity,
            Event.status,
            Event.snapshot_key,
        )
        .where(Event.person_name == person.full_name)
        .order_by(Event.occurred_at),
    )
    if cut:
        truncated.append("events")

    access_rows, cut = await _limited(
        db,
        select(
            AccessEvent.occurred_at,
            AccessEvent.direction,
            AccessEvent.granted,
            AccessEvent.card_number,
            AccessDevice.name,
        )
        .outerjoin(AccessDevice, AccessDevice.id == AccessEvent.device_id)
        .where(AccessEvent.student_staff_id == person.id)
        .order_by(AccessEvent.occurred_at),
    )
    if cut:
        truncated.append("accessEvents")

    photo_url = None
    if person.biometric_photo_key:
        try:
            photo_url = presigned_url(person.biometric_photo_key)
        except Exception:
            photo_url = None

    return {
        "generatedAt": now.isoformat(),
        "controller": settings.org_name,
        "legalBasis": "O'zbekiston Respublikasining \"Shaxsga doir ma'lumotlar to'g'risida\"gi O'RQ-547-son Qonuni",
        "profile": {
            "id": str(person.id),
            "fullName": person.full_name,
            "type": person.type,
            "groupOrPosition": person.group_or_position,
            "faculty": person.faculty.name if person.faculty else None,
            "pinfl": person.pinfl,
            "passportSeries": person.passport_series,
            "passportNumber": person.passport_number,
            "hemisId": person.hemis_id,
            "cardNumber": person.card_number,
            "parentPhone": person.parent_phone,
            "parentTelegramLinked": person.parent_telegram_chat_id is not None,
            "parentNotifyEnabled": person.parent_notify_enabled,
            "selfRegistered": person.self_registered,
            "active": person.active,
            "deactivatedAt": _iso(person.deactivated_at),
            "createdAt": _iso(person.created_at),
        },
        "biometrics": {
            "status": person.biometrics_status,
            "confirmedAt": _iso(person.biometrics_confirmed_at),
            "faceTemplateStored": person.biometric_embedding is not None,
            "photoStored": person.biometric_photo_key is not None,
            # Imzolangan havola bir soat amal qiladi.
            "photoUrl": photo_url,
            "scheduledPurgeAt": _iso(biometric_purge_at(person)),
        },
        "consent": {
            "givenAt": _iso(person.consent_given_at),
            "version": person.consent_version,
            "source": person.consent_source,
            "sourceLabel": CONSENT_SOURCE_LABELS.get(person.consent_source or ""),
            "currentVersion": settings.consent_version,
        },
        "attendance": [
            {
                "date": r.date.isoformat(),
                "status": r.status,
                "checkIn": r.check_in.isoformat() if r.check_in else None,
                "checkOut": r.check_out.isoformat() if r.check_out else None,
                "source": r.source,
            }
            for r in attendance_rows
        ],
        "lessonAttendance": [
            {
                "date": r.date.isoformat(),
                "subject": r.subject,
                "group": r.group_name,
                "teacher": r.teacher,
                "status": r.status,
                "firstSeenAt": _iso(r.first_seen_at),
                "lastSeenAt": _iso(r.last_seen_at),
                "sightings": r.sightings,
            }
            for r in lesson_rows
        ],
        "presenceVisits": [
            {
                "camera": r.name,
                "firstSeenAt": _iso(r.first_seen_at),
                "lastSeenAt": _iso(r.last_seen_at),
                "sightings": r.sightings,
                "similarity": round(r.best_similarity, 3) if r.best_similarity is not None else None,
            }
            for r in visit_rows
        ],
        "events": [
            {
                "id": str(r.id),
                "occurredAt": _iso(r.occurred_at),
                "module": r.module_name,
                "camera": r.camera_name,
                "building": r.building,
                "severity": r.severity,
                "status": r.status,
                "hasSnapshot": r.snapshot_key is not None,
            }
            for r in event_rows
        ],
        "accessEvents": [
            {
                "occurredAt": _iso(r.occurred_at),
                "device": r.name,
                "direction": r.direction,
                "granted": r.granted,
                "cardNumber": r.card_number,
            }
            for r in access_rows
        ],
        "truncated": truncated,
    }
