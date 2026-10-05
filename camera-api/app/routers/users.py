import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, get_current_user, require_permission
from app.models import Building, Permission, User
from app.models.user import role_display_label, role_from_display_label
from app.pagination import Page, PageParams, build_page, paginate
from app.rate_limit import limiter
from app.routers.auth import clear_two_factor
from app.schemas.permission import PermissionEntryOut, PermissionToggleIn
from app.schemas.user import AdminUserOut, ResetUserPasswordIn, UserBuildingScopeIn, UserCreateIn, UserUpdateIn
from app.security import hash_password
from app.services.access_scope import allowed_buildings, is_restricted
from app.services.notifications.sms import normalize_phone
from app.services.security_checks import forget_default_password_check
from app.timezone import to_local
from app.utils import compute_initials

router = APIRouter(tags=["users"])


#: Shuncha kundan beri kirmagan hisob — "eski" (o'chirish yoki bloklash nomzodi).
STALE_LOGIN_DAYS = 90


def _format_last_login(user: User) -> str:
    if user.last_login_at is None:
        return "Hali kirmagan"
    return to_local(user.last_login_at).strftime("%Y-%m-%d %H:%M")


def _to_admin_user_out(user: User) -> AdminUserOut:
    return AdminUserOut(
        id=str(user.id),
        name=user.full_name,
        login=user.login,
        initials=compute_initials(user.full_name),
        last_login=_format_last_login(user),
        last_login_days=(
            (datetime.now(timezone.utc) - user.last_login_at).days if user.last_login_at is not None else None
        ),
        role=role_display_label(user.role),
        email=user.email,
        phone=user.phone,
        telegram_linked=bool(user.telegram_chat_id),
        two_factor_enabled=bool(user.totp_enabled),
        allowed_building_ids=[str(b) for b in (user.allowed_building_ids or [])],
    )


def _resolve_role(requested_label: str, current_user: CurrentUser) -> str:
    """Tanlangan rolni qaytaradi, lekin imtiyozni OSHIRISHGA yo'l qo'ymaydi.

    `manageRoles` — sozlanadigan huquq: Super Admin uni "Admin" ustuniga
    yoqib qo'yishi mumkin. Shu holatda tekshiruvsiz admin o'zini yoki
    boshqa hisobni Super Admin qilib qo'yib, huquqlar matritsasini
    (faqat Super Admin tahrirlaydigan) o'z qo'liga olib olardi. Super
    Admin rolini faqat Super Admin bera oladi."""
    role = role_from_display_label(requested_label)
    if role == "super-admin" and current_user.role != "super-admin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Super Admin rolini faqat Super Admin tayinlay oladi"
        )
    return role


def _guard_super_admin_target(user: User, current_user: CurrentUser) -> None:
    """Super Admin hisobiga faqat Super Admin tegishi mumkin.

    Aks holda `manageRoles` berilgan admin Super Admin'ning parolini
    tiklab (yoki hisobini o'chirib) uning o'rnini egallab olardi — ya'ni
    rolni ko'tarish taqiqi aylanib o'tilardi."""
    if user.role == "super-admin" and current_user.role != "super-admin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Super Admin hisobini faqat Super Admin o'zgartira oladi"
        )
    _guard_scope_target(user, current_user)


def _guard_scope_target(user: User, current_user: CurrentUser) -> None:
    """Bino doirasi cheklangan boshqaruvchi faqat O'Z doirasi ichidagi
    hisoblarga tegadi.

    Aks holda bitta binoga cheklangan admin cheklanmagan hamkasbining
    parolini tiklab (yoki 2FA'sini olib tashlab) uning nomidan kirib,
    butun kampusni ko'rib olardi — doira qog'ozda qolardi."""
    mine = allowed_buildings(current_user)
    if mine is None:
        return
    theirs = allowed_buildings(user)
    if theirs is None or not theirs <= mine:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Bu hisob sizning bino doirangizdan kengroq — uni o'zgartira olmaysiz"
        )


