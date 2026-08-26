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

When a camera stays unreachable longer than camera_offline_alert_minutes,
an AuditLog alert is written once (deduplicated per outage) so admins
can spot chronic network failures without watching the monitoring page.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal
from app.jobs.sweep_guard import SweepGuard
from app.models import AuditLog, Camera
from app.services.connectivity import tcp_check

logger = logging.getLogger("app.camera_health")

_health_semaphore = asyncio.Semaphore(settings.ai_sweep_camera_concurrency)
_sweep_guard = SweepGuard("camera_health")

# camera_id -> UTC moment when the current offline streak started
_offline_since: dict[str, datetime] = {}
# camera_ids that already received an alert for the current offline streak
_alerted: set[str] = set()


def is_reachable(last_seen_at: datetime | None) -> bool:
    if last_seen_at is None:
        return False
    return (datetime.now(timezone.utc) - last_seen_at) < timedelta(
        seconds=settings.camera_health_freshness_seconds
    )


async def _check_one(camera: Camera) -> tuple[bool, float]:
    async with _health_semaphore:
        return await tcp_check(camera.ip, camera.port)


async def _maybe_raise_offline_alert(db: AsyncSession, camera: Camera, offline_since: datetime) -> None:
    alert_minutes = settings.camera_offline_alert_minutes
    if alert_minutes <= 0:
        return
    camera_id = str(camera.id)
    if camera_id in _alerted:
        return
    if datetime.now(timezone.utc) - offline_since < timedelta(minutes=alert_minutes):
        return

    _alerted.add(camera_id)
    message = (
        f"Kamera {alert_minutes} daqiqadan beri javob bermayapti: "
        f"{camera.name} ({camera.ip}:{camera.port})"
    )
    logger.warning(
        "camera offline alert",
        extra={
            "camera_id": camera_id,
            "camera_name": camera.name,
            "ip": camera.ip,
            "port": camera.port,
            "offline_since": offline_since.isoformat(),
        },
    )
    db.add(
        AuditLog(
            user_id=None,
            user_name="Kamera monitoring",
            action=message,
            module="Kameralar",
            status="xavfli",
            ip="internal",
        )
    )


def _track_offline_camera(camera: Camera, now: datetime) -> datetime:
    camera_id = str(camera.id)
    if camera_id not in _offline_since:
        _offline_since[camera_id] = now
    return _offline_since[camera_id]


def _mark_camera_online(camera: Camera) -> None:
    camera_id = str(camera.id)
    _offline_since.pop(camera_id, None)
    _alerted.discard(camera_id)


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
            offline_since = _track_offline_camera(camera, now)
            await _maybe_raise_offline_alert(db, camera, offline_since)
            continue
        ok, _latency_ms = outcome
        if ok:
            camera.last_seen_at = now
            _mark_camera_online(camera)
            reachable_count += 1
        else:
            offline_since = _track_offline_camera(camera, now)
            await _maybe_raise_offline_alert(db, camera, offline_since)
    await db.commit()
    return reachable_count


async def camera_health_loop() -> None:
    """Runs forever. An immediate first pass at startup (rather than waiting
    a full interval) means genuinely-live cameras don't read as "offline"
    for up to camera_health_interval_seconds right after a restart."""
    while True:
        try:

            async def _tick() -> int:
                async with SessionLocal() as db:
                    return await run_camera_health_sweep_once(db)

            count = await _sweep_guard.run(_tick)
            if count is not None:
                logger.info("camera health sweep complete", extra={"reachable": count})
        except Exception:
            logger.exception("camera health sweep failed")
        await asyncio.sleep(settings.camera_health_interval_seconds)
