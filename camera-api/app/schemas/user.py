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
    role: str  # "Super Admin" | "Admin" — display label, see models.RoleDisplayLabel
    email: str | None = None


class UserCreateIn(CamelModel):
    """Matches the fields collected by AddUserModal.tsx."""

    name: str = Field(min_length=5)
    login: str = Field(min_length=3)
    password: str = Field(min_length=8)
    role: str  # "Super Admin" | "Admin"
    email: EmailStr | None = None


class UserUpdateIn(CamelModel):
    """Matches EditUserModal.tsx — no password field; use the dedicated
    reset-password endpoint for that (keeps the two concerns separate, same
    as StudentStaffUpdateIn / CameraUpdateIn elsewhere in this API)."""

    name: str = Field(min_length=5)
    login: str = Field(min_length=3)
    role: str
    email: EmailStr | None = None


class ResetUserPasswordIn(CamelModel):
    new_password: str = Field(min_length=8)
