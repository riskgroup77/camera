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

Uch himoya shu yerda (2026-09):
- Sinov rejimi: modul `sinov` bo'lsa signal yoziladi (is_trial), lekin
  operatorlarga yuborilmaydi — navbat, ogohlantirish va hisobotlar uni
  ko'rmaydi. Aniqlik namunalarni baholash orqali o'lchanadi.
- Tezlik chegarasi: shaxsi aniqlanmagan signallar kamera×modul va modul
  bo'yicha soatlik chegaradan oshsa yozilmaydi.
- Dalil: `details` (sabab va o'lchangan qiymatlar) saqlanadi, snapshot
  ustiga ramka/zona chiziladi (app/services/evidence.py).
"""

import asyncio
import logging
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AIModuleConfig, Camera, Event
from app.schemas.event import EventOut
from app.services.event_status import OPEN_STATUSES
from app.services.evidence import Shape, annotate_snapshot
from app.services.notifications import notify_event
from app.services.sop import default_steps, resolve_steps
from app.storage import presigned_url, upload_file
from app.timezone import to_local
from app.ws import manager

logger = logging.getLogger("app.event_bus")

# Tezlik chegarasi sabab yozilmagan signallar (modul kodi bo'yicha, jarayon
# ishga tushgandan beri) — AI Modullari sahifasida ko'rsatiladi.
_rate_limited: Counter[int] = Counter()


def rate_limited_counts() -> dict[int, int]:
    return dict(_rate_limited)


def reset_rate_limited_for_tests() -> None:
    _rate_limited.clear()


def sla_due_at(severity: str, occurred_at: datetime) -> datetime | None:
    """Og'irlik bo'yicha hal qilish muddati (settings.event_sla_minutes_*)."""
    minutes = {
        "yuqori": settings.event_sla_minutes_high,
        "o'rta": settings.event_sla_minutes_medium,
        "past": settings.event_sla_minutes_low,
    }.get(severity, 0)
    if minutes <= 0:
        return None
    return occurred_at + timedelta(minutes=minutes)


def _iso(moment: datetime | None) -> str | None:
    return to_local(moment).isoformat(timespec="seconds") if moment else None


def event_to_out(
    event: Event,
    *,
    assignee_name: str | None = None,
    comments_count: int | None = None,
    now: datetime | None = None,
    sop: list[str] | None = None,
) -> EventOut:
    """Event → API javobi. Routerlar va sweeplar bitta shakldan foydalanadi.

    Tayinlangan foydalanuvchi ismi va izohlar soni boshqa jadvallarda —
    chaqiruvchi ularni (ro'yxat uchun bitta so'rovda) o'zi olib beradi.
    "overdue" — muddat o'tgan va hali qaror qilinmagan (yangi/jarayonda).
    `sop` berilmasa (bazaga murojaat qilmaydigan chaqiruvchilar) — modulning
    standart ko'rsatmasi."""
    now = now or datetime.now(timezone.utc)
    overdue = bool(event.due_at and event.status in OPEN_STATUSES and event.due_at < now)
    return EventOut(
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
        clip_url=presigned_url(event.clip_key) if getattr(event, "clip_key", None) else None,
        occurred_at=to_local(event.occurred_at).isoformat(timespec="seconds"),
        reviewed_at=to_local(event.reviewed_at).strftime("%Y-%m-%d %H:%M") if event.reviewed_at else None,
        is_trial=bool(event.is_trial),
        details=event.details,
        assigned_to_id=str(event.assigned_to_id) if event.assigned_to_id else None,
        assigned_to_name=assignee_name if event.assigned_to_id else None,
        assigned_at=_iso(event.assigned_at),
        due_at=_iso(event.due_at),
        overdue=overdue,
        escalated_at=_iso(event.escalated_at),
        resolved_at=_iso(event.resolved_at),
        resolved_by=event.resolved_by,
        resolution_note=event.resolution_note,
        comments_count=comments_count,
        sop=sop if sop is not None else default_steps(event.module_code),
    )


async def _save_snapshot(frame_bytes: bytes | None, annotations: Sequence[Shape] | None = None) -> str | None:
    if not frame_bytes:
        return None
    try:
        if annotations:
            frame_bytes = await asyncio.to_thread(annotate_snapshot, frame_bytes, annotations)
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


async def _over_rate_limit(db: AsyncSession, camera: Camera, module_code: int, *, is_trial: bool) -> bool:
    """Soatlik chegara. Sinov signallari uchun chegara ancha past: u yerda
    maqsad aniqlikni o'lchash uchun namuna yig'ish, hamma holatni yozish emas."""
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    camera_limit = (
        settings.trial_events_per_camera_hour if is_trial else settings.event_rate_limit_per_camera_hour
    )
    module_limit = (
        settings.trial_events_per_module_hour if is_trial else settings.event_rate_limit_per_module_hour
    )
    per_camera = (
        await db.scalar(
            select(func.count())
            .select_from(Event)
            .where(Event.camera_id == camera.id)
            .where(Event.module_code == module_code)
            .where(Event.is_trial.is_(is_trial))
            .where(Event.occurred_at >= since)
        )
        or 0
    )
    if per_camera >= camera_limit:
        return True
    per_module = (
        await db.scalar(
            select(func.count())
            .select_from(Event)
            .where(Event.module_code == module_code)
            .where(Event.is_trial.is_(is_trial))
            .where(Event.occurred_at >= since)
        )
        or 0
    )
    return per_module >= module_limit


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
    details: dict | None = None,
    annotations: Sequence[Shape] | None = None,
) -> Event | None:
    """Creates, commits, and broadcasts one Event, with a snapshot of
    `frame_bytes` if given. Caller is responsible for its own dedup check
    (e.g. _recently_flagged) before calling this.

    Returns None when the module's configured threshold rejects the
    detection. Before this, AIModuleConfig.threshold was written by the
    admin panel and read back by it, and NOTHING else ever looked at it —
    the "sezgirlik" control was decorative. Production proof at the time:
    every single event of modules 1, 5, 17 and 25 sat below its own
    module's threshold (134/134, 28/28, 84/84, 4/4), which is impossible
    if the number means anything.

    Note what the threshold can and cannot do. Several modules report a
    CONSTANT confidence (see the comments beside each `confidence=` — they
    are honest self-assessments of coarse heuristics, not measurements),
    so for those the threshold acts as an on/off switch rather than a
    sensitivity dial: set it above the constant and the module goes
    quiet. That is a real, useful control, but it is not a gradual one,
    and pretending otherwise in the UI would be the same lie in a new
    place.

    Also returns None when the hourly rate limit is exceeded — only for
    detections without an identified person: a sleeping student or an
    off-hours entry names someone specific, a heuristic burst does not.
    """
    config = (
        await db.execute(
            select(AIModuleConfig.threshold, AIModuleConfig.mode, AIModuleConfig.sop).where(
                AIModuleConfig.code == module_code
            )
        )
    ).one_or_none()
    threshold, mode = (config.threshold, config.mode) if config is not None else (None, "ishchi")
    sop_steps = resolve_steps(module_code, config.sop if config is not None else None)
    if threshold is not None and confidence < threshold:
        logger.info(
            "event suppressed by module threshold",
            extra={
                "module_code": module_code,
                "confidence": confidence,
                "threshold": threshold,
                "camera": camera.name,
            },
        )
        return None

    is_trial = mode == "sinov"
    # Shaxsi aniqlangan ishchi signal (uxlagan talaba, ish vaqtidan tashqari
    # kirgan xodim) cheklanmaydi — har biri alohida odam haqida. Sinov
    # signallari esa har doim kvota ostida: ular faqat namuna.
    if (is_trial or person_name is None) and await _over_rate_limit(db, camera, module_code, is_trial=is_trial):
        _rate_limited[module_code] += 1
        logger.info(
            "event suppressed by rate limit",
            extra={"module_code": module_code, "camera": camera.name, "trial": is_trial},
        )
        return None

    snapshot_key = await _save_snapshot(frame_bytes, annotations)
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
        is_trial=is_trial,
        details=details,
        due_at=None if is_trial else sla_due_at(severity, datetime.now(timezone.utc)),
    )
    db.add(event)
    await db.flush()
    event_out = event_to_out(event, sop=sop_steps)
    await db.commit()
    # Sinov signali operatorlarga yuborilmaydi: monitoring devori, signal
    # paneli va Hodisalar navbati uni ko'rsatmasligi kerak.
    if not is_trial:
        await manager.broadcast(event_out.model_dump(by_alias=True))
        await notify_event(event)
    return event


