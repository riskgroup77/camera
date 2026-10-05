import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ModuleCameraSuppression(Base):
    """Operatorlar qayta-qayta rad etgan kamera × modul juftligi.

    app/jobs/module_suppression.py yaratadi. Faol yozuv (restored_at IS
    NULL) shu kamerada shu modul ishini to'xtatadi — qarang
    app/jobs/module_status.camera_allows_module. Kameraning o'z modul
    ro'yxati (excluded_module_codes) adminning qarori bo'lib qoladi va
    bunga aralashtirilmaydi: avtomatik o'chirish alohida ko'rinib turishi
    va bir tugma bilan qaytarilishi kerak."""

    __tablename__ = "module_camera_suppressions"
    __table_args__ = (Index("ix_module_suppressions_lookup", "camera_id", "module_code", "restored_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False
    )
    module_code: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    restored_by: Mapped[str | None] = mapped_column(String, nullable=True)
