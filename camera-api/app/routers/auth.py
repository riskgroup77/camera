import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.config import settings
from app.crypto import decrypt, encrypt
from app.database import get_db
from app.dependencies import CurrentUser, get_current_user
from app.email import send_password_reset_email
from app.models import AuditLog, PasswordResetToken, RevokedToken, User
from app.rate_limit import limiter
from app.schemas.auth import (
    ForgotPasswordIn,
    LoginRequest,
    LoginResponse,
    ResetPasswordIn,
    SessionResponse,
    TwoFactorCodeIn,
    TwoFactorLoginIn,
    TwoFactorSetupOut,
    TwoFactorStatusOut,
)
from app.security import (
    create_access_token,
    create_two_factor_challenge,
    decode_two_factor_challenge,
    hash_password,
    verify_password,
)
from app.services import totp
from app.services.security_checks import forget_default_password_check

logger = logging.getLogger("app.auth")

RESET_TOKEN_TTL_MINUTES = 30

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _mask_login(login: str) -> str:
    """Noto'g'ri urinishdagi login jurnalga to'liq yozilmaydi.

    Odamlar login maydoniga ko'pincha JSHSHIR yoki pasport raqamini
    yozadi (ro'yxatdan o'tish sahifasi bilan adashtirib) — tizim jurnali
    esa ko'p adminlarga ochiq. Mavjud foydalanuvchi logini bo'lsa ham
    brute-force monitoringi uchun boshi va oxiri yetarli."""
    text = (login or "").strip()
    digits = sum(ch.isdigit() for ch in text)
    if len(text) <= 3:
        return "*" * len(text)
    if digits >= 6:
        return f"{text[:2]}{'*' * (len(text) - 4)}{text[-2:]}"
    return f"{text[:3]}{'*' * max(0, len(text) - 3)}"


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    body: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LoginResponse:
    result = await db.execute(select(User).where(User.login == body.login))
    user = result.scalar_one_or_none()
    ip = request.client.host if request.client else "unknown"

    if user is None or not verify_password(user.password_hash, body.password):
        # Muvaffaqiyatsiz urinish ham audit qilinadi — brute-force monitoringi uchun.
        db.add(
            AuditLog(
                user_id=user.id if user else None,
                user_name=_mask_login(body.login),
                action="Noto'g'ri login urinishi",
                module="Autentifikatsiya",
                status="xatolik",
                ip=ip,
            )
        )
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login yoki parol noto'g'ri")

    if user.totp_enabled and user.totp_secret:
        # Parol to'g'ri, lekin bu hali sessiya EMAS: faqat ikkinchi qadam
        # uchun chaqiruv. Rol va ism ham qaytarilmaydi — parolni bilgan
        # begona odam hisob haqida hech narsa bilib olmasin.
        return LoginResponse(
            two_factor_required=True,
            challenge=create_two_factor_challenge(str(user.id), user.token_version),
        )

    return await _complete_login(db, user, ip)


async def _complete_login(db: AsyncSession, user: User, ip: str) -> LoginResponse:
    """Muvaffaqiyatli kirishni yakunlaydi: audit, last_login va token."""
    user.last_login_at = datetime.now(timezone.utc)
    db.add(
        AuditLog(
            user_id=user.id,
            user_name=user.full_name,
            action="Tizimga kirish",
            module="Autentifikatsiya",
            status="muvaffaqiyatli",
            ip=ip,
        )
    )
    await db.commit()

    token = create_access_token(str(user.id), user.role, user.token_version)
    return LoginResponse(token=token, role=user.role, user_name=user.full_name)


_CHALLENGE_EXPIRED = "Tasdiqlash muddati tugagan — qaytadan kiring"