#: Kunlik video tahlil yaratgan hodisalar belgisi (details["source"]) — kunni
#: qayta hisoblashda oldingilari shu bo'yicha o'chiriladi.
VIDEO_ANALYSIS_SOURCE = "video_tahlil"


async def create_analysis_event(
    db: AsyncSession,
    *,
    camera: Camera | None,
    module_code: int,
    confidence: int,
    severity: str,
    occurred_at: datetime,
    person_name: str | None = None,
    details: dict | None = None,
    snapshot_key: str | None = None,
    module: AIModuleConfig | None = None,
) -> Event | None:
    """Kunlik tahlil hodisasi (app/batch/aggregate.py).

    raise_event'dan farqi: vaqt — videodagi payt (hozir emas); real vaqt
    uchun mo'ljallangan soatlik tezlik chegarasi qo'llanmaydi (hamma
    hodisa bir lahzada yaratiladi, cheklovni kunlik tahlilning o'zi
    qo'yadi); jonli lentaga (WebSocket) va Telegram'ga har biri alohida
    yuborilmaydi — tahlil oxirida bitta xulosa yuboriladi. Modul
    chegarasi (threshold) va sinov rejimi odatdagidek ishlaydi. Commit
    qilmaydi."""
    config = module
    if config is None:
        config = (
            await db.execute(select(AIModuleConfig).where(AIModuleConfig.code == module_code))
        ).scalar_one_or_none()
    if config is None or not config.active:
        return None
    if confidence < config.threshold:
        return None
    is_trial = config.mode == "sinov"
    event = Event(
        occurred_at=occurred_at,
        camera_id=camera.id if camera is not None else None,
        camera_name=camera.name if camera is not None else "",
        building=camera.building.name if camera is not None and camera.building else "",
        module_code=module_code,
        module_name=config.name,
        group=config.group,
        confidence=confidence,
        severity=severity,
        status="yangi",
        person_name=person_name,
        snapshot_key=snapshot_key,
        is_trial=is_trial,
        details={**(details or {}), "source": VIDEO_ANALYSIS_SOURCE},
        due_at=None if is_trial else sla_due_at(severity, datetime.now(timezone.utc)),
    )
    db.add(event)
    return event
