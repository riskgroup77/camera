"""Videodevor ko'rinishlari — ish joylari o'rtasida umumiy (serverda).

Ko'rish/yaratish — viewLive. O'zgartirish va o'chirish — faqat egasi yoki
systemSettings huquqli admin (boshqa operator umumiy ko'rinishni
buzib qo'ymasin).
"""

import json
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, has_any_permission, require_permission
from app.models import User, WallView
from app.schemas.wall_view import (
    WallViewCreateIn,
    WallViewImportIn,
    WallViewImportOut,
    WallViewKind,
    WallViewOut,
    WallViewUpdateIn,
)
from app.timezone import to_local

router = APIRouter(prefix="/api/devor-korinishlar", tags=["wall-views"])

ViewerDep = Annotated[CurrentUser, Depends(require_permission("viewLive"))]
DbDep = Annotated[AsyncSession, Depends(get_db)]
MODULE = "Videodevor"
# Ko'rinish — bir necha o'nlab kamera id'si. Katta payload bu yerga
# tegishli emasligini bildiradi (xato yoki suiiste'mol).
MAX_PAYLOAD_BYTES = 16_000
MAX_VIEWS_PER_USER = 200


def _iso(moment: datetime | None) -> str | None:
    return to_local(moment).isoformat(timespec="seconds") if moment else None


def _to_out(view: WallView, owner_name: str | None, user_id: uuid.UUID, is_admin: bool) -> WallViewOut:
    mine = view.owner_id == user_id
    return WallViewOut(
        id=str(view.id),
        name=view.name,
        kind=view.kind,  # type: ignore[arg-type]
        payload=view.payload or {},
        shared=view.shared,
        owner_id=str(view.owner_id),
        owner_name=owner_name,
        mine=mine,
        can_edit=mine or is_admin,
        created_at=_iso(view.created_at),
        updated_at=_iso(view.updated_at),
    )


def _check_payload(payload: dict) -> dict:
    if len(json.dumps(payload, ensure_ascii=False)) > MAX_PAYLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Ko'rinish ma'lumoti juda katta")
    return payload


def _clean_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nomini kiriting")
    return name[:60]


