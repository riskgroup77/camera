"""Real server resource metrics for the admin dashboard's "Server resurslari"
widget — CPU/RAM/disk usage of the machine running this API process, via
psutil. Replaces the frontend's old hardcoded mock/admin.ts systemResources."""

import asyncio
from typing import Annotated

import psutil
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.ai_watchdog import ai_stall_message
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.schemas.system import (
    CameraHealthSweepOut,
    ConcurrencySlotOut,
    GpuStatusOut,
    MediaMTXShardOut,
    ResourceAlertOut,
    SchedulerLastTickOut,
    SweepStatusOut,
    StreamResyncOut,
    SystemAiStatusOut,
    SystemCameraNetworkOut,
    SystemResourcesOut,
    SystemStreamStatusOut,
)
from app.services.ai_runtime_status import build_ai_runtime_status
from app.services.camera_network_status import build_camera_network_status
from app.services.runtime_snapshot import total_stream_readers
from app.services.security_checks import default_password_logins
from app.services.stream_status import build_stream_status
from app.services.stream_sync import sync_all_active_camera_streams

router = APIRouter(prefix="/api/system", tags=["system"])

# Boshqaruv panelidagi server va AI holati. Kamera mas'uli bu panelni
# ko'rmaydi; qolgan operator rollaridan birortasi yetarli.
StatusDep = Annotated[
    CurrentUser, Depends(require_permission("viewReports", "reviewEvents", "systemSettings"))
]


def _ffmpeg_process_count() -> int:
    count = 0
    for proc in psutil.process_iter(["name"]):
        name = proc.info.get("name") or ""
        if "ffmpeg" in name.lower():
            count += 1
    return count


def _measure_resources() -> tuple[int, int, int, int]:
    return (
        round(psutil.cpu_percent(interval=0.1)),
        round(psutil.virtual_memory().percent),
        round(psutil.disk_usage("/").percent),
        _ffmpeg_process_count(),
    )


def _build_alerts(cpu: int, ram: int, disk: int, ffmpeg_count: int) -> list[ResourceAlertOut]:
    alerts: list[ResourceAlertOut] = []

    def add(metric: str, value: int, threshold: int, label: str) -> None:
        if value < threshold:
            return
        level = "critical" if value >= min(threshold + 10, 100) else "warning"
        alerts.append(
            ResourceAlertOut(
                metric=metric,
                level=level,
                message=f"{label} {value}% (chegara {threshold}%)",
            )
        )

    add("cpu", cpu, settings.resource_alert_cpu_percent, "CPU yuklanishi")
    add("ram", ram, settings.resource_alert_ram_percent, "RAM yuklanishi")
    add("disk", disk, settings.resource_alert_disk_percent, "Disk yuklanishi")

    if ffmpeg_count >= settings.resource_alert_ffmpeg_count:
        alerts.append(
            ResourceAlertOut(
                metric="ffmpeg",
                level="warning",
                message=(
                    f"ffmpeg jarayonlari ko'p: {ffmpeg_count} "
                    f"(chegara {settings.resource_alert_ffmpeg_count})"
                ),
            )
        )

    return alerts


