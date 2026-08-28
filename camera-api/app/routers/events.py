from typing import Annotated

import jwt
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, get_current_user
from app.models import Camera, Event, User
from app.pagination import Page, PageParams, build_page, paginate
from app.schemas.event import EventCreateIn, EventOut, EventReviewIn
from app.security import decode_access_token
from app.storage import presigned_url
from app.timezone import local_now
from app.ws import manager

router = APIRouter(tags=["events"])


def _to_out(event: Event) -> EventOut:
    return EventOut(
        id=str(event.id),
        timestamp=event.occurred_at.strftime("%Y-%m-%d %H:%M"),
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


@router.websocket("/ws/events")
async def events_websocket(websocket: WebSocket) -> None:
    """Real-time push for new AI events — replaces the frontend's
    setInterval-based simulation (camera/src/lib/realtime.ts) with an
    actual persistent connection. Auth via ?token=<jwt> since browser
    WebSocket APIs can't set an Authorization header."""
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return
    try:
        decode_access_token(token)
    except jwt.PyJWTError:
        await websocket.close(code=4401)
        return

    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # no client->server protocol yet; just detect disconnects
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@router.get("/api/events", response_model=Page[EventOut])
async def list_events(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(get_current_user)],
    page_params: Annotated[PageParams, Depends()],
    severity: Annotated[str | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query()] = None,
    today: Annotated[bool, Query()] = False,
) -> Page[EventOut]:
    stmt = select(Event).order_by(Event.occurred_at.desc())
    if severity:
        stmt = stmt.where(Event.severity == severity)
    if status_filter:
        stmt = stmt.where(Event.status == status_filter)
    if search:
        stmt = stmt.where(Event.module_name.ilike(f"%{search}%"))
    if today:
        # "Today" means the institute's local calendar day, not UTC's —
        # see app/timezone.py's module docstring for why that distinction
        # is a real bug, not pedantry (near-midnight local time, a plain
        # UTC "today" is off by a day).
        start_of_today = local_now().replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = stmt.where(Event.occurred_at >= start_of_today)

    records, total = await paginate(db, stmt, page_params)
    items = [_to_out(e) for e in records]
    return build_page(items, total, page_params)


@router.post("/api/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def create_event(
    body: EventCreateIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> EventOut:
    result = await db.execute(select(Camera).options(selectinload(Camera.building)).where(Camera.id == body.camera_id))
    camera = result.scalar_one_or_none()
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi")

    event = Event(
        camera_id=camera.id,
        camera_name=camera.name,
        building=camera.building.name if camera.building else "",
        module_code=body.module_code,
        module_name=body.module_name,
        group=body.group,
        confidence=body.confidence,
        severity=body.severity,
        person_name=body.person_name,
        status="yangi",
    )
    db.add(event)
    await log_action(db, request, current_user.id, f"Yangi AI hodisa: {body.module_name}", "AI Modullari")
    await db.commit()
    await db.refresh(event)

    out = _to_out(event)
    await manager.broadcast(out.model_dump(by_alias=True))
    return out


@router.delete("/api/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hodisa topilmadi")

    await log_action(db, request, current_user.id, f"Hodisani o'chirdi: {event.module_name}", "AI Modullari")
    await db.delete(event)
    await db.commit()


@router.patch("/api/events/{event_id}/review", response_model=EventOut)
async def review_event(
    event_id: str,
    body: EventReviewIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> EventOut:
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hodisa topilmadi")

    event.status = body.status
    reviewer = await db.get(User, current_user.id)
    event.reviewed_by = reviewer.full_name if reviewer else None

    await log_action(db, request, current_user.id, f"Hodisani ko'rib chiqdi: {body.status}", "AI Modullari")
    await db.commit()
    await db.refresh(event)

    out = _to_out(event)
    await manager.broadcast(out.model_dump(by_alias=True))
    return out