async def _forbid_last_super_admin_demotion(db: AsyncSession, user: User, new_role: str) -> None:
    """Oxirgi Super Admin'ni pasaytirib bo'lmaydi — aks holda huquqlar
    matritsasini o'zgartira oladigan hech kim qolmaydi (o'chirishda shu
    tekshiruv bor edi, tahrirlashda esa yo'q edi)."""
    if user.role != "super-admin" or new_role == "super-admin":
        return
    others = (
        await db.execute(select(User.id).where(User.role == "super-admin", User.id != user.id))
    ).scalars().first()
    if others is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Oxirgi Super Admin rolini o'zgartirib bo'lmaydi")


def _clean_phone(value: str | None) -> str | None:
    """Bo'sh — o'chiriladi; aks holda +998XXXXXXXXX (SMS shu ko'rinishni kutadi)."""
    if value is None or not value.strip():
        return None
    phone = normalize_phone(value)
    if phone is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Telefon raqami noto'g'ri (masalan: +998 90 123 45 67)")
    return phone


@router.get("/api/users", response_model=Page[AdminUserOut])
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission("manageRoles"))],
    page_params: Annotated[PageParams, Depends()],
    search: Annotated[str | None, Query(max_length=100)] = None,
    role: Annotated[str | None, Query(max_length=40)] = None,
    xavf: Annotated[Literal["kirmagan", "eski", "2fa_yoq"] | None, Query()] = None,
) -> Page[AdminUserOut]:
    """Foydalanuvchilar: ism/login qidiruvi, rol va xavf filtri —
    hech kirmagan, 90 kundan beri kirmagan, 2FA siz administrator."""
    stmt = select(User).order_by(User.created_at)
    if search and search.strip():
        term = f"%{search.strip()}%"
        stmt = stmt.where(or_(User.full_name.ilike(term), User.login.ilike(term)))
    if role:
        stmt = stmt.where(User.role == role)
    if xavf == "kirmagan":
        stmt = stmt.where(User.last_login_at.is_(None))
    elif xavf == "eski":
        stmt = stmt.where(User.last_login_at < datetime.now(timezone.utc) - timedelta(days=STALE_LOGIN_DAYS))
    elif xavf == "2fa_yoq":
        stmt = stmt.where(User.role.in_(("super-admin", "admin"))).where(User.totp_enabled.is_(False))
    records, total = await paginate(db, stmt, page_params)
    items = [_to_admin_user_out(u) for u in records]
    return build_page(items, total, page_params)


@router.post("/api/users", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreateIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("manageRoles"))],
) -> AdminUserOut:
    existing = await db.execute(select(User).where(User.login == body.login))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu login band")

    user = User(
        login=body.login,
        password_hash=hash_password(body.password),
        full_name=body.name,
        role=_resolve_role(body.role, current_user),
        email=body.email,
        phone=_clean_phone(body.phone),
        # Cheklangan boshqaruvchi yaratgan hisob uning doirasini meros
        # oladi: aks holda yangi (cheklovsiz) hisob ochib, o'sha bilan
        # kirish doirani aylanib o'tish yo'li bo'lardi.
        # (Bo'sh to'plam — "hech narsa": bo'sh ro'yxat esa "hammasi" degani
        # bo'lardi, shuning uchun hech bir binoga mos kelmaydigan nil UUID.)
        allowed_building_ids=(
            (sorted(str(b) for b in scope) or [str(uuid.UUID(int=0))])
            if (scope := allowed_buildings(current_user)) is not None
            else None
        ),
    )
    db.add(user)
    await log_action(db, request, current_user.id, f"Yangi foydalanuvchi qo'shdi: {body.login}", "Foydalanuvchilar")
    await db.commit()
    await db.refresh(user)
    return _to_admin_user_out(user)


