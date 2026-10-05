from pydantic import EmailStr, Field

from app.schemas.base import CamelModel


class AdminUserOut(CamelModel):
    """Matches src/types/index.ts `AdminUser` (email is an additive, optional
    extra used by the edit form — absent/None renders as empty client-side)."""

    id: str
    name: str
    login: str
    initials: str
    last_login: str
    # Oxirgi kirishdan beri o'tgan kun (hech kirmagan — None).
    last_login_days: int | None = None
    role: str  # "Super Admin" | "Admin" — display label, see models.RoleDisplayLabel
    email: str | None = None
    # Shaxsiy bildirishnomalar uchun (Telegram bog'lanmagan bo'lsa SMS).
    phone: str | None = None
    telegram_linked: bool = False
    # Ikki bosqichli kirish yoqilganmi (sirning o'zi hech qachon qaytarilmaydi).
    two_factor_enabled: bool = False
    # Bino doirasi: bo'sh ro'yxat — barcha binolar.
    allowed_building_ids: list[str] = []


class UserCreateIn(CamelModel):
    """Matches the fields collected by AddUserModal.tsx."""

    name: str = Field(min_length=5)
    login: str = Field(min_length=3)
    password: str = Field(min_length=8)
    role: str  # "Super Admin" | "Admin"
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)


class UserUpdateIn(CamelModel):
    """Matches EditUserModal.tsx — no password field; use the dedicated
    reset-password endpoint for that (keeps the two concerns separate, same
    as StudentStaffUpdateIn / CameraUpdateIn elsewhere in this API)."""

    name: str = Field(min_length=5)
    login: str = Field(min_length=3)
    role: str
    email: EmailStr | None = None
    # Yuborilmasa — o'zgarmaydi; bo'sh satr — o'chiriladi.
    phone: str | None = Field(default=None, max_length=32)


class ResetUserPasswordIn(CamelModel):
    new_password: str = Field(min_length=8)


class UserBuildingScopeIn(CamelModel):
    """Bo'sh ro'yxat — cheklov yo'q (barcha binolar)."""

    building_ids: list[str] = Field(default_factory=list, max_length=200)
