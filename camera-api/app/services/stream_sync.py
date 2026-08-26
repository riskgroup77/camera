"""Keeps MediaMTX path registrations in sync with the database — used at
API startup (MediaMTX restart wipes in-memory paths while Camera.stream_url
rows survive in Postgres) and by the cameras admin router on create/update."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt
from app.models import Camera
from app.rtsp import build_rtsp_url
from app.services.video_gateway import register_camera_stream, unregister_camera_stream

logger = logging.getLogger("app.stream_sync")


async def sync_camera_stream(db: AsyncSession, camera: Camera) -> None:
    """Register or unregister one camera with MediaMTX and persist stream_url."""
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


async def sync_all_active_camera_streams(db: AsyncSession) -> tuple[int, int]:
    """Re-register every faol camera — call once on leader startup."""
    result = await db.execute(select(Camera).where(Camera.status == "faol"))
    cameras = result.scalars().all()
    ok = 0
    failed = 0
    for camera in cameras:
        try:
            await sync_camera_stream(db, camera)
            ok += 1
            logger.info(
                "startup stream sync ok",
                extra={"camera_id": str(camera.id), "camera_name": camera.name},
            )
        except Exception:
            failed += 1
            logger.exception(
                "startup stream sync failed",
                extra={"camera_id": str(camera.id), "camera_name": camera.name},
            )
    return ok, failed
