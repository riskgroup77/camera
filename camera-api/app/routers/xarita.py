"""Xarita — qavat rejasi ustida kameralar (Milestone Smart Map kabi).

Operator ekrani uchun ixcham API: bino/qavat tanlanadi, reja rasmi va
shu qavat kameralari holati (devor bilan bir xil semantika), ko'rish
konusi va ochiq signallar soni bilan bitta so'rovda keladi.

Ma'lumot modeli qavat rejalari bilan umumiy (floor_plans jadvali,
cameras.plan_x/plan_y/plan_rotation/plan_fov) — /api/floor-plans bilan
ikki xil nusxa paydo bo'lmasin. Mantiq app/services/floor_plans.py dan
olinadi.

Huquqlar: o'qish — viewLive; rasm yuklash va kamerani joylash —
editCameraLocation. O'zgarishlar audit jurnaliga yoziladi.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Path, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, has_any_permission, require_permission
from app.models import Building, Camera, PresenceVisit
from app.services.access_scope import allowed_buildings, camera_filter, ensure_camera_allowed
from app.models.platform import FloorPlan
from app.schemas.xarita import (
    XaritaBuildingOut,
    XaritaCameraOut,
    XaritaFloorOut,
    XaritaFloorViewOut,
    XaritaPlacementIn,
    XaritaPlanOut,
)
from app.services.floor_plans import (
    PlanImageError,
    camera_health,
    default_plan_name,
    inspect_plan_image,
    is_on_plan,
    is_unassigned_candidate,
    open_event_counts,
    plan_camera_counts,
    unassigned_candidate_filter,
)
from app.services.stream_links import signed_stream_url
from app.storage import delete_files_quietly, presigned_url, upload_file

logger = logging.getLogger("app.xarita")

router = APIRouter(prefix="/api/xarita", tags=["xarita"])

ViewDep = Annotated[CurrentUser, Depends(require_permission("viewLive"))]
EditDep = Annotated[CurrentUser, Depends(require_permission("editCameraLocation"))]
DbDep = Annotated[AsyncSession, Depends(get_db)]
FloorPath = Annotated[int, Path(ge=-10, le=200)]

AUDIT_MODULE = "Xarita"
# Xarita brauzerda to'liq ochiladi — 10 MB dan kattasi sekin yuklanadi,
# chizmani eksport qilishda bu chegaraga sig'ish oson.
MAX_MAP_BYTES = 10 * 1024 * 1024
ALLOWED_TYPES = ("image/png", "image/jpeg")
DEFAULT_FOV = 70


def _parse_uuid(raw: str, message: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, message) from None


def _image_url(key: str) -> str | None:
    # Imzolash xatosi butun qavat ko'rinishini 500 ga aylantirmasin —
    # kameralar ro'yxati rasmsiz ham foydali.
    try:
        return presigned_url(key)
    except Exception:
        logger.warning("map presign failed", extra={"key": key}, exc_info=True)
        return None


def _plan_out(plan: FloorPlan) -> XaritaPlanOut:
    stamp = plan.updated_at or plan.created_at
    return XaritaPlanOut(
        image_url=_image_url(plan.image_key),
        width=plan.width,
        height=plan.height,
        updated_at=stamp.astimezone(timezone.utc).isoformat() if stamp else "",
    )


def _map_status(camera: Camera) -> str:
    online, video = camera_health(camera)
    if not online:
        return "offline"
    return "online" if video else "novideo"


#: "Hozir" oynasi — xaritada kamera oldidagi odamlar soni shu davr bo'yicha.
PEOPLE_WINDOW = timedelta(minutes=10)


async def people_now_counts(db: AsyncSession, camera_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not camera_ids:
        return {}
    since = datetime.now(timezone.utc) - PEOPLE_WINDOW
    rows = await db.execute(
        select(PresenceVisit.camera_id, func.count(func.distinct(PresenceVisit.student_staff_id)))
        .where(PresenceVisit.camera_id.in_(camera_ids), PresenceVisit.last_seen_at >= since)
        .group_by(PresenceVisit.camera_id)
    )
    return dict(rows.all())


def _camera_out(
    camera: Camera, events: dict[uuid.UUID, int], *, assigned: bool = True, people: dict[uuid.UUID, int] | None = None
) -> XaritaCameraOut:
    return XaritaCameraOut(
        id=str(camera.id),
        name=camera.name,
        zone=camera.zone or "",
        status=_map_status(camera),
        # Biriktirilmagan kameraning eski koordinatasi boshqa rejaga tegishli.
        x=camera.plan_x if assigned else None,
        y=camera.plan_y if assigned else None,
        angle=camera.plan_rotation if assigned else None,
        fov=camera.plan_fov or DEFAULT_FOV,
        open_events=events.get(camera.id, 0),
        people_now=(people or {}).get(camera.id, 0),
        stream_url=signed_stream_url(camera.stream_url),
        assigned=assigned,
    )


async def _building(db: AsyncSession, building_id: str, user=None) -> Building:
    building = await db.get(Building, _parse_uuid(building_id, "Bino topilmadi"))
    allowed = allowed_buildings(user)
    # Bino doirasi cheklangan foydalanuvchi boshqa binoni (va uning jonli
    # oqim havolalarini) ko'rmaydi — mavjudligini ham oshkor qilmaymiz.
    if building is None or (allowed is not None and building.id not in allowed):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bino topilmadi")
    return building


async def _plan(db: AsyncSession, building_id: uuid.UUID, floor: int) -> FloorPlan | None:
    return (
        await db.execute(select(FloorPlan).where(FloorPlan.building_id == building_id, FloorPlan.floor == floor))
    ).scalar_one_or_none()


@router.get("/binolar", response_model=list[XaritaBuildingOut])
async def list_buildings(db: DbDep, current_user: ViewDep) -> list[XaritaBuildingOut]:
    """Rejasi yoki kamerasi bor qavatli binolar. Tahrir huquqi borlarga
    binoning e'lon qilingan barcha qavatlari ham qaytadi — bo'sh qavatga
    ham reja yuklash mumkin bo'lsin."""
    can_edit = await has_any_permission(db, current_user.role, ("editCameraLocation",))
    buildings = (await db.execute(select(Building).order_by(Building.sort_order, Building.name))).scalars().all()
    allowed = allowed_buildings(current_user)
    if allowed is not None:
        buildings = [b for b in buildings if b.id in allowed]
    plans = (await db.execute(select(FloorPlan.building_id, FloorPlan.floor))).all()
    with_plan = {(b, f) for b, f in plans}
    counts = await plan_camera_counts(db)

    out: list[XaritaBuildingOut] = []
    for building in buildings:
        floors = {f for b, f in with_plan if b == building.id} | {f for b, f in counts if b == building.id}
        if can_edit and building.floors:
            floors |= set(range(1, building.floors + 1))
        if not floors:
            continue
        out.append(
            XaritaBuildingOut(
                id=str(building.id),
                name=building.name,
                floors=[
                    XaritaFloorOut(
                        floor=f,
                        has_plan=(building.id, f) in with_plan,
                        camera_count=counts.get((building.id, f), (0, 0))[0],
                        placed_count=counts.get((building.id, f), (0, 0))[1],
                    )
                    for f in sorted(floors)
                ],
            )
        )
    return out


