import uuid
from datetime import date as date_type, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class FaceReviewItem(Base):
    """"Kulrang zona" mosligi — odam tekshiruvi navbati.

    Kuchsiz CPU va CCTV burchagida haqiqiy moslik ko'pincha 0.42-0.50
    kosinusda qoladi, ya'ni davomatning qat'iy 0.50 chegarasidan past.
    Bunday moslikni avtomatik qabul qilib bo'lmaydi (boshqa odamga
    davomat yozish xavfi), tashlab yuborish esa odamni "kelmadi" qiladi.
    Shuning uchun u operatorga ko'rsatiladi: kamera kadri va ro'yxat
    rasmi yonma-yon. "Ha, u" — davomat yoziladi VA yuz odamning kamera
    galereyasiga qo'shiladi, ya'ni keyingi safar tizim uni o'zi taniydi.

    Bir odam bir kamerada kun davomida o'nlab kadrga tushadi — ular BITTA
    qatorga yig'iladi (`hits`), rasm eng yirik/eng o'xshash yuzniki.
    """

    __tablename__ = "face_review_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('kutilmoqda', 'tasdiqlandi', 'rad_etildi')",
            name="ck_face_review_items_status",
        ),
        Index("ix_face_review_items_day_status", "day", "status"),
        # Bir odam + kun + kamera = bitta qator (parallel kuzatuvchilar ikkilamasin).
        Index("ux_face_review_items_person_day_camera", "person_id", "day", "camera_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    day: Mapped[date_type] = mapped_column(Date, nullable=False)
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students_staff.id", ondelete="CASCADE"), nullable=False
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    second_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Eng yaxshi yuzning normallashgan vektori (JSON) — tasdiqlanganda galereyaga.
    embedding: Mapped[str] = mapped_column(String, nullable=False)
    crop_key: Mapped[str | None] = mapped_column(String, nullable=True)
    face_px: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="kutilmoqda")
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
