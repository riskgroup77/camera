import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class PresenceVisit(Base):
    """Odam qaysi kamera oldida qachondan qachongacha bo'lgani — "tashrif".

    Kunlik davomat (AttendanceRecord) har odamga kuniga BITTA qator saqlaydi:
    kelgan va eshikdan oxirgi chiqqan vaqti. U "o'qituvchi 11:00 da qayerda
    edi, darsiga kirdimi" degan savolga javob bera olmaydi. Bu jadval har
    bir yuz tanishni kamera bo'yicha yozadi.

    Har ko'rinish alohida qator emas: kirish kameralari har 6 soniyada
    tekshiriladi va bir odam bir necha daqiqa turganda yuzlab qator hosil
    bo'lardi. Shuning uchun bir kamerada settings.presence_visit_gap_minutes
    dan qisqa tanaffus bilan ketma-ket ko'rinishlar BITTA tashrifga
    birlashtiriladi (first_seen_at .. last_seen_at, sightings — necha marta).

    Darsga bog'liqlik bu yerda saqlanMAYDI — u o'qilganda dars jadvalidan
    hisoblanadi (app/routers/presence.py). Jadval keyin kiritilsa yoki
    o'zgartirilsa, eski tashriflar ham to'g'ri ko'rinadi.
    """

    __tablename__ = "presence_visits"
    __table_args__ = (
        Index("ix_presence_visits_person_last_seen", "student_staff_id", "last_seen_at"),
        Index("ix_presence_visits_camera_last_seen", "camera_id", "last_seen_at"),
        Index("ix_presence_visits_first_seen", "first_seen_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    student_staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students_staff.id", ondelete="CASCADE"), nullable=False
    )
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sightings: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    best_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)

    camera: Mapped["Camera | None"] = relationship("Camera", lazy="joined")
