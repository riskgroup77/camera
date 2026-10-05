import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class WallView(Base):
    """Videodevorning saqlangan ko'rinishi (setka + kataklardagi kameralar)
    yoki aylanish (tur) sozlamasi.

    Ilgari bular faqat brauzerning localStorage'ida edi: boshqa ish
    joyidagi operator ularni ko'rmasdi. Endi serverda — `shared` bo'lsa
    hamma viewLive egalari ko'radi, o'zgartirish esa faqat egasi yoki
    systemSettings huquqli admin. `payload` — frontend saqlaydigan shakl
    (hozir {layout, tiles}); server uning ichiga aralashmaydi, faqat
    o'lchamini cheklaydi.
    """

    __tablename__ = "wall_views"
    __table_args__ = (
        CheckConstraint("kind IN ('view', 'tour')", name="ck_wall_views_kind"),
        Index("ix_wall_views_owner", "owner_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False, default="view", server_default="view")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
