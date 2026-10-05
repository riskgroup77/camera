from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.base import CamelModel


class ConsentSectionOut(CamelModel):
    title: str
    body: str


class ConsentTextOut(CamelModel):
    """Ochiq ro'yxatdan o'tish sahifasida ko'rsatiladigan rozilik matni."""

    version: str
    required: bool
    title: str
    controller: str
    sections: list[ConsentSectionOut]
    statement: str


class RetentionSettingsOut(CamelModel):
    """Saqlash muddatlari (kun). 0 — muddat qo'yilmagan / o'chirilmaydi."""

    event_retention_days: int
    snapshot_retention_days: int
    audit_log_retention_days: int
    biometric_retention_days_after_inactive: int
    access_event_retention_days: int
    notification_log_retention_days: int
    presence_visit_retention_days: int = 0
    unknown_sighting_retention_days: int = 0
    # Video arxivi soatda (disk byudjeti bilan o'lchanadi), hodisa klipi kunda.
    recording_retention_hours: int
    event_clip_retention_days: int


class PrivacyOverviewOut(CamelModel):
    people_total: int
    people_active: int
    people_inactive: int
    with_biometrics: int
    biometrics_without_consent: int
    consent_outdated: int
    # Faol emas, lekin biometrikasi hali o'chirilmagan odamlar.
    inactive_with_biometrics: int
    # Ulardan eng yaqin o'chiriladigani qachon (cleanup sikli shu paytdan
    # keyingi birinchi aylanishda o'chiradi). Muddat 0 bo'lsa — None.
    next_biometric_purge_at: datetime | None
    # Muddati allaqachon o'tgan, keyingi tozalashda o'chiriladiganlar.
    biometric_purge_overdue: int
    snapshot_count: int
    oldest_snapshot_at: datetime | None
    consent_version: str
    consent_required: bool
    retention: RetentionSettingsOut


class PrivacyPersonOut(CamelModel):
    id: str
    full_name: str
    type: str
    group_or_position: str
    faculty_name: str | None
    active: bool
    deactivated_at: datetime | None
    has_biometrics: bool
    biometrics_status: str
    consent_given_at: datetime | None
    consent_version: str | None
    consent_source: str | None
    # Rozilik joriy matn versiyasiga berilganmi.
    consent_current: bool
    # Faol emas va biometrikasi bor — qachon avtomatik o'chiriladi.
    biometric_purge_at: datetime | None


PrivacyFilter = Literal["no_consent", "inactive", "with_biometrics"]


class PrivacyPeopleSearchIn(CamelModel):
    """GET /api/privacy/people bilan bir xil, lekin tanada: qidiruv matni
    JSHSHIR bo'lishi mumkin va URL access log/brauzer tarixiga tushmasligi
    kerak (students_staff /search bilan bir xil sabab)."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=500)
    search: str | None = Field(default=None, max_length=100)
    filter: PrivacyFilter | None = None


class ConsentRecordIn(CamelModel):
    source: Literal["qogoz", "admin"]
    note: str | None = Field(default=None, max_length=500)


class PrivacyBiometricsOut(CamelModel):
    """Bitta odam haqida saqlanayotgan biometrik ma'lumot (o'chirishdan oldin)."""

    person: PrivacyPersonOut
    # Asosiy yuz rasmi — imzolangan havola, bir soat amal qiladi.
    photo_url: str | None
    photo_left_url: str | None = None
    photo_right_url: str | None = None
    face_template_stored: bool
    biometrics_confirmed_at: datetime | None
    # Kamerada tanilgan kadrlardan olingan qo'shimcha yuz vektorlari.
    gallery_samples: int
    # Operator shu odamga biriktirgan notanish yuz kadrlari (rasmi bilan).
    linked_sightings: int
    recent_days: int
    recent_visits: int
    recent_sightings: int
    last_seen_at: datetime | None


class ErasureOut(CamelModel):
    person: PrivacyPersonOut
    # Rasm obyekti ombordan o'chdimi (best-effort). False bo'lsa ham
    # bazadagi yuz vektori o'chirilgan — odam endi tanilmaydi.
    photo_deleted: bool
