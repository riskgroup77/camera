"""Prometheus /metrics endpointi.

Prometheus (deploy/monitoring/) shu yerdan har 30 soniyada o'qiydi. Ikki xil
ko'rsatkich beriladi:

* jarayon ko'rsatkichlari (prometheus_client standarti: CPU, xotira, ochiq
  fayllar, GC) — so'rov tushgan uvicorn jarayoniniki;
* tizim holati (kameralar, hodisalar, davomat, turniket, xabarlar, AI) —
  so'rov paytida bazadan arzon agregat so'rovlar bilan hisoblanadi va
  CACHE_TTL_SECONDS davomida keshlanadi. Bir nechta Prometheus yoki
  bir nechta worker bazani ortiqcha yuklamaydi.

Himoya: settings.metrics_token bo'lsa "Authorization: Bearer <token>"
talab qilinadi. Bo'sh bo'lsa — faqat ichki tarmoq (loopback/private IP)
dan; nginx orqali kelgan so'rovda X-Forwarded-For/X-Real-IP dagi manzil
ham ichki bo'lishi shart. nginx /metrics ni tashqariga umuman ochmaydi
(deploy/nginx/cam-fermi-api.conf) — bu ikkinchi qatlam.
"""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import logging
import os
import time
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, CollectorRegistry, generate_latest
from prometheus_client.core import GaugeMetricFamily, InfoMetricFamily
from prometheus_client.registry import Collector
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.jobs.camera_health import is_reachable, is_video_flowing
from app.models import AccessEvent, AttendanceRecord, Camera, Event, NotificationLog
from app.timezone import INSTITUTE_TZ, local_now
from app.timezone import business_today

logger = logging.getLogger("app.metrics")

router = APIRouter(tags=["metrics"])

PREFIX = "sm"
CACHE_TTL_SECONDS = 15.0
# Redis'dagi AI surati sekin javob bersa scrape osilib qolmasin.
AI_SNAPSHOT_TIMEOUT_SECONDS = 3.0
OPEN_STATUSES = ("yangi", "jarayonda")

_cache: tuple[float, list] | None = None
_cache_lock = asyncio.Lock()


def reset_metrics_cache() -> None:
    """Keshni tozalash (testlar va sozlama o'zgarganda)."""
    global _cache
    _cache = None


# ----------------------------------------------------------------------
# Kirish nazorati
# ----------------------------------------------------------------------


# Aniq ro'yxat: ipaddress.is_private hujjat tarmoqlarini (203.0.113.0/24 va
# h.k.) ham "private" deydi — bizga faqat haqiqiy ichki tarmoqlar kerak.
_INTERNAL_NETWORKS = tuple(
    ipaddress.ip_network(net)
    for net in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7")
)


def _is_internal_ip(value: str | None) -> bool:
    if not value:
        return False
    try:
        ip = ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip in net for net in _INTERNAL_NETWORKS if net.version == ip.version)


def _forwarded_addresses(request: Request) -> list[str]:
    addresses: list[str] = []
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        addresses.extend(part.strip() for part in forwarded_for.split(",") if part.strip())
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        addresses.append(real_ip.strip())
    return addresses


async def _authorize(request: Request) -> None:
    if not settings.metrics_enabled:
        # Endpoint "yo'q" — o'chirilganini ham oshkor qilmaymiz.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    token = settings.metrics_token.strip()
    if token:
        header = request.headers.get("authorization", "")
        scheme, _, supplied = header.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.strip().encode(), token.encode()):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Metrics token noto'g'ri",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return

    client_host = request.client.host if request.client else None
    addresses = [client_host, *_forwarded_addresses(request)]
    if not all(_is_internal_ip(address) for address in addresses):
        logger.warning("metrics request rejected", extra={"client_ip": client_host})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="/metrics faqat ichki tarmoqdan (yoki METRICS_TOKEN bilan) ochiladi",
        )


# ----------------------------------------------------------------------
# Tizim holati
# ----------------------------------------------------------------------


def _gauge(name: str, documentation: str, labels: Iterable[str] = ()) -> GaugeMetricFamily:
    return GaugeMetricFamily(f"{PREFIX}_{name}", documentation, labels=list(labels))


