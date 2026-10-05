import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class FaceGalleryEmbedding(Base):
    """Odamning KAMERADA ko'ringan yuzidan olingan qo'shimcha namuna.

    StudentStaff.biometric_embedding — ro'yxatga olishdagi rasm (ko'pincha
    hujjat rasmi). Kamera kadri boshqa yorug'lik/burchak/o'lchamda bo'lgani
    uchun ArcFace o'xshashligi odamning o'zida ham 0.45-0.60 da qoladi.
    Bu jadval ishonchli tanilgan kadrlardan namunalar saqlaydi
    (app/services/face_gallery.py) va moslik "asl rasm yoki shu
    namunalardan eng yaqini" bo'yicha hisoblanadi.

    `anchor_hash` — namuna qo'shilgan paytdagi asl vektorning xeshi. Odam
    qayta ro'yxatdan o'tsa yoki biometrikasi o'chirilsa, eski namunalar
    avtomatik e'tiborga olinmaydi (va migratsiyadagi trigger ularni
    o'chiradi) — boshqa rasmga bog'langan namuna yangi rasm bilan
    aralashmasligi kerak. Odam o'chirilsa — CASCADE."""

    __tablename__ = "face_gallery_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    student_staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students_staff.id", ondelete="CASCADE"), nullable=False, index=True
    )
    embedding: Mapped[str] = mapped_column(String, nullable=False)
    anchor_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Qo'shilgan paytdagi asl rasm bilan o'xshashlik va yuz balandligi (px).
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    face_px: Mapped[int] = mapped_column(Integer, nullable=False)
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
