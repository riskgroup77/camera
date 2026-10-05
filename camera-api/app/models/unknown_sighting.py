import uuid
from datetime import date as date_type, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class UnknownSighting(Base):
    """Kunduzi kamerada ko'ringan NOTANISH yuz — ko'rib chiqish uchun.

    Begona shaxs moduli (#1) kechasi darhol signal beradi. Kunduzi esa
    bunday qila olmaydi: talabalarning ko'pchiligining yuzi hali tizimda
    yo'q, va ular "notanish" bo'lib chiqadi (2026-09 da 640 signalning
    527 tasi shu sabab rad etilgan). Shuning uchun kunduzi notanish yuz
    signal emas, shu jadvalga YOZUV bo'ladi; operator uni ko'rib:

      * "talaba"  — kimligini tanlaydi, yuz o'sha odamga biriktiriladi
                    (keyingi safar kamera uni taniydi — qamrov o'sadi);
      * "begona"  — haqiqiy begona: odatdagi hodisa (#1) yaratiladi;
      * "otkazildi" — ahamiyatsiz (yomon kadr, o'tkinchi).

    Bitta odam kun davomida o'nlab kadrga tushadi — har biri alohida
    qator bo'lsa ro'yxat foydasiz bo'lardi. Shuning uchun bir kunda
    o'xshash yuzlar BIR qatorga yig'iladi (`hits`, `last_seen_at`),
    rasm esa eng yirik yuzniki saqlanadi.
    """

    __tablename__ = "unknown_sightings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('kutilmoqda', 'talaba', 'begona', 'otkazildi')",
            name="ck_unknown_sightings_status",
        ),
        Index("ix_unknown_sightings_day_status", "day", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    day: Mapped[date_type] = mapped_column(Date, nullable=False)
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Normallashgan ArcFace vektori (JSON) — birlashtirish va "talaba"
    # deb belgilanganda odamga biriktirish uchun.
    embedding: Mapped[str] = mapped_column(String, nullable=False)
    crop_key: Mapped[str | None] = mapped_column(String, nullable=True)
    face_px: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Ro'yxatdagi eng yaqin odamga o'xshashlik — past bo'lsa haqiqatan
    # notanish, chegaraga yaqin bo'lsa ehtimol yomon burchakdagi tanish.
    closest_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[str] = mapped_column(String, nullable=False, default="kutilmoqda")
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students_staff.id", ondelete="SET NULL"), nullable=True
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