@router.get("/{building_id}/{floor}", response_model=XaritaFloorViewOut)
async def floor_view(building_id: str, floor: FloorPath, db: DbDep, current_user: ViewDep) -> XaritaFloorViewOut:
    building = await _building(db, building_id, current_user)
    plan = await _plan(db, building.id, floor)
    cameras = (
        await db.execute(
            select(Camera).where(Camera.building_id == building.id, Camera.floor == floor).order_by(Camera.name)
        )
    ).scalars().all()
    events = await open_event_counts(db, [c.id for c in cameras])
    people = await people_now_counts(db, [c.id for c in cameras])

    candidates: list[XaritaCameraOut] = []
    if await has_any_permission(db, current_user.role, ("editCameraLocation",)):
        # Qavati belgilanmagan kameralarni xaritaga qo'yish — shu qavatga
        # biriktirishning eng tez yo'li.
        probe = FloorPlan(building_id=building.id, floor=floor)
        rows = (
            await db.execute(
                select(Camera).where(unassigned_candidate_filter(probe), camera_filter(current_user)).order_by(Camera.name)
            )
        ).scalars().all()
        candidates = [_camera_out(c, {}, assigned=False) for c in rows]

    return XaritaFloorViewOut(
        building_id=str(building.id),
        building_name=building.name,
        floor=floor,
        plan=_plan_out(plan) if plan else None,
        cameras=[_camera_out(c, events, people=people) for c in cameras],
        candidates=candidates,
    )


