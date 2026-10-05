from pydantic import Field

from app.schemas.base import CamelModel


class LoginRequest(CamelModel):
    login: str
    password: str


class LoginResponse(CamelModel):
    """Parol to'g'ri bo'lsa ikki holat:

    * 2FA o'chiq — token, role, user_name to'ldirilgan (odatdagi sessiya);
    * 2FA yoqilgan — two_factor_required=True va `challenge` (5 daqiqalik,
      bir martalik, FAQAT /api/auth/2fa/kirish uchun). token/role/user_name
      bu holda BO'SH: parolning o'zi hali sessiya bermaydi."""

    token: str | None = None
    role: str | None = None  # "super-admin" | "admin" — always derived server-side, never trusted from the client
    user_name: str | None = None
    two_factor_required: bool = False
    challenge: str | None = None


class SessionResponse(CamelModel):
    """GET /api/auth/me — joriy sessiya haqiqati.

    Rol tokenda emas, BAZADA: mijoz uni kirish paytida olib localStorage'da
    12 soat saqlaydi, lekin admin rolni shu orada o'zgartirishi mumkin.
    Mijoz vaqti-vaqti bilan shu yerdan so'rab, menyusini haqiqatga
    moslaydi (yoki 401 olib, sessiyani tozalaydi)."""

    role: str
    user_name: str
    # Administrator, 2FA hali yoqilmagan — mijoz sozlash oynasini majburan ochadi.
    two_factor_required: bool = False


class ForgotPasswordIn(CamelModel):
    login: str


class ResetPasswordIn(CamelModel):
    token: str
    new_password: str = Field(min_length=8)


class TwoFactorLoginIn(CamelModel):
    challenge: str = Field(min_length=1, max_length=2048)
    code: str = Field(min_length=1, max_length=16)


class TwoFactorCodeIn(CamelModel):
    code: str = Field(min_length=1, max_length=16)


class TwoFactorSetupOut(CamelModel):
    """Yoqishni boshlash: QR shu URI'dan chiziladi; `secret` — QR'ni
    skanerlay olmaganlar uchun qo'lda kiritiladigan kalit."""

    otpauth_uri: str
    secret: str


class TwoFactorStatusOut(CamelModel):
    enabled: bool
    confirmed_at: str | None = None