@router.patch("/api/users/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: str,
    body: UserUpdateIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("manageRoles"))],
) -> AdminUserOut:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Foydalanuvchi topilmadi")

    if body.login != user.login:
        existing = await db.execute(select(User).where(User.login == body.login, User.id != user.id))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Bu login band")

    _guard_super_admin_target(user, current_user)
    new_role = _resolve_role(body.role, current_user)
    await _forbid_last_super_admin_demotion(db, user, new_role)
    # O'zini o'zi pasaytirish ham taqiqlanadi: o'chirish taqiqlangan edi,
    # lekin rolni o'zgartirish ochiq qolgandi — Super Admin bir bosishda
    # huquqlar matritsasiga kira olmay qolardi (ikkinchi Super Admin bo'lsa
    # yuqoridagi tekshiruv ham ushlab qolmaydi).
    if user.id == current_user.id and new_role != user.role:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "O'z rolingizni o'zgartira olmaysiz — boshqa Super Admin buni qilsin")

    user.full_name = body.name
    user.login = body.login
    user.role = new_role
    user.email = body.email
    if "phone" in body.model_fields_set:
        user.phone = _clean_phone(body.phone)

    await log_action(db, request, current_user.id, f"Foydalanuvchini tahrirladi: {body.login}", "Foydalanuvchilar")
    await db.commit()
    await db.refresh(user)
    return _to_admin_user_out(user)


@router.post("/api/users/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def reset_user_password(
    user_id: str,
    body: ResetUserPasswordIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("manageRoles"))],
) -> None:
    """Admin-mediated reset — no email round-trip needed. Bumps the target
    user's token_version, so any session they currently have open (with
    the old password) is logged out immediately, same as self-service reset."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Foydalanuvchi topilmadi")

    _guard_super_admin_target(user, current_user)
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    forget_default_password_check()

    await log_action(
        db, request, current_user.id, f"Foydalanuvchi parolini tikladi: {user.login}", "Foydalanuvchilar"
    )
    await db.commit()


async def _get_user(db: AsyncSession, user_id: str) -> User:
    try:
        key = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Foydalanuvchi topilmadi") from None
    user = await db.get(User, key)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Foydalanuvchi topilmadi")
    return user


@router.post("/api/users/{user_id}/2fa/bekor", response_model=AdminUserOut)
@limiter.limit("10/minute")
async def reset_user_two_factor(
    user_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("manageRoles"))],
) -> AdminUserOut:
    """Telefonini yo'qotgan xodim uchun: 2FA butunlay olib tashlanadi,
    keyingi kirish faqat parol bilan, so'ng u qaytadan yoqadi.

    Super Admin hisobiga faqat Super Admin tegadi (parol tiklash bilan bir
    xil qoida) — aks holda manageRoles berilgan admin Super Admin'ning
    ikkinchi himoya qatlamini olib tashlab, uni egallashga bir qadam
    yaqinlashardi. token_version oshiriladi: agar telefon o'g'irlangan
    bo'lsa, shu paytgacha ochilgan sessiyalar ham yopiladi."""
    user = await _get_user(db, user_id)
    _guard_super_admin_target(user, current_user)
    clear_two_factor(user)
    user.token_version += 1
    await log_action(
        db, request, current_user.id, f"Ikki bosqichli kirishni bekor qildi: {user.login}", "Foydalanuvchilar"
    )
    await db.commit()
    await db.refresh(user)
    return _to_admin_user_out(user)