@router.get("/resources", response_model=SystemResourcesOut)
async def get_system_resources(
    _: StatusDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemResourcesOut:
    # psutil sinxron: cpu_percent 0.1 s kutadi, process_iter esa yuzlab
    # jarayonni aylanadi — event loop'da bu har so'rovda butun API'ni
    # to'xtatardi (productionda so'rov 727 ms edi).
    cpu, ram, disk, ffmpeg_count = await asyncio.to_thread(_measure_resources)
    # Barcha API jarayonlari bo'yicha — javob bergan jarayonniki emas.
    stream_readers = await total_stream_readers()
    # AI alohida ai-worker konteynerida bo'lsa, uning ffmpeg jarayonlari bu
    # konteynerdan ko'rinmaydi (PID nomlar fazosi) — panelda 0 chiqardi.
    # Har o'quvchi bitta ffmpeg, o'quvchilar soni esa Redis orqali hamma
    # jarayonlardan yig'iladi.
    ffmpeg_count = max(ffmpeg_count, stream_readers)

    return SystemResourcesOut(
        cpu=cpu,
        ram=ram,
        disk=disk,
        ffmpeg_process_count=ffmpeg_count,
        stream_reader_count=stream_readers,
        alerts=_security_alerts(await default_password_logins(db))
        + await _ai_alerts(db)
        + _build_alerts(cpu, ram, disk, ffmpeg_count),
    )


async def _ai_alerts(db: AsyncSession) -> list[ResourceAlertOut]:
    message = await ai_stall_message(db)
    return [ResourceAlertOut(metric="ai", level="critical", message=message)] if message else []


def _security_alerts(default_logins: list[str]) -> list[ResourceAlertOut]:
    if not default_logins:
        return []
    return [
        ResourceAlertOut(
            metric="security",
            level="critical",
            message=(
                f"Ochiq e'lon qilingan standart parol bilan hisob: {', '.join(default_logins)} — "
                "parolni darhol almashtiring (Foydalanuvchilar va Rollar)"
            ),
        )
    ]


@router.get("/ai-status", response_model=SystemAiStatusOut)
async def get_ai_status(_: StatusDep) -> SystemAiStatusOut:
    raw = await build_ai_runtime_status()
    return SystemAiStatusOut(
        scheduler_enabled=bool(raw["scheduler_enabled"]),
        scheduler_poll_seconds=int(raw["scheduler_poll_seconds"]),
        unified_face_sweep_enabled=bool(raw["unified_face_sweep_enabled"]),
        global_sweep_concurrency=int(raw["global_sweep_concurrency"]),
        face_inference_concurrency=int(raw["face_inference_concurrency"]),
        object_inference_concurrency=int(raw["object_inference_concurrency"]),
        critical_modules=list(raw["critical_modules"]),
        standard_modules=list(raw["standard_modules"]),
        last_tick=SchedulerLastTickOut(**raw["last_tick"]),
        sweeps=[SweepStatusOut(**row) for row in raw["sweeps"]],
        gpu=GpuStatusOut(**raw["gpu"]),
        sweep_slots=ConcurrencySlotOut(**raw["sweep_slots"]),
        entrance_exit_sweep_slots=ConcurrencySlotOut(**raw["entrance_exit_sweep_slots"]),
        face_inference_gate=ConcurrencySlotOut(**raw["face_inference_gate"]),
        stream_reader_count=int(raw["stream_reader_count"]),
        embedding_sweep_cache_ttl_seconds=int(raw["embedding_sweep_cache_ttl_seconds"]),
        entrance_watchers=int(raw.get("entrance_watchers") or 0),
    )


@router.get("/stream-status", response_model=SystemStreamStatusOut)
async def get_stream_status(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: StatusDep,
) -> SystemStreamStatusOut:
    raw = await build_stream_status(db)
    return SystemStreamStatusOut(
        sharding_enabled=bool(raw["sharding_enabled"]),
        shard_count=int(raw["shard_count"]),
        faol_cameras=int(raw["faol_cameras"]),
        registered_streams=int(raw["registered_streams"]),
        shards=[MediaMTXShardOut(**shard) for shard in raw["shards"]],
        distribution=list(raw["distribution"]),
        recommendation=str(raw["recommendation"]),
        hls_public_base=str(raw["hls_public_base"]),
    )


@router.get("/camera-network", response_model=SystemCameraNetworkOut)
async def get_camera_network(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: StatusDep,
) -> SystemCameraNetworkOut:
    raw = await build_camera_network_status(db)
    return SystemCameraNetworkOut(
        faol_cameras=int(raw["faol_cameras"]),
        reachable_cameras=int(raw["reachable_cameras"]),
        offline_cameras=int(raw["offline_cameras"]),
        link_local_ip_count=int(raw["link_local_ip_count"]),
        chronic_offline_count=int(raw["chronic_offline_count"]),
        offline_alert_minutes=int(raw["offline_alert_minutes"]),
        health_interval_seconds=int(raw["health_interval_seconds"]),
        health_freshness_seconds=int(raw["health_freshness_seconds"]),
        health_concurrency=int(raw["health_concurrency"]),
        recent_offline_alerts_24h=int(raw["recent_offline_alerts_24h"]),
        last_sweep=CameraHealthSweepOut(**raw["last_sweep"]),
        recommendation=str(raw["recommendation"]),
    )


@router.post("/resync-streams", response_model=StreamResyncOut)
async def resync_streams(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission("systemSettings"))],
) -> StreamResyncOut:
    synced, failed = await sync_all_active_camera_streams(db)
    return StreamResyncOut(synced=synced, failed=failed)


@router.get("/alerts")
async def system_alerts(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: StatusDep,
) -> list[dict[str, str]]:
    """Hozir faol tizim muammolari — Telegramga ketadigan ogohlantirishlar bilan bir xil
    (app/jobs/system_alerts.py): AI to'xtashi, disk, HEMIS."""
    from datetime import datetime, timezone

    from app.jobs.system_alerts import TITLES, collect_problems

    problems = await collect_problems(db, datetime.now(timezone.utc))
    return [{"key": key, "title": TITLES.get(key, key), "message": text} for key, text in problems.items()]
