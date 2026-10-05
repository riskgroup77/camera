"""Kameralar salomatligi — /api/kamera-salomatligi.

  GET /                      — har bir faol kamera: holat, uptime (24s/7k),
      uzilishlar soni, jonli/yozuv yo'li, yozuv bitreyti, AI oxirgi tahlili
      va umumiy xulosa.
  GET /{camera_id}/uzilishlar — kameraning uzilishlar tarixi (drawer uchun).

Uzilishlarni app/jobs/camera_health.py yozadi; hisob-kitoblar —
app/services/camera_health_dashboard.py.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.jobs.camera_health import is_reachable, is_video_flowing
from app.models import Camera, CameraOutage
from app.schemas.base import CamelModel
from app.services import camera_health_dashboard as dash
from app.services import runtime_snapshot
from app.services.access_scope import camera_filter, ensure_camera_allowed
from app.services.recording import rec_path_name
from app.services.video_gateway import _path_name

router = APIRouter(prefix="/api/kamera-salomatligi", tags=["kamera-salomatligi"])

# Tizim sozlamalari egasi ham, kameralarni joyida tuzatadigan kamera
# mas'uli ham shu ro'yxatga qaraydi — qaysi kamera o'chiqligini bilish
# ikkalasining ham ishi.
HealthDep = Annotated[CurrentUser, Depends(require_permission("systemSettings", "editCameraLocation"))]
DbDep = Annotated[AsyncSession, Depends(get_db)]

CameraState = Literal["online", "offline", "no_video"]


class CameraHealthOut(CamelModel):
    id: str
    name: str
    building: str | None = None
    floor: int | None = None
    ip: str
    status: CameraState
    last_seen_at: datetime | None = None
    last_frame_at: datetime | None = None
    offline_since: datetime | None = None
    uptime_day: float
    uptime_week: float
    outages_week: int
    # None — MediaMTX'dan javob yo'q (noma'lum), False — yo'l tayyor emas.
    live_ready: bool | None = None
    recording_ready: bool | None = None
    recording_mbps: float | None = None
    ai_last_analyzed_at: datetime | None = None
    ai_stream: str | None = None


class SummaryOut(CamelModel):
    total: int
    online: int
    offline: int
    no_video: int
    avg_uptime_day: float | None = None
    recording: int | None = None


class DashboardOut(CamelModel):
    generated_at: datetime
    mediamtx_reachable: bool
    recording_enabled: bool
    summary: SummaryOut
    cameras: list[CameraHealthOut]


class OutageOut(CamelModel):
    id: str
    started_at: datetime
    ended_at: datetime | None = None
    duration_seconds: int
    reason: str


class OutageListOut(CamelModel):
    camera_id: str
    camera_name: str
    days: int
    items: list[OutageOut]


def _state(camera: Camera) -> CameraState:
    if not is_reachable(camera.last_seen_at):
        return "offline"
    if not is_video_flowing(camera.last_frame_at):
        return "no_video"
    return "online"


@router.get("", response_model=DashboardOut)
async def camera_health_dashboard(user: HealthDep, db: DbDep) -> DashboardOut:
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    day_ago = now - timedelta(days=1)

    cameras = (
        (
            await db.execute(
                select(Camera).where(Camera.status == "faol").where(camera_filter(user)).order_by(Camera.name)
            )
        ).scalars().unique().all()
    )
    outages = (
        (
            await db.execute(
                select(CameraOutage).where(
                    CameraOutage.camera_id.in_([c.id for c in cameras]),
                    or_(CameraOutage.ended_at.is_(None), CameraOutage.ended_at > week_ago),
                )
            )
        )
        .scalars()
        .all()
        if cameras
        else []
    )
    by_camera: dict[uuid.UUID, list[CameraOutage]] = {}
    for outage in outages:
        by_camera.setdefault(outage.camera_id, []).append(outage)

    # MediaMTX va AI surati bir vaqtda — ikkalasi ham tarmoq so'rovi.
    paths, views = await asyncio.gather(dash.fetch_mediamtx_paths(), _safe_views())

    rows: list[CameraHealthOut] = []
    for camera in cameras:
        camera_id = str(camera.id)
        own = by_camera.get(camera.id, [])
        intervals = [(o.started_at, o.ended_at) for o in own]
        created = camera.created_at or week_ago
        open_starts = [o.started_at for o in own if o.ended_at is None]

        live_ready: bool | None = None
        rec_ready: bool | None = None
        rec_mbps: float | None = None
        if paths is not None:
            live = paths.get(_path_name(camera_id))
            rec = paths.get(rec_path_name(camera_id))
            live_ready = bool(live and live.ready)
            rec_ready = bool(rec and rec.ready)
            if rec is not None and rec.ready:
                rec_mbps = dash.bitrate_mbps(rec_path_name(camera_id), rec.bytes_received)

        view = views.get(camera_id)
        rows.append(
            CameraHealthOut(
                id=camera_id,
                name=camera.name,
                building=camera.building.name if camera.building else None,
                floor=camera.floor,
                ip=camera.ip,
                status=_state(camera),
                last_seen_at=camera.last_seen_at,
                last_frame_at=camera.last_frame_at,
                offline_since=min(open_starts) if open_starts else None,
                # Kamera oynadan keyin qo'shilgan bo'lsa, undan oldingi
                # vaqt "ishlagan" ham, "ishlamagan" ham emas — hisobga kirmaydi.
                uptime_day=dash.uptime_percent(intervals, max(day_ago, created), now),
                uptime_week=dash.uptime_percent(intervals, max(week_ago, created), now),
                outages_week=len(own),
                live_ready=live_ready,
                recording_ready=rec_ready,
                recording_mbps=rec_mbps,
                ai_last_analyzed_at=view.last_frame_at if view else None,
                ai_stream=view.stream if view else None,
            )
        )

    summary = SummaryOut(
        total=len(rows),
        online=sum(1 for r in rows if r.status == "online"),
        offline=sum(1 for r in rows if r.status == "offline"),
        no_video=sum(1 for r in rows if r.status == "no_video"),
        avg_uptime_day=round(sum(r.uptime_day for r in rows) / len(rows), 2) if rows else None,
        recording=sum(1 for r in rows if r.recording_ready) if paths is not None else None,
    )
    return DashboardOut(
        generated_at=now,
        mediamtx_reachable=paths is not None,
        recording_enabled=settings.recording_enabled,
        summary=summary,
        cameras=rows,
    )


async def _safe_views() -> dict:
    try:
        return await runtime_snapshot.load_recognition_views()
    except Exception:
        # AI surati yo'q (Redis o'chiq) — panelning qolgan qismi ishlayversin.
        return {}


@router.get("/{camera_id}/uzilishlar", response_model=OutageListOut)
async def camera_outages(
    camera_id: uuid.UUID,
    user: HealthDep,
    db: DbDep,
    days: Annotated[int, Query(alias="kun", ge=1, le=90)] = 30,
) -> OutageListOut:
    camera = await db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera topilmadi")
    ensure_camera_allowed(user, camera)
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    result = await db.execute(
        select(CameraOutage)
        .where(
            CameraOutage.camera_id == camera_id,
            or_(CameraOutage.ended_at.is_(None), CameraOutage.ended_at > since),
        )
        .order_by(CameraOutage.started_at.desc())
        .limit(200)
    )
    items = [
        OutageOut(
            id=str(o.id),
            started_at=o.started_at,
            ended_at=o.ended_at,
            duration_seconds=int(((o.ended_at or now) - o.started_at).total_seconds()),
            reason=o.reason,
        )
        for o in result.scalars().all()
    ]
    return OutageListOut(camera_id=str(camera_id), camera_name=camera.name, days=days, items=items)