async def _camera_families(db: AsyncSession) -> list:
    by_status = _gauge("cameras", "Kameralar soni holat bo'yicha (faol/nofaol/...)", ["status"])
    total = 0
    rows = await db.execute(select(Camera.status, func.count()).group_by(Camera.status))
    for camera_status, count in rows.all():
        by_status.add_metric([camera_status or ""], count)
        total += count

    # "Erishiladi" / "tasvir bor" — aynan app/jobs/camera_health.py
    # dagi funksiyalar bilan (panel va Prometheus bir xil raqam ko'rsatsin).
    active = reachable = flowing = 0
    rows = await db.execute(select(Camera.last_seen_at, Camera.last_frame_at).where(Camera.status == "faol"))
    for last_seen_at, last_frame_at in rows.all():
        active += 1
        if is_reachable(last_seen_at):
            reachable += 1
            if is_video_flowing(last_frame_at):
                flowing += 1

    total_g = _gauge("cameras_total", "Barcha kameralar soni")
    total_g.add_metric([], total)
    active_g = _gauge("cameras_active", "Faol (kuzatiladigan) kameralar soni")
    active_g.add_metric([], active)
    reachable_g = _gauge("cameras_reachable", "Tarmoqda javob berayotgan faol kameralar")
    reachable_g.add_metric([], reachable)
    flowing_g = _gauge("cameras_video_flowing", "Tasvir kelayotgan faol kameralar")
    flowing_g.add_metric([], flowing)
    return [total_g, by_status, active_g, reachable_g, flowing_g]


async def _event_families(db: AsyncSession, now: datetime) -> list:
    since = now - timedelta(hours=1)
    last_hour = _gauge(
        "events_last_hour",
        "Oxirgi 1 soatdagi hodisalar (sinov rejimisiz) modul va og'irlik bo'yicha",
        ["module_code", "module", "severity"],
    )
    rows = await db.execute(
        select(Event.module_code, func.max(Event.module_name), Event.severity, func.count())
        .where(Event.occurred_at >= since, Event.is_trial.is_(False))
        .group_by(Event.module_code, Event.severity)
    )
    for module_code, module_name, severity, count in rows.all():
        last_hour.add_metric([str(module_code), module_name or "", severity], count)

    open_g = _gauge("events_open", "Yopilmagan hodisalar holat bo'yicha (sinov rejimisiz)", ["status"])
    counts = dict.fromkeys(OPEN_STATUSES, 0)
    rows = await db.execute(
        select(Event.status, func.count())
        .where(Event.status.in_(OPEN_STATUSES), Event.is_trial.is_(False))
        .group_by(Event.status)
    )
    for event_status, count in rows.all():
        counts[event_status] = count
    for event_status, count in counts.items():
        open_g.add_metric([event_status], count)

    unreviewed = _gauge("events_unreviewed", "Ko'rib chiqilmagan ('yangi') hodisalar")
    unreviewed.add_metric([], counts["yangi"])

    overdue_count = await db.scalar(
        select(func.count())
        .select_from(Event)
        .where(
            Event.due_at.is_not(None),
            Event.due_at < now,
            Event.status.in_(OPEN_STATUSES),
            Event.is_trial.is_(False),
        )
    )
    overdue = _gauge("events_overdue", "Hal qilish muddati (SLA) o'tgan ochiq hodisalar")
    overdue.add_metric([], overdue_count or 0)
    return [last_hour, open_g, unreviewed, overdue]


async def _attendance_families(db: AsyncSession) -> list:
    today = business_today()
    records = _gauge(
        "attendance_records_today",
        "Bugungi davomat yozuvlari holat va manba bo'yicha (Toshkent vaqti)",
        ["status", "source"],
    )
    rows = await db.execute(
        select(AttendanceRecord.status, AttendanceRecord.source, func.count())
        .where(AttendanceRecord.date == today)
        .group_by(AttendanceRecord.status, AttendanceRecord.source)
    )
    for record_status, source, count in rows.all():
        records.add_metric([record_status, source or "nomalum"], count)

    families = [records]
    last_check_in = await db.scalar(
        select(func.max(AttendanceRecord.check_in)).where(
            AttendanceRecord.date == today,
            AttendanceRecord.status.in_(("keldi", "kech_keldi")),
        )
    )
    if last_check_in is not None:
        last = _gauge(
            "attendance_last_check_in_timestamp_seconds",
            "Bugungi eng kech kelish (check_in) vaqti (unix; check_in Toshkent vaqtida yoziladi)",
        )
        last.add_metric([], datetime.combine(today, last_check_in, tzinfo=INSTITUTE_TZ).timestamp())
        families.append(last)
    return families