@router.put("/api/users/{user_id}/binolar", response_model=AdminUserOut)
async def set_user_building_scope(
    user_id: str,
    body: UserBuildingScopeIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("manageRoles"))],
) -> AdminUserOut:
    """Foydalanuvchi qaysi binolar kameralarini ko'rishini belgilaydi
    (app/services/access_scope.py). Bo'sh ro'yxat — barcha binolar.

    Doirani faqat O'ZI cheklanmagan foydalanuvchi o'zgartira oladi: aks
    holda bitta binoga cheklangan (lekin manageRoles'i bor) admin o'z
    cheklovini olib tashlab, butun kampusni ko'rib olardi."""
    if is_restricted(current_user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Bino doirasini faqat barcha binolarni ko'ra oladigan foydalanuvchi o'zgartiradi"
        )
    user = await _get_user(db, user_id)
    _guard_super_admin_target(user, current_user)
    if user.role == "super-admin" and body.building_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Super Admin doim barcha binolarni ko'radi")

    ids: list[uuid.UUID] = []
    for raw in dict.fromkeys(body.building_ids):
        try:
            ids.append(uuid.UUID(raw))
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Noto'g'ri bino identifikatori") from None
    if ids:
        found = set((await db.execute(select(Building.id).where(Building.id.in_(ids)))).scalars().all())
        if len(found) != len(ids):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Bunday bino topilmadi")

    user.allowed_building_ids = [str(i) for i in ids] or None
    names = (
        (await db.execute(select(Building.name).where(Building.id.in_(ids)).order_by(Building.name))).scalars().all()
        if ids
        else []
    )
    scope_text = ", ".join(names) if names else "barcha binolar"
    await log_action(
        db, request, current_user.id, f"Bino doirasini o'zgartirdi: {user.login} — {scope_text}", "Foydalanuvchilar"
    )
    await db.commit()
    await db.refresh(user)
    return _to_admin_user_out(user)


@router.delete("/api/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(require_permission("manageRoles"))],
) -> None:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Foydalanuvchi topilmadi")

    if str(user.id) == str(current_user.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O'zingizni o'chira olmaysiz")

    _guard_super_admin_target(user, current_user)

    if user.role == "super-admin":
        count_result = await db.execute(select(User).where(User.role == "super-admin"))
        if len(count_result.scalars().all()) <= 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Oxirgi Super Admin'ni o'chirib bo'lmaydi")

    await log_action(db, request, current_user.id, f"Foydalanuvchini o'chirdi: {user.login}", "Foydalanuvchilar")
    await db.delete(user)
    await db.commit()


@router.get("/api/permissions", response_model=dict[str, PermissionEntryOut])
async def get_permission_matrix(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, PermissionEntryOut]:
    result = await db.execute(select(Permission))
    return {
        p.key: PermissionEntryOut(
            super_admin=p.super_admin, admin=p.admin, camera_steward=p.camera_steward
        )
        for p in result.scalars().all()
    }


@router.patch("/api/permissions/{key}", response_model=PermissionEntryOut)
async def toggle_permission(
    key: str,
    body: PermissionToggleIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> PermissionEntryOut:
    # Matches UsersRolesPage.tsx: "Faqat Super Admin tahrirlashi mumkin" —
    # this is a hardcoded capability, not itself part of the configurable matrix.
    if current_user.role != "super-admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Faqat Super Admin huquqlarni o'zgartira oladi")

    # Super Admin ustuni o'zgarmaydi — UsersRolesPage.tsx uni "qulflangan"
    # qilib ko'rsatadi. require_permission() da Super Admin uchun chetlab
    # o'tish YO'Q: shu ustundagi bayroq o'chirilsa, o'sha huquq butun
    # tizimda yo'qoladi va uni qaytarish uchun ham huquq qolmaydi
    # (masalan 'manageRoles' — matritsa sahifasining o'zi berkiladi).
    if body.role == "superAdmin":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Super Admin huquqlari o'zgarmaydi — aks holda tizimga kirish yo'li yopilib qolardi",
        )

    result = await db.execute(select(Permission).where(Permission.key == key))
    permission = result.scalar_one_or_none()
    if permission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bunday huquq topilmadi")

    if body.role == "cameraSteward":
        permission.camera_steward = not permission.camera_steward
    else:
        permission.admin = not permission.admin

    await log_action(
        db, request, current_user.id, f"'{key}' huquqini o'zgartirdi ({body.role})", "Foydalanuvchilar va Rollar"
    )
    await db.commit()
    await db.refresh(permission)
    # camera_steward ham qaytarilishi SHART: frontend matritsadagi qatorni
    # shu javob bilan almashtiradi, maydon tushib qolsa "Kamera mas'uli"
    # ustuni doim o'chiq ko'rinib, keyingi bosish bazaga teskari yozardi.
    return PermissionEntryOut(
        super_admin=permission.super_admin,
        admin=permission.admin,
        camera_steward=permission.camera_steward,
    )
