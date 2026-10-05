import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, func, true
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReportSchedule(Base):
    """Avtomatik hisobot: har hafta (dushanba) yoki har oy (1-sana) 08:00 dan
    keyin oldingi davr hisoboti Excel fayl bo'lib Telegram chatlarga
    yuboriladi (app/jobs/report_schedules.py).

    last_sent_at — davr uchun bir martalik yuborish belgisi: server qayta
    ishga tushsa yoki sikl har 5 daqiqada aylansa ham hisobot takrorlanmaydi."""

    __tablename__ = "report_schedules"
    __table_args__ = (
        CheckConstraint("kind IN ('kunlik', 'haftalik', 'oylik')", name="ck_report_schedules_kind"),
        CheckConstraint(
            "report IN ('kpi', 'davomat_xodim', 'davomat_talaba', 'tabel_xodim', 'tabel_talaba', 'jadval_davomat')",
            name="ck_report_schedules_report",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    report: Mapped[str] = mapped_column(String, nullable=False)
    telegram_chat_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