async def _access_and_notification_families(db: AsyncSession, now: datetime) -> list:
    since = now - timedelta(hours=1)
    access = _gauge(
        "access_events_last_hour",
        "Oxirgi 1 soatdagi turniket hodisalari (ruxsat va yo'nalish bo'yicha)",
        ["granted", "direction"],
    )
    rows = await db.execute(
        select(AccessEvent.granted, AccessEvent.direction, func.count())
        .where(AccessEvent.occurred_at >= since)
        .group_by(AccessEvent.granted, AccessEvent.direction)
    )
    for granted, direction, count in rows.all():
        access.add_metric(["true" if granted else "false", direction or "nomalum"], count)

    notifications = _gauge(
        "notifications_last_hour",
        "Oxirgi 1 soatdagi xabarlar (kanal va holat bo'yicha)",
        ["channel", "status"],
    )
    rows = await db.execute(
        select(NotificationLog.channel, NotificationLog.status, func.count())
        .where(NotificationLog.created_at >= since)
        .group_by(NotificationLog.channel, NotificationLog.status)
    )
    for channel, notification_status, count in rows.all():
        notifications.add_metric([channel, notification_status], count)
    return [access, notifications]


async def _leader_process_view() -> dict | None:
    """AI ishlayotgan (leader) jarayonning surati — Redis'dan yoki o'zimizdan.

    load_leader_process_view() dan farqi: surat yo'q bo'lsa shu jarayonni
    o'lchamaydi — AI'siz api jarayonida bu torch'ni yuklab yuborardi."""
    from app.services import runtime_snapshot

    if runtime_snapshot._is_publisher:
        return runtime_snapshot.local_process_view()
    data = await runtime_snapshot._read_json(runtime_snapshot.KEY_LEADER_PROCESS)
    return data or None


async def _ai_families() -> list:
    from app.services.runtime_snapshot import load_sweep_stats, total_stream_readers

    now = datetime.now(timezone.utc)
    sweeps = await load_sweep_stats()
    labels = ["name", "tier"]
    runs = _gauge("ai_sweep_runs", "Sweep leader ishga tushgandan beri necha marta ishladi", labels)
    failures = _gauge("ai_sweep_failures", "Sweep leader ishga tushgandan beri necha marta xato berdi", labels)
    duration = _gauge("ai_sweep_last_duration_seconds", "Sweepning oxirgi davomiyligi", labels)
    finished = _gauge("ai_sweep_last_finished_timestamp_seconds", "Sweep oxirgi marta tugagan vaqt (unix)", labels)
    lagging = _gauge("ai_sweep_lagging", "1 — sweep o'z intervalidan ancha kechikmoqda", labels)
    paused = _gauge("ai_sweep_paused", "1 — sweep ataylab to'xtatilgan (masalan tirband soat)", labels)
    for sweep in sweeps:
        key = [sweep.name, sweep.tier]
        runs.add_metric(key, sweep.runs)
        failures.add_metric(key, sweep.failures)
        duration.add_metric(key, sweep.last_duration_seconds)
        if sweep.last_finished_at is not None:
            finished.add_metric(key, sweep.last_finished_at.timestamp())
        lagging.add_metric(key, 1 if sweep.is_lagging(now) else 0)
        paused.add_metric(key, 1 if sweep.paused else 0)

    readers = _gauge("ai_stream_readers", "Ochiq ffmpeg oqim o'quvchilari (barcha jarayonlar)")
    readers.add_metric([], await total_stream_readers())
    families: list = [runs, failures, duration, finished, lagging, paused, readers]

    leader = await _leader_process_view()
    if not leader:
        return families

    slots = _gauge("ai_slots", "AI sweep slotlari (kamera parallelligi)", ["pool", "kind"])
    for pool, key in (("global", "sweep_slots"), ("entrance_exit", "entrance_exit_sweep_slots")):
        snapshot = leader.get(key) or {}
        for kind in ("max", "in_use"):
            if kind in snapshot:
                slots.add_metric([pool, kind], float(snapshot[kind]))
    gate = _gauge("ai_face_inference_gate", "Yuz inference navbati", ["kind"])
    for kind, value in (leader.get("face_inference_gate") or {}).items():
        gate.add_metric([str(kind)], float(value))
    watchers = _gauge("ai_entrance_watchers", "Kirish kameralarini uzluksiz kuzatuvchilar")
    watchers.add_metric([], float(leader.get("entrance_watchers") or 0))
    families += [slots, gate, watchers]

    health = leader.get("camera_health_sweep") or {}
    if health.get("finished_at"):
        sweep_g = _gauge("camera_health_sweep", "Oxirgi kamera tarmoq tekshiruvi", ["kind"])
        sweep_g.add_metric(["duration_seconds"], float(health.get("duration_seconds") or 0))
        sweep_g.add_metric(["checked"], float(health.get("faol_checked") or 0))
        sweep_g.add_metric(["reachable"], float(health.get("reachable") or 0))
        sweep_g.add_metric(
            ["finished_timestamp_seconds"], datetime.fromisoformat(str(health["finished_at"])).timestamp()
        )
        families.append(sweep_g)

    gpu = leader.get("gpu") or {}
    if "cuda_available" in gpu:
        gpu_g = _gauge("ai_gpu_cuda_available", "1 — AI jarayonida CUDA mavjud")
        gpu_g.add_metric([], 1 if gpu.get("cuda_available") else 0)
        families.append(gpu_g)
    return families


