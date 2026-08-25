from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit import log_action
from app.crypto import decrypt, encrypt
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.jobs.camera_health import is_reachable
from app.models import Building, Camera
from app.pagination import Page, PageParams, build_page, paginate
from app.rtsp import build_rtsp_url
from app.schemas.camera import (
    CameraCreateIn,
    CameraModulesIn,
    CameraOut,
    CameraUpdateIn,
    CameraZoneOut,
    CameraZonePolygonIn,
    ConnectionTestIn,
    ConnectionTestOut,
)
from app.services.connectivity import test_camera_connection
from app.services.video_gateway import register_camera_stream, unregister_camera_stream

router = APIRouter(prefix="/api/cameras", tags=["cameras"])

PermDep = Annotated[CurrentUser, Depends(require_permission("manageCameras"))]


async def _resolve_building(db: AsyncSession, name: str) -> Building:
    result = await db.execute(select(Building).where(Building.name == name))
    building = result.scalar_one_or_none()
    if building is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"'{name}' nomli bino topilmadi")
    return building


async def _sync_stream(db: AsyncSession, camera: Camera) -> None:
    """Keeps the video gateway's registration in sync with the camera's
    status. Only 'faol' cameras get a live HLS URL — this is the piece
    the frontend's LiveVideoPlayer.tsx has been waiting for since it was
    built with a streamUrl prop and no way to populate it."""
    if camera.status == "faol":
        camera.stream_url = await register_camera_stream(
            str(camera.id),
            build_rtsp_url(
                camera.ip,
                camera.port,
                camera.rtsp_path,
                decrypt(camera.rtsp_username) if camera.rtsp_username else None,
                decrypt(camera.rtsp_password) if camera.rtsp_password else None,
            ),
        )
    elif camera.stream_url is not None:
        await unregister_camera_stream(str(camera.id))
        camera.stream_url = None
    await db.commit()
    await db.refresh(camera, attribute_names=["building"])


def _to_out(camera: Camera) -> CameraOut:
    return CameraOut(
        id=str(camera.id),
        name=camera.name,
        ip=camera.ip,
        port=camera.port,
        rtsp_path=camera.rtsp_path,
        building=camera.building.name if camera.building else "",
        zone=camera.zone,
        resolution=camera.resolution,
        fps=camera.fps,
        status=camera.status,
        stream_url=camera.stream_url,
        is_reachable=is_reachable(camera.last_seen_at),
        restricted_zone_polygon=camera.restricted_zone_polygon,
        excluded_module_codes=camera.excluded_module_codes,
        is_entrance=camera.is_entrance,
    )


@router.get("", response_model=Page[CameraOut])
async def list_cameras(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: PermDep,
    page_params: Annotated[PageParams, Depends()],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    building: Annotated[str | None, Query()] = None,
    zone: Annotated[str | None, Query()] = None,
) -> Page[CameraOut]:
    stmt = select(Camera).options(selectinload(Camera.building)).order_by(Camera.created_at.desc())
    if status_filter:
        stmt = stmt.where(Camera.status == status_filter)
    if building:
        stmt = stmt.join(Building).where(Building.name == building)
    if zone:
        stmt = stmt.where(Camera.zone == zone)

    records, total = await paginate(db, stmt, page_params)
    items = [_to_out(c) for c in records]
    return build_page(items, total, page_params)


@router.get("/zones", response_model=list[CameraZoneOut])
async def list_camera_zones(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: PermDep,
    building: Annotated[str | None, Query()] = None,
) -> list[CameraZoneOut]:
    """Distinct zone names with their camera count — a room routinely holds
    more than one camera (different angles), so this backs both the
    zone-name autocomplete in AddCameraModal.tsx (pick an existing room
    instead of retyping/mistyping its name) and the zone filter chips in
    CamerasZonesPage.tsx."""
    stmt = select(Camera.zone, func.count(Camera.id)).group_by(Camera.zone).order_by(Camera.zone)
    if building:
        stmt = stmt.join(Building).where(Building.name == building)

    result = await db.execute(stmt)
    return [CameraZoneOut(zone=zone_name, camera_count=count) for zone_name, count in result.all()]


