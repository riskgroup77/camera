import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class CameraOutage(Base):
    """Kameraning bitta uzilishi: qachon javob bermay qoldi, qachon qaytdi.

    last_seen_at faqat "hozir" haqida gapiradi — kecha kamera 3 marta
    o'chib-yonganini u eslab qolmaydi. Uptime foizi va uzilishlar tarixi
    (tizim sahifasidagi "Kameralar" bo'limi) uchun har bir uzilish alohida
    qator bo'lib saqlanadi. Yozuvchi — app/jobs/camera_health.py.

    ended_at NULL — uzilish hali davom etmoqda.
    """

    __tablename__ = "camera_outages"
    __table_args__ = (Index("ix_camera_outages_camera_started", "camera_id", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # "tarmoq" — TCP javob yo'q; "xato" — tekshiruvning o'zi yiqildi.
    reason: Mapped[str] = mapped_column(String(32), nullable=False, default="tarmoq")
