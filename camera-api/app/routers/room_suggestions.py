"""Kamera -> xona takliflari (app/services/room_inference.py) — /api/xona-takliflari."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.models import Building, Camera
from app.schemas.base import CamelModel
from app.services.access_scope import camera_filter
from app.services.camera_roles import normalize_room_code
from app.services.integrations.hemis_schedule import relink_cameras
from app.services.room_inference import suggest_rooms

router = APIRouter(prefix="/api/xona-takliflari", tags=["kameralar"])
PermDep = Annotated[CurrentUser, Depends(require_permission("manageCameras"))]


class RoomSuggestionOut(CamelModel):
    camera_id: str
    camera_name: str
    current_room: str | None
    current_building: str | None
    room_code: str
    building_number: int
    hemis_building: str | None
    auditorium: str | None
    building_id: str | None
    people: int
    lessons: int
    share: float
    agrees: bool
    conflict_camera: str | None


class ApplyRoomIn(CamelModel):
    room_code: str
    building_id: str | None = None


class ApplyRoomOut(CamelModel):
    message: str
    relinked_lessons: int


@router.get("", response_model=list[RoomSuggestionOut])
async def list_suggestions(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: PermDep,
    kun: Annotated[int, Query(ge=1, le=60)] = 14,
    min_odam: Annotated[int, Query(ge=1, le=50)] = 3,
) -> list[RoomSuggestionOut]:
    """Dars vaqtida tanilgan odamlar bo'yicha har kamera uchun ehtimoliy xona."""
    allowed = set((await db.execute(select(Camera.id).where(camera_filter(current_user)))).scalars())
    return [
        RoomSuggestionOut(
            **{
                **s.__dict__,
                "camera_id": str(s.camera_id),
                "building_id": str(s.building_id) if s.building_id else None,
            }
        )
        for s in await suggest_rooms(db, days=kun, min_people=min_odam)
        if s.camera_id in allowed
    ]


@router.post("/{camera_id}/qollash", response_model=ApplyRoomOut)
async def apply_suggestion(
    camera_id: str,
    body: ApplyRoomIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: PermDep,
) -> ApplyRoomOut:
    try:
        key = uuid.UUID(camera_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi") from None
    camera = (await db.execute(select(Camera).where(Camera.id == key, camera_filter(current_user)))).scalar_one_or_none()
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi")
    code = normalize_room_code(body.room_code)
    if not code:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Xona raqami bo'sh")
    if body.building_id:
        try:
            building = await db.get(Building, uuid.UUID(body.building_id))
        except ValueError:
            building = None
        if building is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Bino topilmadi")
        camera.building_id = building.id
    camera.room_code = code
    await db.flush()
    relinked = await relink_cameras(db)
    await log_action(db, request, current_user.id, f"{camera.name}: xona {code} (taklif asosida)", "Kameralar")
    await db.commit()
    return ApplyRoomOut(message=f"{camera.name} — {code}-xona. {relinked} ta dars shu kameraga bog'landi", relinked_lessons=relinked)
