"""Single place every app/jobs/*.py sweep creates and broadcasts an
Event — was duplicated ~18 times (Event(...) -> db.add -> db.flush ->
EventOut(...) -> db.commit -> manager.broadcast) with only the module
code/name/group/confidence/severity actually varying per caller.

Also the one place a detection's snapshot gets saved: pass the frame
bytes that triggered the event and a human reviewing "Hodisalar jurnali"
sees what the AI actually saw, instead of the mock placeholder the admin
UI used to show (or a live feed of whatever's on camera *now*, which by
the time anyone reviews it has nothing to do with the original
detection). A missing/failed upload degrades to no snapshot, not a
failed sweep — see _save_snapshot.
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Camera, Event
from app.schemas.event import EventOut
from app.storage import presigned_url, upload_file
from app.timezone import to_local
from app.ws import manager

logger = logging.getLogger("app.event_bus")


async def _save_snapshot(frame_bytes: bytes | None) -> str | None:
    if not frame_bytes:
        return None
    try:
        # upload_file() is a synchronous boto3 call (real network I/O) —
        # off the event loop via to_thread, same reason every other
        # blocking model/storage call in app/jobs/*.py is wrapped this
        # way. Without it, one S3/MinIO round trip per event stalls every
        # other concurrent camera task and the WS/HTTP server.
        _file_id, key = await asyncio.to_thread(upload_file, frame_bytes, "snapshot.jpg", "image/jpeg", "events")
        return key
    except Exception:
        logger.exception("event snapshot upload failed")
        return None


async def raise_event(
    db: AsyncSession,
    *,
    camera: Camera,
    module_code: int,
    module_name: str,
    group: str,
    confidence: int,
    severity: str,
    frame_bytes: bytes | None = None,
    person_name: str | None = None,
) -> Event:
    """Creates, commits, and broadcasts one Event, with a snapshot of
    `frame_bytes` if given. Caller is responsible for its own dedup check
    (e.g. _recently_flagged) before calling this — this function always
    raises."""
    snapshot_key = await _save_snapshot(frame_bytes)
    event = Event(
        camera_id=camera.id,
        camera_name=camera.name,
        building=camera.building.name if camera.building else "",
        module_code=module_code,
        module_name=module_name,
        group=group,
        confidence=confidence,
        severity=severity,
        status="yangi",
        person_name=person_name,
        snapshot_key=snapshot_key,
    )
    db.add(event)
    await db.flush()
    event_out = EventOut(
        id=str(event.id),
        timestamp=to_local(event.occurred_at).strftime("%Y-%m-%d %H:%M"),
        camera_id=str(event.camera_id) if event.camera_id else "",
        camera_name=event.camera_name,
        building=event.building,
        module_code=event.module_code,
        module_name=event.module_name,
        group=event.group,
        confidence=event.confidence,
        severity=event.severity,
        status=event.status,
        person_name=event.person_name,
        reviewed_by=event.reviewed_by,
        snapshot_url=presigned_url(event.snapshot_key) if event.snapshot_key else None,
    )
    await db.commit()
    await manager.broadcast(event_out.model_dump(by_alias=True))
    return event
