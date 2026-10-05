import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('super-admin', 'admin', 'kamera-masuli')", name="ck_users_role"),
    )

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
    # Shaxsiy bildirishnomalar (hodisa tayinlanganda va h.k.) —
    # app/services/notifications. Telegram botga "/start <kod>" yuborib bog'lanadi.
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String, nullable=True)
    telegram_link_code: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    telegram_link_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Ikki bosqichli kirish (TOTP, app/services/totp.py). Sir Fernet bilan
    # shifrlangan (app/crypto.py): baza nusxasi (backup) sizib chiqsa ham
    # undan kodlarni yasab bo'lmasin. totp_secret bor-u totp_enabled=False —
    # yoqish boshlangan, lekin hali kod bilan tasdiqlanmagan holat.
    totp_secret: Mapped[str | None] = mapped_column(String, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    totp_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Oxirgi qabul qilingan 30 soniyalik qadam: bitta kodni (ekrandan
    # ko'rib olingan yoki tarmoqda ushlangan) oynaning qolgan ~90 soniyasida
    # ikkinchi marta ishlatib bo'lmasin.
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Bino doirasi (app/services/access_scope.py): NULL yoki bo'sh ro'yxat —
    # barcha binolar. Aks holda foydalanuvchi faqat shu binolardagi
    # kameralar, ularning hodisalari va arxivini ko'radi. Super Admin'ga
    # qo'llanmaydi.
    allowed_building_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)


# Rol qiymati <-> ekranda ko'rinadigan nomi. src/layouts/AdminLayout.tsx
# dagi ROLE_LABEL bilan bir xil bo'lishi shart.
ROLE_LABELS = {
    "super-admin": "Super Admin",
    "admin": "Admin",
    "kamera-masuli": "Kamera mas'uli",
}


def _normalize_label(label: str) -> str:
    """Tutuq belgisi klaviaturaga qarab har xil yoziladi (mas'uli,
    mas’uli, masʻuli) — solishtirishdan oldin bir xilga keltiramiz."""
    text = label.strip().lower()
    for ch in "‘’`ʻʼ´":
        text = text.replace(ch, "'")
    return text


def role_display_label(role: str) -> str:
    """Mirrors src/layouts/AdminLayout.tsx ROLE_LABEL."""
    return ROLE_LABELS.get(role, ROLE_LABELS["admin"])


def role_from_display_label(label: str) -> str:
    """Inverse of role_display_label — used when a client sends the
    frontend's display string (AddUserModal's role <select>).

    Noma'lum qiymat "admin" ga tushadi: eng kam imtiyozli EMAS, lekin
    mavjud xatti-harakat shunday edi va uni jimgina o'zgartirish
    foydalanuvchi yaratishni buzishi mumkin."""
    normalized = _normalize_label(label)
    for role, display in ROLE_LABELS.items():
        if normalized == _normalize_label(display):
            return role
    return "admin"
