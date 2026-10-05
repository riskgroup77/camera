"""Platforma kengaytmasi (2026-09-19): bildirishnomalar, hodisa ish
jarayoni, qavat rejalari, turniket/kirish nazorati va integratsiyalar.

Mavjud jadvallarga qo'shilgan ustunlar o'z modellarida (camera.py,
event.py, student_staff.py, user.py, attendance.py) — bu yerda faqat
yangi jadvallar. Hammasi bitta migratsiyada: s1a2b3c4d5e6.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class NotificationRule(Base):
    """Kimga, qaysi kanal orqali, qanday signal yuboriladi.

    kinds: 'event' (AI hodisasi), 'event_overdue' (SLA o'tgan hodisa),
    'camera_offline', 'camera_online', 'access_denied', 'system'.
    Filtrlar (module_codes, building_ids, min_severity) bo'sh (NULL) —
    cheklov yo'q.
    """

    __tablename__ = "notification_rules"
    __table_args__ = (
        CheckConstraint("channel IN ('telegram', 'sms')", name="ck_notification_rules_channel"),
        CheckConstraint(
            "min_severity IS NULL OR min_severity IN ('past', 'o''rta', 'yuqori')",
            name="ck_notification_rules_min_severity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    channel: Mapped[str] = mapped_column(String, nullable=False)
    # Telegram chat_id lar yoki telefon raqamlar (+998XXXXXXXXX).
    recipients: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    kinds: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    module_codes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    building_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    min_severity: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationLog(Base):
    """Har bir yuborilgan (yoki yuborilmagan) xabar — tekshirish va
    "nega xabar kelmadi?" savoliga javob uchun. cleanup_loop tozalaydi."""

    __tablename__ = "notification_log"
    __table_args__ = (
        CheckConstraint("status IN ('yuborildi', 'xato', 'otkazildi')", name="ck_notification_log_status"),
        Index("ix_notification_log_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    channel: Mapped[str] = mapped_column(String, nullable=False)
    recipient: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Nimaga tegishli: hodisa id, kamera id, odam id va h.k.
    ref_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Qayta yuborilgan (bir marta) — xato yozuv cheksiz qayta yuborilmasin.
    resent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EventComment(Base):
    """Hodisa tarixi: izohlar, holat o'zgarishi, tayinlash."""

    __tablename__ = "event_comments"
    __table_args__ = (
        CheckConstraint("kind IN ('izoh', 'holat', 'tayinlash')", name="ck_event_comments_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    author_name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="izoh")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FloorPlan(Base):
    """Bino qavatining rasmi (PNG/JPG) — kameralar uning ustiga nisbiy
    koordinatalar (cameras.plan_x/plan_y, 0..1) bilan joylanadi."""

    __tablename__ = "floor_plans"
    __table_args__ = (UniqueConstraint("building_id", "floor", name="uq_floor_plans_building_floor"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    building_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    floor: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False, default="")
    image_key: Mapped[str] = mapped_column(String, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Rasm almashtirilgan vaqt — xaritada "reja yangilangan" ko'rsatiladi.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AccessDevice(Base):
    """Turniket / yuz terminali / kirish nazorati kontrolleri.

    kind='hikvision' — ISAPI orqali AcsEvent so'rab turiladi (poll).
    kind='zkteco' — ZKTeco ADMS/push yoki oraliq dastur webhook orqali.
    kind='webhook' — qurilma (yoki oraliq dastur) o'zi POST qiladi,
    /api/access/webhook/{id} ga X-Api-Key bilan.
    Login/parol Fernet bilan shifrlanadi (app/crypto.py), api_key esa
    xeshlanadi — qayta o'qish kerak emas.
    """

    __tablename__ = "access_devices"
    __table_args__ = (
        CheckConstraint("kind IN ('hikvision', 'zkteco', 'webhook')", name="ck_access_devices_kind"),
        CheckConstraint("direction IN ('kirish', 'chiqish', 'ikkalasi')", name="ck_access_devices_direction"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    ip: Mapped[str | None] = mapped_column(String, nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    password: Mapped[str | None] = mapped_column(String, nullable=True)
    api_key_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    direction: Mapped[str] = mapped_column(String, nullable=False, default="kirish")
    building_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("buildings.id", ondelete="SET NULL"), nullable=True
    )
    # Davomatga yozilsinmi (aks holda faqat jurnal).
    marks_attendance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Qurilmaning oxirgi o'qilgan hodisasi (ISAPI serialNo va h.k.).
    poll_cursor: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AccessEvent(Base):
    __tablename__ = "access_events"
    __table_args__ = (
        UniqueConstraint("device_id", "external_id", name="uq_access_events_device_external"),
        Index("ix_access_events_occurred", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("access_devices.id", ondelete="SET NULL"), nullable=True, index=True
    )
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    card_number: Mapped[str | None] = mapped_column(String, nullable=True)
    employee_no: Mapped[str | None] = mapped_column(String, nullable=True)
    student_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students_staff.id", ondelete="SET NULL"), nullable=True, index=True
    )
    direction: Mapped[str | None] = mapped_column(String, nullable=True)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IntegrationSyncRun(Base):
    """HEMIS (va keyingi tashqi tizimlar) sinxronlash tarixi."""

    __tablename__ = "integration_sync_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ishlamoqda', 'muvaffaqiyatli', 'xato')", name="ck_integration_sync_runs_status"
        ),
        Index("ix_integration_sync_runs_source_started", "source", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    source: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ishlamoqda")
    stats: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String, nullable=False, default="tizim")