@router.post("", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
async def create_camera(
    body: CameraCreateIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: PermDep,
) -> CameraOut:
    building = await _resolve_building(db, body.building)
    camera = Camera(
        name=body.name,
        ip=body.ip,
        port=body.port,
        rtsp_path=body.rtsp_path,
        rtsp_username=encrypt(body.rtsp_username) if body.rtsp_username else None,
        rtsp_password=encrypt(body.rtsp_password) if body.rtsp_password else None,
        building_id=building.id,
        zone=body.zone,
        resolution=body.resolution,
        fps=body.fps,
        status=body.status,
        is_entrance=body.is_entrance,
    )
    db.add(camera)
    await log_action(db, request, current_user.id, f"Yangi kamera qo'shdi: {body.name}", "Kameralar")
    await db.commit()
    await db.refresh(camera, attribute_names=["building"])
    await _sync_stream(db, camera)
    return _to_out(camera)


@router.patch("/{camera_id}", response_model=CameraOut)
async def update_camera(
    camera_id: str,
    body: CameraUpdateIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: PermDep,
) -> CameraOut:
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi")

    building = await _resolve_building(db, body.building)
    camera.name = body.name
    camera.ip = body.ip
    camera.port = body.port
    camera.rtsp_path = body.rtsp_path
    if body.rtsp_username is not None:
        camera.rtsp_username = encrypt(body.rtsp_username)
    if body.rtsp_password is not None:
        camera.rtsp_password = encrypt(body.rtsp_password)
    camera.building_id = building.id
    camera.zone = body.zone
    camera.resolution = body.resolution
    camera.fps = body.fps
    camera.status = body.status
    camera.is_entrance = body.is_entrance

    await log_action(db, request, current_user.id, f"Kamerani tahrirladi: {body.name}", "Kameralar")
    await db.commit()
    await db.refresh(camera, attribute_names=["building"])
    await _sync_stream(db, camera)
    return _to_out(camera)


@router.patch("/{camera_id}/zone-polygon", response_model=CameraOut)
async def set_camera_zone_polygon(
    camera_id: str,
    body: CameraZonePolygonIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: PermDep,
) -> CameraOut:
    """Separate from update_camera (PATCH /{camera_id}) since the polygon
    is drawn interactively on the live video feed — a distinct workflow
    (CameraZoneModal.tsx) from the edit form, and one that shouldn't force
    re-sending every other camera field just to draw/clear a zone."""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi")

    if body.polygon is not None and len(body.polygon) > 0 and len(body.polygon) < 3:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Zona kamida 3 ta nuqtadan iborat bo'lishi kerak")

    camera.restricted_zone_polygon = body.polygon if body.polygon else None

    action = "Taqiqlangan zonani o'rnatdi" if camera.restricted_zone_polygon else "Taqiqlangan zonani tozaladi"
    await log_action(db, request, current_user.id, f"{action}: {camera.name}", "Kameralar")
    await db.commit()
    await db.refresh(camera, attribute_names=["building"])
    return _to_out(camera)


@router.patch("/{camera_id}/modules", response_model=CameraOut)
async def set_camera_excluded_modules(
    camera_id: str,
    body: CameraModulesIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: PermDep,
) -> CameraOut:
    """Separate from update_camera (PATCH /{camera_id}) for the same
    reason set_camera_zone_polygon is — a distinct admin workflow
    (checkbox list of AI modules, CameraModulesModal.tsx) shouldn't force
    re-sending every other camera field. Every app/jobs/*.py sweep loop
    checks Camera.excluded_module_codes on its next tick — no restart
    needed for a change here to take effect."""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi")

    camera.excluded_module_codes = body.excluded_module_codes if body.excluded_module_codes else None

    await log_action(
        db, request, current_user.id, f"Kamera uchun AI modullarni sozladi: {camera.name}", "Kameralar"
    )
    await db.commit()
    await db.refresh(camera, attribute_names=["building"])
    return _to_out(camera)


@router.post("/test-connection", response_model=ConnectionTestOut)
async def test_connection(body: ConnectionTestIn, _: PermDep) -> ConnectionTestOut:
    """Used by the 'add camera' flow, before anything is saved — credentials
    here are raw request input, never touch encrypt()/decrypt()."""
    return await test_camera_connection(
        ip=body.ip,
        port=body.port,
        rtsp_path=body.rtsp_path,
        username=body.rtsp_username,
        password=body.rtsp_password,
    )


@router.post("/{camera_id}/test-connection", response_model=ConnectionTestOut)
async def test_saved_camera_connection(
    camera_id: str, db: Annotated[AsyncSession, Depends(get_db)], _: PermDep
) -> ConnectionTestOut:
    """Re-verifies an already-saved camera using its stored (encrypted)
    credentials — the admin doesn't need to retype login/parol to re-check
    a camera that's gone offline."""
    result = await db.execute(select(Camera).where(Camera.id == camera_id))
    camera = result.scalar_one_or_none()
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi")

    return await test_camera_connection(
        ip=camera.ip,
        port=camera.port,
        rtsp_path=camera.rtsp_path,
        username=decrypt(camera.rtsp_username) if camera.rtsp_username else None,
        password=decrypt(camera.rtsp_password) if camera.rtsp_password else None,
    )