def _app_info() -> InfoMetricFamily:
    info = InfoMetricFamily(f"{PREFIX}_app", "Ilova versiyasi va roli")
    info.add_metric(
        [],
        {
            "version": os.environ.get("APP_VERSION", "").strip() or "unknown",
            "role": settings.ai_role,
            "system": settings.org_system_name,
        },
    )
    return info


async def _collect(db: AsyncSession) -> list:
    started = time.monotonic()
    now = datetime.now(timezone.utc)
    families: list = []
    ok = True
    try:
        families += await _camera_families(db)
        families += await _event_families(db, now)
        families += await _attendance_families(db)
        families += await _access_and_notification_families(db, now)
    except Exception:
        ok = False
        logger.exception("metrics database collection failed")
        await db.rollback()
    try:
        families += await asyncio.wait_for(_ai_families(), timeout=AI_SNAPSHOT_TIMEOUT_SECONDS)
    except Exception:
        # AI surati ixtiyoriy — bazadagi ko'rsatkichlar baribir beriladi.
        logger.warning("metrics AI snapshot unavailable", exc_info=True)

    success = _gauge("metrics_collect_success", "1 — tizim ko'rsatkichlari bazadan muvaffaqiyatli olindi")
    success.add_metric([], 1 if ok else 0)
    duration = _gauge("metrics_collect_duration_seconds", "Ko'rsatkichlarni yig'ish davomiyligi")
    duration.add_metric([], round(time.monotonic() - started, 4))
    collected = _gauge("metrics_collected_timestamp_seconds", "Ko'rsatkichlar yig'ilgan vaqt (unix)")
    collected.add_metric([], now.timestamp())
    families += [success, duration, collected]
    return families


async def _snapshot(db: AsyncSession) -> list:
    global _cache
    cached = _cache
    if cached is not None and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]
    async with _cache_lock:
        cached = _cache
        if cached is not None and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
        families = await _collect(db)
        _cache = (time.monotonic(), families)
        return families


class _StaticCollector(Collector):
    def __init__(self, families: list) -> None:
        self._families = families

    def collect(self):
        yield from self._families


@router.get("/metrics", include_in_schema=False, dependencies=[Depends(_authorize)])
async def metrics(db: AsyncSession = Depends(get_db)) -> Response:
    families = await _snapshot(db)
    registry = CollectorRegistry(auto_describe=False)
    registry.register(_StaticCollector([_app_info(), *families]))
    # Standart jarayon/GC ko'rsatkichlari + tizim holati. Nomlar kesishmaydi
    # (tizim holati "sm_" prefiksida), shuning uchun ikkala matnni qo'shish
    # to'g'ri Prometheus formatini beradi.
    body = generate_latest(REGISTRY) + generate_latest(registry)
    return Response(content=body, media_type=CONTENT_TYPE_LATEST)