def _totp_secret(user: User) -> str:
    try:
        return decrypt(user.totp_secret or "")
    except ValueError:
        # ENCRYPTION_KEY almashgan: kodni tekshirib bo'lmaydi. Bu holatda
        # 2FA'ni chetlab o'tish YO'Q — administrator uni bekor qiladi.
        logger.error("2FA sirini ochib bo'lmadi", extra={"user_id": str(user.id)})
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Ikki bosqichli kirish kalitini o'qib bo'lmadi — administratorga murojaat qiling",
        ) from None


@router.post("/2fa/kirish", response_model=LoginResponse)
@limiter.limit("5/minute")
async def two_factor_login(
    request: Request,
    body: TwoFactorLoginIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LoginResponse:
    """Ikkinchi qadam: parol bilan olingan chaqiruv + ilovadagi 6 xonali kod.

    Chaqiruv bir martalik: muvaffaqiyatli kirishdan keyin uning jti'si
    revoked_tokens'ga yoziladi (ikkinchi marta ishlatib bo'lmaydi). Kod
    ham bir martalik — totp_last_step. Noto'g'ri kod chaqiruvni
    kuydirmaydi (odam raqamni adashtirib yozishi mumkin), lekin urinishlar
    login kabi IP bo'yicha 5/daqiqa bilan cheklangan."""
    ip = request.client.host if request.client else "unknown"
    try:
        challenge = decode_two_factor_challenge(body.challenge)
        jti = uuid.UUID(challenge.jti)
        user_id = uuid.UUID(challenge.user_id)
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _CHALLENGE_EXPIRED) from None

    if await db.get(RevokedToken, jti) is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _CHALLENGE_EXPIRED)

    # FOR UPDATE: bir xil kod bilan parallel ikki so'rov totp_last_step'ni
    # bir vaqtda o'qib, ikkalasi ham o'tib ketmasin.
    user = (
        await db.execute(select(User).where(User.id == user_id).with_for_update())
    ).scalar_one_or_none()
    # token_version: chaqiruv olingandan keyin parol almashtirilgan yoki
    # hisob bloklangan bo'lsa — eski parol bilan olingan chaqiruv yaroqsiz.
    if (
        user is None
        or user.token_version != challenge.token_version
        or not user.totp_enabled
        or not user.totp_secret
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _CHALLENGE_EXPIRED)

    step = totp.verify(_totp_secret(user), body.code, last_step=user.totp_last_step)
    if step is None:
        db.add(
            AuditLog(
                user_id=user.id,
                user_name=user.full_name,
                action="Noto'g'ri 2FA kodi",
                module="Autentifikatsiya",
                status="xatolik",
                ip=ip,
            )
        )
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Kod noto'g'ri yoki eskirgan")

    user.totp_last_step = step
    db.add(RevokedToken(jti=jti, expires_at=challenge.expires_at))
    try:
        await db.flush()
    except IntegrityError:
        # Xuddi shu chaqiruv parallel so'rovda allaqachon ishlatildi.
        await db.rollback()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _CHALLENGE_EXPIRED) from None
    return await _complete_login(db, user, ip)


async def _load_self(db: AsyncSession, current_user: CurrentUser) -> User:
    user = (
        await db.execute(select(User).where(User.id == uuid.UUID(current_user.id)).with_for_update())
    ).scalar_one_or_none()
    if user is None:  # pragma: no cover — get_current_user allaqachon tekshirgan
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessiya tugatilgan — qayta kiring")
    return user


def _status_out(user: User) -> TwoFactorStatusOut:
    return TwoFactorStatusOut(
        enabled=bool(user.totp_enabled),
        confirmed_at=user.totp_confirmed_at.isoformat() if user.totp_confirmed_at else None,
    )


def clear_two_factor(user: User) -> None:
    """2FA'ni butunlay olib tashlaydi (o'zi o'chirganda va admin bekor qilganda)."""
    user.totp_secret = None
    user.totp_enabled = False
    user.totp_confirmed_at = None
    user.totp_last_step = None


