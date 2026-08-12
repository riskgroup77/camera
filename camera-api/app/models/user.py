import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('super-admin', 'admin')", name="ck_users_role"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    login: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    # Ixtiyoriy — mavjud bo'lsa forgot-password havolasi shu manzilga
    # yuboriladi (SMTP sozlangan bo'lsa); bo'lmasa reset havolasi faqat
    # server logiga yoziladi (app/email.py).
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    # JWT'lardagi "ver" claim shu bilan solishtiriladi — parol o'zgarganda yoki
    # admin foydalanuvchini "barcha qurilmalardan chiqarish" kerak bo'lganda shu
    # qiymat oshiriladi, natijada eski JWT'lar avtomatik yaroqsiz bo'lib qoladi
    # (get_current_user tekshiradi — app/dependencies.py).
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def role_display_label(role: str) -> str:
    """Mirrors src/layouts/AdminLayout.tsx ROLE_LABEL."""
    return "Super Admin" if role == "super-admin" else "Admin"


def role_from_display_label(label: str) -> str:
    """Inverse of role_display_label — used when a client sends the
    frontend's display string (AddUserModal's role <select>)."""
    return "super-admin" if label.strip().lower() == "super admin" else "admin"
