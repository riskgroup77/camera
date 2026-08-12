"""Background camera reachability sweep.

Closes a real gap: Camera.status is a manually-set admin field ("this
camera should be active") that never reflects reality if the camera
actually goes offline — cable unplugged, IP changed, device powered off.
Before this, the Monitoring page's "Oflayn" count and the admin table's
status badge were both just echoing whatever an operator last typed in,
not anything observed. This runs a lightweight TCP check against every
'faol' camera on a timer and stamps last_seen_at on success;
is_reachable() below is computed from how fresh that stamp is and is what
app/routers/cameras.py and app/routers/public.py actually expose.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal
from app.models import Camera
from app.services.connectivity import tcp_check

logger = logging.getLogger("app.camera_health")

# Same rationale as app/jobs/attendance_ai.py's _camera_semaphore: a
# sequential TCP check per camera means a full sweep takes N times one
# camera's timeout at N cameras — at 400 cameras with even a few offline
# (each eating a real connect timeout), that adds up fast. tcp_check() is
# pure socket I/O, not CPU/DB work, so these can safely run concurrently
# against the same `db` session below — the ORM mutations happen after
# gather() completes, not while it's running.
_health_semaphore = asyncio.Semaphore(settings.ai_sweep_camera_concurrency)


def is_reachable(last_seen_at: datetime | None) -> bool:
    if last_seen_at is None:
        return False
    return (datetime.now(timezone.utc) - last_seen_at) < timedelta(
        seconds=settings.camera_health_freshness_seconds
    )


async def _check_one(camera: Camera) -> tuple[bool, float]:
    async with _health_semaphore:
        return await tcp_check(camera.ip, camera.port)


async def run_camera_health_sweep_once(db: AsyncSession) -> int:
    """Checks every 'faol' camera CONCURRENTLY (bounded by
    _health_semaphore), stamps last_seen_at on the reachable ones. Returns
    how many were reachable this sweep (for logging)."""
    result = await db.execute(select(Camera).where(Camera.status == "faol"))
    cameras = result.scalars().all()

    now = datetime.now(timezone.utc)
    results = await asyncio.gather(*(_check_one(camera) for camera in cameras), return_exceptions=True)

    reachable_count = 0
    for camera, outcome in zip(cameras, results, strict=True):
        if isinstance(outcome, BaseException):
            logger.exception("camera health check failed", extra={"camera_id": str(camera.id)}, exc_info=outcome)
            continue
        ok, _latency_ms = outcome
        if ok:
            camera.last_seen_at = now
            reachable_count += 1
    await db.commit()
    return reachable_count


async def camera_health_loop() -> None:
    """Runs forever. An immediate first pass at startup (rather than waiting
    a full interval) means genuinely-live cameras don't read as "offline"
    for up to camera_health_interval_seconds right after a restart."""
    while True:
        try:
            async with SessionLocal() as db:
                count = await run_camera_health_sweep_once(db)
                logger.info("camera health sweep complete", extra={"reachable": count})
        except Exception:
            logger.exception("camera health sweep failed")
        await asyncio.sleep(settings.camera_health_interval_seconds)
