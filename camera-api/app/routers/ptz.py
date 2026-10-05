"""PTZ kamera boshqaruvi (ONVIF / Hikvision ISAPI).

Kameraga buyruqlar app/services/ptz.py orqali yuboriladi. Bu yerda —
huquq tekshiruvi, kamerani bazadan olish, login/parolni ochish va
xizmat xatolarini HTTP javobiga aylantirish.

Jurnal (audit_log) faqat preset SAQLASH uchun yoziladi: har bir harakat
("chapga 300 ms") jurnalni keraksiz yozuvlar bilan to'ldirib yuborardi,
preset esa kamerada saqlanadigan doimiy o'zgarish.
"""

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.crypto import decrypt
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.models import Camera
from app.rate_limit import limiter
from app.schemas.ptz import (
    PtzAdhocProbeIn,
    PtzMoveIn,
    PtzPresetIn,
    PtzPresetOut,
    PtzProbeIn,
    PtzProbeOut,
    PtzStatusOut,
)
from app.services import ptz as ptz_service
from app.services.access_scope import ensure_camera_allowed

router = APIRouter(prefix="/api/cameras", tags=["ptz"])

PtzDep = Annotated[CurrentUser, Depends(require_permission("controlPtz"))]
# Tekshiruv (probe) — sozlash jarayonining qismi: kamerani qo'shayotgan
# admin (manageCameras) ham, PTZ operatori ham ishlata oladi.
ProbeDep = Annotated[CurrentUser, Depends(require_permission("manageCameras", "controlPtz"))]
# Saqlanmagan kamera uchun tekshiruv ixtiyoriy IP'ga so'rov yuboradi —
# faqat kamera qo'sha oladiganlar uchun (POST /api/cameras/test-connection kabi).
AdhocProbeDep = Annotated[CurrentUser, Depends(require_permission("manageCameras"))]

# Xost nomi yoki IP (IPv6 kvadrat qavsda ham) — yo'l, so'rov yoki
# foydalanuvchi ma'lumoti qo'shib yuborishning oldini oladi.
_HOST_RE = re.compile(r"^[A-Za-z0-9.\-:\[\]]{1,255}$")


def _camera_uuid(camera_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(camera_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi") from None


async def _get_camera(db: AsyncSession, camera_id: str, user: CurrentUser) -> Camera:
    camera = await db.get(Camera, _camera_uuid(camera_id))
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi")
    # Boshqa bino kamerasini burish ham, uning holatini ko'rish ham — yo'q.
    return ensure_camera_allowed(user, camera)


def _decrypt_or_empty(value: str | None) -> str:
    if not value:
        return ""
    try:
        return decrypt(value)
    except ValueError:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Kamera login/parolini ochib bo'lmadi — ENCRYPTION_KEY o'zgargan bo'lishi mumkin",
        ) from None


def _target(
    camera: Camera,
    *,
    protocol: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
) -> ptz_service.PtzTarget:
    return ptz_service.PtzTarget(
        camera_id=str(camera.id),
        host=camera.ip,
        port=port or camera.onvif_port or ptz_service.DEFAULT_HTTP_PORT,
        username=username if username is not None else _decrypt_or_empty(camera.rtsp_username),
        password=password if password is not None else _decrypt_or_empty(camera.rtsp_password),
        protocol=protocol if protocol is not None else (camera.ptz_protocol or ""),
    )


async def _enabled_target(
    db: AsyncSession, camera_id: str, user: CurrentUser
) -> tuple[Camera, ptz_service.PtzTarget]:
    camera = await _get_camera(db, camera_id, user)
    if not camera.ptz_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu kamerada PTZ boshqaruvi yoqilmagan")
    if camera.ptz_protocol not in ptz_service.PROTOCOLS:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Kamera uchun PTZ protokoli tanlanmagan (ONVIF yoki Hikvision ISAPI)"
        )
    return camera, _target(camera)


def _http_error(exc: ptz_service.PtzError) -> HTTPException:
    return HTTPException(exc.http_status, exc.message)


def _probe_out(result: ptz_service.PtzProbeResult) -> PtzProbeOut:
    return PtzProbeOut(
        success=result.success,
        message=result.message,
        protocol=result.protocol if result.protocol in ptz_service.PROTOCOLS else None,
        reachable=result.reachable,
        authenticated=result.authenticated,
        ptz_supported=result.ptz_supported,
        presets_supported=result.presets_supported,
        preset_count=result.preset_count,
        device_info=result.device_info,
        latency_ms=result.latency_ms,
        tried=[p for p in result.tried if p in ptz_service.PROTOCOLS],
    )


