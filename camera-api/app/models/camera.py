import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.org import Building


class Camera(Base):
    __tablename__ = "cameras"
    __table_args__ = (CheckConstraint("status IN ('faol', 'nofaol', 'tamirda')", name="ck_cameras_status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String, nullable=False)
    ip: Mapped[str] = mapped_column(String, nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=554)
    rtsp_path: Mapped[str | None] = mapped_column(String, nullable=True)
    # Fernet bilan shifrlangan holda saqlanadi (app/crypto.py) — bu ustunlarga
    # to'g'ridan-to'g'ri emas, faqat encrypt()/decrypt() orqali murojaat qiling.
    # Parol kabi bir tomonlama xeshlash bu yerda ishlamaydi, chunki RTSP
    # handshake uchun qiymat qayta o'qilishi (decrypt qilinishi) shart.
    rtsp_username: Mapped[str | None] = mapped_column(String, nullable=True)
    rtsp_password: Mapped[str | None] = mapped_column(String, nullable=True)

    building_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("buildings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    zone: Mapped[str] = mapped_column(String, nullable=False)
    resolution: Mapped[str] = mapped_column(String, nullable=False)
    fps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="nofaol")
    stream_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Set only by app/jobs/camera_health.py's periodic TCP reachability sweep
    # — deliberately separate from `status` above. `status` is the admin's
    # *intent* ("this camera should be active"); `last_seen_at` is what was
    # actually, recently observed. Without this split, a camera whose cable
    # gets unplugged silently keeps showing "faol"/live everywhere (Monitoring
    # page, admin table) until someone happens to click "Ulanishni tekshirish"
    # — the exact gap this column closes.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    building: Mapped[Building | None] = relationship("Building", lazy="joined")
