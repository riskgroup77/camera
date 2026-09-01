from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, get_current_user, require_permission
from app.models import Permission, User
from app.models.user import role_display_label, role_from_display_label
from app.pagination import Page, PageParams, build_page, paginate
from app.rate_limit import limiter
from app.schemas.permission import PermissionEntryOut, PermissionToggleIn
from app.schemas.user import AdminUserOut, ResetUserPasswordIn, UserCreateIn, UserUpdateIn
from app.security import hash_password
from app.timezone import to_local
from app.utils import compute_initials

router = APIRouter(tags=["users"])


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
        role=role_display_label(user.role),
        email=user.email,
    )


@router.get("/api/users", response_model=Page[AdminUserOut])
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission("manageRoles"))],
    page_params: Annotated[PageParams, Depends()],
) -> Page[AdminUserOut]:
    stmt = select(User).order_by(User.created_at)
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
        role=role_from_display_label(body.role),
        email=body.email,
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

    user.full_name = body.name
    user.login = body.login
    user.role = role_from_display_label(body.role)
    user.email = body.email

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

    user.password_hash = hash_password(body.new_password)
    user.token_version += 1

    await log_action(
        db, request, current_user.id, f"Foydalanuvchi parolini tikladi: {user.login}", "Foydalanuvchilar"
    )
    await db.commit()


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
        p.key: PermissionEntryOut(super_admin=p.super_admin, admin=p.admin)
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

    result = await db.execute(select(Permission).where(Permission.key == key))
    permission = result.scalar_one_or_none()
    if permission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bunday huquq topilmadi")

    if body.role == "superAdmin":
        permission.super_admin = not permission.super_admin
    else:
        permission.admin = not permission.admin

    await log_action(
        db, request, current_user.id, f"'{key}' huquqini o'zgartirdi ({body.role})", "Foydalanuvchilar va Rollar"
    )
    await db.commit()
    await db.refresh(permission)
    return PermissionEntryOut(super_admin=permission.super_admin, admin=permission.admin)