@router.put("/{building_id}/{floor}/rasm", response_model=XaritaPlanOut)
async def upload_map_image(
    building_id: str,
    floor: FloorPath,
    request: Request,
    db: DbDep,
    current_user: EditDep,
    file: Annotated[UploadFile, File(description="Qavat chizmasi: PNG yoki JPEG, 10 MB gacha")],
) -> XaritaPlanOut:
    """Qavat rejasini yaratadi yoki rasmini almashtiradi. Kameralar
    joylashuvi nisbiy (0..1) — rasm almashganda ham saqlanadi."""
    building = await _building(db, building_id, current_user)
    if building.floors and floor > building.floors:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{building.name} {building.floors} qavatli")

    # Chegaradan bitta bayt ortiq o'qiladi: katta fayl to'liq xotiraga olinmaydi.
    data = await file.read(MAX_MAP_BYTES + 1)
    if len(data) > MAX_MAP_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Rasm juda katta — ko'pi bilan 10 MB")
    try:
        image = inspect_plan_image(data)
    except PlanImageError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    if image.content_type not in ALLOWED_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Faqat PNG yoki JPEG rasm qabul qilinadi")

    try:
        _file_id, key = await asyncio.to_thread(
            upload_file, data, f"plan.{image.extension}", image.content_type, "floor-plans"
        )
    except Exception:
        logger.exception("map image upload failed")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Rasmni saqlab bo'lmadi — keyinroq urinib ko'ring") from None

    plan = await _plan(db, building.id, floor)
    old_key = plan.image_key if plan else None
    if plan is None:
        plan = FloorPlan(
            building_id=building.id,
            floor=floor,
            name=default_plan_name(building.name, floor),
            image_key=key,
            width=image.width,
            height=image.height,
        )
        db.add(plan)
        action = f"Xarita rasmini yukladi: {building.name}, {floor}-qavat"
    else:
        plan.image_key = key
        plan.width = image.width
        plan.height = image.height
        action = f"Xarita rasmini almashtirdi: {building.name}, {floor}-qavat"

    await log_action(db, request, current_user.id, action, AUDIT_MODULE)
    try:
        await db.commit()
    except IntegrityError:
        # Ikki kishi bir vaqtda shu qavatga birinchi rasmni yukladi.
        await db.rollback()
        await delete_files_quietly([key])
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu qavat rejasi hozirgina yaratildi — sahifani yangilang") from None
    except Exception:
        await db.rollback()
        await delete_files_quietly([key])
        raise
    await delete_files_quietly([old_key])
    await db.refresh(plan)
    return _plan_out(plan)


@router.put("/kamera/{camera_id}/joy", response_model=XaritaCameraOut)
async def place_camera(
    camera_id: str,
    body: XaritaPlacementIn,
    request: Request,
    db: DbDep,
    current_user: EditDep,
) -> XaritaCameraOut:
    """Kamerani xaritaga qo'yadi, suradi, buradi yoki (x=y=null) olib
    tashlaydi.

    buildingId+floor berilsa va kamera hali qavatga biriktirilmagan bo'lsa
    — shu qavatga biriktiriladi. Boshqa qavatdagi kamerani bu yo'l bilan
    jimgina ko'chirib bo'lmaydi (409): buning uchun kameralar sozlamasi bor."""
    camera = await db.get(Camera, _parse_uuid(camera_id, "Kamera topilmadi"))
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi")
    ensure_camera_allowed(current_user, camera)

    assigned_now = False
    if body.building_id is not None and body.floor is not None:
        target = FloorPlan(building_id=_parse_uuid(body.building_id, "Bino topilmadi"), floor=body.floor)
        if not is_on_plan(camera, target):
            if not is_unassigned_candidate(camera, target):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"{camera.name} boshqa bino yoki qavatga biriktirilgan — kameralar sozlamasida o'zgartiring",
                )
            if body.x is None:
                # Biriktirilmagan kamerani "olib tashlash" — o'zgarish yo'q.
                return _camera_out(camera, {}, assigned=False)
            if await db.get(Building, target.building_id) is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Bino topilmadi")
            # Bino/qavat o'zgarishi reja joyini tozalaydi (models/camera.py
            # tinglovchisi) — shuning uchun koordinatadan OLDIN.
            camera.building_id = target.building_id
            camera.floor = target.floor
            assigned_now = True
    elif camera.building_id is None or camera.floor is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kamera qavatga biriktirilmagan — buildingId va floor bering")

    camera.plan_x = body.x
    camera.plan_y = body.y
    camera.plan_rotation = (body.angle or 0) if body.x is not None else None
    if body.fov is not None:
        camera.plan_fov = body.fov

    if body.x is None:
        action = f"Kamerani xaritadan olib tashladi: {camera.name}"
    else:
        action = f"Kamera joyini xaritada o'zgartirdi: {camera.name}"
        if assigned_now:
            action += f" (qavatga biriktirildi: {camera.floor}-qavat)"
    await log_action(db, request, current_user.id, action, AUDIT_MODULE)
    await db.commit()
    await db.refresh(camera)
    events = await open_event_counts(db, [camera.id])
    return _camera_out(camera, events)