@router.post("/ptz/probe", response_model=PtzProbeOut)
@limiter.limit("20/minute")
async def probe_unsaved_camera(request: Request, body: PtzAdhocProbeIn, _: AdhocProbeDep) -> PtzProbeOut:
    """"Yangi kamera qo'shish" formasi — kamera hali bazada yo'q, login/parol
    so'rov tanasidan olinadi va hech qayerda saqlanmaydi."""
    host = body.ip.strip()
    if not _HOST_RE.match(host):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "IP manzil noto'g'ri")
    target = ptz_service.PtzTarget(
        camera_id=f"probe:{host}",
        host=host,
        port=body.onvif_port or ptz_service.DEFAULT_HTTP_PORT,
        username=body.username or "",
        password=body.password or "",
        protocol=body.protocol or "",
    )
    try:
        return _probe_out(await ptz_service.probe(target))
    finally:
        ptz_service.invalidate_camera(target.camera_id)


@router.get("/{camera_id}/ptz", response_model=PtzStatusOut)
async def get_ptz_status(
    camera_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: PtzDep,
) -> PtzStatusOut:
    camera = await _get_camera(db, camera_id, current_user)
    return PtzStatusOut(
        camera_id=str(camera.id),
        enabled=camera.ptz_enabled,
        protocol=camera.ptz_protocol if camera.ptz_protocol in ptz_service.PROTOCOLS else None,
        onvif_port=camera.onvif_port,
    )


@router.post("/{camera_id}/ptz/probe", response_model=PtzProbeOut)
@limiter.limit("20/minute")
async def probe_camera(
    request: Request,
    camera_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: ProbeDep,
    body: PtzProbeIn | None = None,
) -> PtzProbeOut:
    """Ulanish, login/parol va PTZ imkoniyatlarini tekshiradi. ptz_enabled
    shart EMAS — aynan yoqishdan oldin tekshirish uchun."""
    camera = await _get_camera(db, camera_id, current_user)
    body = body or PtzProbeIn()
    target = _target(
        camera,
        protocol=body.protocol or "",
        port=body.onvif_port,
        username=body.username or None,
        password=body.password or None,
    )
    result = await ptz_service.probe(target)
    # Protokol bo'yicha ONVIF keshi sinov qiymatlari bilan qolib ketmasin.
    ptz_service.invalidate_camera(str(camera.id))
    return _probe_out(result)


@router.post("/{camera_id}/ptz/move", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("300/minute")
async def move_camera(
    request: Request,
    camera_id: str,
    body: PtzMoveIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: PtzDep,
) -> Response:
    """Tugma bosib turilganda panel har ~1 soniyada qayta yuboradi, shuning
    uchun chegara (300/daqiqa) bir nechta operatorga bemalol yetadi, lekin
    kamerani so'rovlar bilan "ko'mib" tashlashga yo'l qo'ymaydi."""
    _, target = await _enabled_target(db, camera_id, current_user)
    try:
        await ptz_service.move(target, body.pan, body.tilt, body.zoom, body.duration_ms)
    except ptz_service.PtzError as exc:
        raise _http_error(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{camera_id}/ptz/stop", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("300/minute")
async def stop_camera(
    request: Request,
    camera_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: PtzDep,
) -> Response:
    _, target = await _enabled_target(db, camera_id, current_user)
    try:
        await ptz_service.stop(target)
    except ptz_service.PtzError as exc:
        raise _http_error(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{camera_id}/ptz/presets", response_model=list[PtzPresetOut])
async def list_presets(
    camera_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: PtzDep,
) -> list[PtzPresetOut]:
    _, target = await _enabled_target(db, camera_id, current_user)
    try:
        presets = await ptz_service.get_presets(target)
    except ptz_service.PtzError as exc:
        raise _http_error(exc) from None
    return [PtzPresetOut(token=p.token, name=p.name) for p in presets]


@router.post("/{camera_id}/ptz/presets/{preset_token}/goto", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("60/minute")
async def goto_preset(
    request: Request,
    camera_id: str,
    preset_token: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: PtzDep,
) -> Response:
    if not preset_token or len(preset_token) > 64:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Preset identifikatori noto'g'ri")
    _, target = await _enabled_target(db, camera_id, current_user)
    try:
        await ptz_service.goto_preset(target, preset_token)
    except ptz_service.PtzError as exc:
        raise _http_error(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{camera_id}/ptz/presets", response_model=PtzPresetOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def save_preset(
    request: Request,
    camera_id: str,
    body: PtzPresetIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: PtzDep,
) -> PtzPresetOut:
    """Kameraning HOZIRGI holatini yangi nomli preset sifatida saqlaydi."""
    camera, target = await _enabled_target(db, camera_id, current_user)
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Preset nomini kiriting")
    try:
        preset = await ptz_service.set_preset(target, name)
    except ptz_service.PtzError as exc:
        raise _http_error(exc) from None
    await log_action(
        db,
        request,
        current_user.id,
        f"PTZ preset saqladi: {camera.name} — «{preset.name}» (#{preset.token})",
        "Kameralar",
    )
    await db.commit()
    return PtzPresetOut(token=preset.token, name=preset.name)