def _parse_id(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def _is_admin(db: AsyncSession, user: CurrentUser) -> bool:
    return await has_any_permission(db, user.role, ("systemSettings",))


async def _owner_name(db: AsyncSession, owner_id: uuid.UUID) -> str | None:
    owner = await db.get(User, owner_id)
    return owner.full_name if owner else None


async def _visible(db: AsyncSession, user_id: uuid.UUID, kind: str) -> list[tuple[WallView, str | None]]:
    rows = (
        await db.execute(
            select(WallView, User.full_name)
            .outerjoin(User, User.id == WallView.owner_id)
            .where(WallView.kind == kind)
            .where(or_(WallView.owner_id == user_id, WallView.shared.is_(True)))
            .order_by(WallView.created_at, WallView.name)
            .limit(1000)
        )
    ).all()
    return [(view, name) for view, name in rows]


async def _own_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    return int(await db.scalar(select(func.count()).select_from(WallView).where(WallView.owner_id == user_id)) or 0)


async def _editable(db: AsyncSession, view_id: uuid.UUID, user: CurrentUser) -> tuple[WallView, bool]:
    view = await db.get(WallView, view_id)
    user_id = uuid.UUID(user.id)
    # Boshqaning ulashilmagan ko'rinishi "yo'q" — mavjudligini ham bildirmaymiz.
    if view is None or (view.owner_id != user_id and not view.shared):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ko'rinish topilmadi")
    is_admin = await _is_admin(db, user)
    if view.owner_id != user_id and not is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Faqat egasi o'zgartira oladi")
    return view, is_admin


@router.get("", response_model=list[WallViewOut])
async def list_views(
    db: DbDep, current_user: ViewerDep, kind: Annotated[WallViewKind, Query()] = "view"
) -> list[WallViewOut]:
    user_id = uuid.UUID(current_user.id)
    is_admin = await _is_admin(db, current_user)
    return [_to_out(view, name, user_id, is_admin) for view, name in await _visible(db, user_id, kind)]


@router.post("", response_model=WallViewOut, status_code=status.HTTP_201_CREATED)
async def create_view(request: Request, body: WallViewCreateIn, db: DbDep, current_user: ViewerDep) -> WallViewOut:
    user_id = uuid.UUID(current_user.id)
    if await _own_count(db, user_id) >= MAX_VIEWS_PER_USER:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Ko'pi bilan {MAX_VIEWS_PER_USER} ta ko'rinish")
    view_id = _parse_id(body.id)
    if view_id is not None and await db.get(WallView, view_id) is not None:
        view_id = None
    view = WallView(
        name=_clean_name(body.name),
        kind=body.kind,
        payload=_check_payload(body.payload),
        owner_id=user_id,
        shared=body.shared,
    )
    if view_id is not None:
        view.id = view_id
    db.add(view)
    await db.flush()
    await log_action(db, request, current_user.id, f"Videodevor ko'rinishi yaratildi: {view.name}", MODULE)
    await db.commit()
    await db.refresh(view)
    return _to_out(view, await _owner_name(db, user_id), user_id, await _is_admin(db, current_user))


@router.patch("/{view_id}", response_model=WallViewOut)
async def update_view(
    view_id: uuid.UUID, request: Request, body: WallViewUpdateIn, db: DbDep, current_user: ViewerDep
) -> WallViewOut:
    view, is_admin = await _editable(db, view_id, current_user)
    if body.name is not None:
        view.name = _clean_name(body.name)
    if body.payload is not None:
        view.payload = _check_payload(body.payload)
    if body.shared is not None:
        view.shared = body.shared
    await log_action(db, request, current_user.id, f"Videodevor ko'rinishi o'zgartirildi: {view.name}", MODULE)
    await db.commit()
    await db.refresh(view)
    return _to_out(view, await _owner_name(db, view.owner_id), uuid.UUID(current_user.id), is_admin)


@router.delete("/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_view(view_id: uuid.UUID, request: Request, db: DbDep, current_user: ViewerDep) -> Response:
    view, _ = await _editable(db, view_id, current_user)
    name = view.name
    await db.delete(view)
    await log_action(db, request, current_user.id, f"Videodevor ko'rinishi o'chirildi: {name}", MODULE)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/import", response_model=WallViewImportOut)
async def import_views(request: Request, body: WallViewImportIn, db: DbDep, current_user: ViewerDep) -> WallViewImportOut:
    """Brauzerdagi (localStorage) ko'rinishlarni bir martada serverga
    ko'chirish — takroriy chaqiruv xavfsiz: o'zining shu id'li ko'rinishi
    faqat kelgani yangiroq bo'lsa yangilanadi, boshqaning id'si bilan
    kelgani esa o'tkazib yuboriladi (begona ko'rinishni egallab olmasin)."""
    user_id = uuid.UUID(current_user.id)
    is_admin = await _is_admin(db, current_user)
    created = updated = skipped = 0
    room = MAX_VIEWS_PER_USER - await _own_count(db, user_id)
    for item in body.items:
        try:
            payload = _check_payload(item.payload)
            name = _clean_name(item.name)
        except HTTPException:
            skipped += 1
            continue
        view_id = _parse_id(item.id)
        existing = await db.get(WallView, view_id) if view_id else None
        if existing is not None:
            if existing.owner_id != user_id or existing.kind != item.kind:
                skipped += 1
                continue
            incoming = _parse_time(item.updated_at)
            if incoming is not None and existing.updated_at is not None and incoming <= existing.updated_at:
                skipped += 1
                continue
            existing.name = name
            existing.payload = payload
            updated += 1
            continue
        if room <= 0:
            skipped += 1
            continue
        view = WallView(name=name, kind=item.kind, payload=payload, owner_id=user_id, shared=item.shared)
        if view_id is not None:
            view.id = view_id
        db.add(view)
        await db.flush()
        room -= 1
        created += 1
    if created or updated:
        await log_action(
            db, request, current_user.id, f"Videodevor ko'rinishlari import qilindi: +{created}, ~{updated}", MODULE
        )
    await db.commit()
    kind = body.items[0].kind if body.items else "view"
    items = [_to_out(view, name, user_id, is_admin) for view, name in await _visible(db, user_id, kind)]
    return WallViewImportOut(created=created, updated=updated, skipped=skipped, items=items)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else None
