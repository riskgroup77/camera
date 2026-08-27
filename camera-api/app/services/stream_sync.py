"""Keeps MediaMTX path registrations in sync with the database — used at
API startup (MediaMTX restart wipes in-memory paths while Camera.stream_url
rows survive in Postgres) and by the cameras admin router on create/update."""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto import decrypt
from app.models import Camera
from app.rtsp import build_rtsp_url
from app.services.video_gateway import register_camera_stream, unregister_camera_stream

logger = logging.getLogger("app.stream_sync")


def _rtsp_url_for(camera: Camera) -> str:
    return build_rtsp_url(
        camera.ip,
        camera.port,
        camera.rtsp_path,
        decrypt(camera.rtsp_username) if camera.rtsp_username else None,
        decrypt(camera.rtsp_password) if camera.rtsp_password else None,
    )


async def _register_faol_stream(camera: Camera) -> str:
    return await register_camera_stream(str(camera.id), _rtsp_url_for(camera))


async def sync_camera_stream(db: AsyncSession, camera: Camera) -> None:
    """Register or unregister one camera with MediaMTX and persist stream_url."""
    if camera.status == "faol":
        camera.stream_url = await _register_faol_stream(camera)
    elif camera.stream_url is not None:
        await unregister_camera_stream(str(camera.id))
        camera.stream_url = None
    await db.commit()
    await db.refresh(camera, attribute_names=["building"])


async def sync_all_active_camera_streams(db: AsyncSession) -> tuple[int, int]:
    """Re-register every faol camera — parallel MediaMTX calls, one DB commit."""
    result = await db.execute(select(Camera).where(Camera.status == "faol"))
    cameras = result.scalars().all()
    if not cameras:
        return 0, 0

    semaphore = asyncio.Semaphore(settings.stream_sync_concurrency)

    async def _sync_one(camera: Camera) -> tuple[Camera, str | None]:
        async with semaphore:
            try:
                url = await _register_faol_stream(camera)
                return camera, url
            except Exception:
                logger.exception(
                    "startup stream sync failed",
                    extra={"camera_id": str(camera.id), "camera_name": camera.name},
                )
                return camera, None

    outcomes = await asyncio.gather(*(_sync_one(camera) for camera in cameras))

    ok = 0
    failed = 0
    for camera, url in outcomes:
        if url is None:
            failed += 1
            continue
        camera.stream_url = url
        ok += 1
        logger.info(
            "startup stream sync ok",
            extra={"camera_id": str(camera.id), "camera_name": camera.name},
        )

    await db.commit()
    return ok, failed