@router.get("/2fa", response_model=TwoFactorStatusOut)
async def two_factor_status(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> TwoFactorStatusOut:
    user = await db.get(User, uuid.UUID(current_user.id))
    if user is None:  # pragma: no cover
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessiya tugatilgan — qayta kiring")
    return _status_out(user)


@router.post("/2fa/boshlash", response_model=TwoFactorSetupOut)
@limiter.limit("5/minute")
async def two_factor_begin(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> TwoFactorSetupOut:
    """Yangi sir yaratadi (hali YOQMAYDI). Qayta chaqirilsa eski
    tasdiqlanmagan sir almashtiriladi — QR yo'qolgan bo'lsa shu yetarli.

    Yoqilgan 2FA ustidan qayta boshlash taqiqlangan: aks holda ochiq
    qolgan sessiyani egallagan odam sirni jimgina almashtirib, egasini
    tizimdan qulflab qo'yardi. Avval kod bilan o'chirish kerak."""
    user = await _load_self(db, current_user)
    if user.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ikki bosqichli kirish allaqachon yoqilgan")
    secret = totp.generate_secret()
    user.totp_secret = encrypt(secret)
    user.totp_last_step = None
    await log_action(db, request, current_user.id, "2FA yoqishni boshladi", "Autentifikatsiya")
    await db.commit()
    return TwoFactorSetupOut(
        otpauth_uri=totp.provisioning_uri(secret, user.login, settings.org_name),
        secret=secret,
    )


@router.post("/2fa/tasdiqlash", response_model=TwoFactorStatusOut)
@limiter.limit("5/minute")
async def two_factor_confirm(
    request: Request,
    body: TwoFactorCodeIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> TwoFactorStatusOut:
    """Ilovadagi birinchi kod bilan yoqadi — telefon sirni to'g'ri
    saqlaganini shu isbotlaydi (aks holda odam o'zini qulflab qo'yardi)."""
    user = await _load_self(db, current_user)
    if user.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ikki bosqichli kirish allaqachon yoqilgan")
    if not user.totp_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Avval QR-kodni oling")
    step = totp.verify(_totp_secret(user), body.code, last_step=user.totp_last_step)
    if step is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kod noto'g'ri yoki eskirgan")
    user.totp_enabled = True
    user.totp_confirmed_at = datetime.now(timezone.utc)
    user.totp_last_step = step
    await log_action(db, request, current_user.id, "Ikki bosqichli kirishni yoqdi", "Autentifikatsiya")
    await db.commit()
    return _status_out(user)


@router.post("/2fa/ochirish", response_model=TwoFactorStatusOut)
@limiter.limit("5/minute")
async def two_factor_disable(
    request: Request,
    body: TwoFactorCodeIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> TwoFactorStatusOut:
    """O'zi o'chirish — amaldagi kod bilan. Ochiq qolgan sessiyaning
    o'zi yetarli emas: aks holda kompyuterni bir daqiqa qarovsiz
    qoldirish himoyani butunlay olib tashlashga yetardi. Telefon
    yo'qolgan bo'lsa — administrator bekor qiladi
    (POST /api/users/{id}/2fa/bekor)."""
    user = await _load_self(db, current_user)
    if not user.totp_enabled or not user.totp_secret:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ikki bosqichli kirish yoqilmagan")
    step = totp.verify(_totp_secret(user), body.code, last_step=user.totp_last_step)
    if step is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kod noto'g'ri yoki eskirgan")
    clear_two_factor(user)
    await log_action(db, request, current_user.id, "Ikki bosqichli kirishni o'chirdi", "Autentifikatsiya")
    await db.commit()
    return _status_out(user)


@router.get("/me", response_model=SessionResponse)
async def me(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> SessionResponse:
    """Sessiyaning hozirgi haqiqati: rol va ism BAZADAN.

    get_current_user allaqachon tokenni, blocklistni va token_version'ni
    tekshiradi — ya'ni chiqib ketgan, paroli almashtirilgan yoki o'chirilgan
    hisob bu yerda 401 oladi. Mijoz shu javob bilan localStorage'dagi
    (kirish paytida muzlatilgan) rolni yangilaydi: lavozimi o'zgargan odam
    JWT muddati tugashini kutmasdan to'g'ri menyuni ko'radi."""
    user = await db.get(User, current_user.id)
    if user is None:  # pragma: no cover — get_current_user allaqachon tekshirgan
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessiya tugatilgan — qayta kiring")
    return SessionResponse(role=user.role, user_name=user.full_name, two_factor_required=current_user.needs_2fa_setup)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    """Real server-side revocation — the token's own jti is blocklisted until
    its natural expiry, so a copy of it (stolen, cached, whatever) stops
    working immediately instead of staying valid for the rest of its TTL."""
    db.add(RevokedToken(jti=uuid.UUID(current_user.jti), expires_at=current_user.expires_at))
    await log_action(db, request, current_user.id, "Tizimdan chiqdi", "Autentifikatsiya")
    await db.commit()


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def forgot_password(
    request: Request,
    body: ForgotPasswordIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Har doim bir xil (bo'sh, 204) javob qaytaradi — hisob mavjudligini
    yoki unga email biriktirilganini oshkor qilmaslik uchun. Haqiqiy ish
    (token yaratish, email/log) faqat hisob topilganda ichkarida bajariladi."""
    result = await db.execute(select(User).where(User.login == body.login))
    user = result.scalar_one_or_none()
    if user is None:
        return

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)
    db.add(PasswordResetToken(user_id=user.id, token_hash=token_hash, expires_at=expires_at))
    await log_action(db, request, str(user.id), "Parolni tiklashni so'radi", "Autentifikatsiya")
    await db.commit()

    reset_link = f"{settings.frontend_base_url}/parolni-tiklash?token={raw_token}"
    if user.email:
        send_password_reset_email(user.email, user.full_name, reset_link)
    else:
        # HAVOLANING O'ZI JURNALGA YOZILMAYDI. Token — bir martalik parol
        # tiklash kaliti: jurnalni o'qiy oladigan (yoki jurnal yig'uvchi
        # tizimga ulangan) har kim shu havola bilan hisobni egallab olardi.
        # Email yo'q bo'lsa to'g'ri yo'l — administrator orqali tiklash
        # (POST /api/users/{id}/reset-password).
        logger.warning(
            "parolni tiklash so'raldi, lekin foydalanuvchida email manzili yo'q — havola yuborilmadi",
            extra={"user_id": str(user.id)},
        )


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    body: ResetPasswordIn,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    token_hash = hashlib.sha256(body.token.encode("utf-8")).hexdigest()
    result = await db.execute(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))
    reset_token = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if reset_token is None or reset_token.used_at is not None or reset_token.expires_at < now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Havola yaroqsiz yoki muddati tugagan")

    user = await db.get(User, reset_token.user_id)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Havola yaroqsiz yoki muddati tugagan")

    user.password_hash = hash_password(body.new_password)
    forget_default_password_check()
    # Parol o'zgarganda barcha eski sessiyalar (barcha qurilmalardagi JWT'lar)
    # avtomatik yaroqsiz bo'ladi — get_current_user token_version'ni solishtiradi.
    user.token_version += 1
    reset_token.used_at = now
    # Shu foydalanuvchining BOSHQA ishlatilmagan tiklash havolalari ham
    # bekor qilinadi: bir necha marta "parolni unutdim" bosilgan bo'lsa,
    # eski email'dagi havola parol allaqachon almashtirilganidan keyin
    # ham ishlab turardi (hisobni qayta egallash yo'li).
    await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now)
    )

    await log_action(db, request, str(user.id), "Parolni muvaffaqiyatli tikladi", "Autentifikatsiya")
    await db.commit()
