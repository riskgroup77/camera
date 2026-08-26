"""Real server resource metrics for the admin dashboard's "Server resurslari"
widget — CPU/RAM/disk usage of the machine running this API process, via
psutil. Replaces the frontend's old hardcoded mock/admin.ts systemResources."""

from typing import Annotated

import psutil
from fastapi import APIRouter, Depends

from app.config import settings
from app.dependencies import CurrentUser, get_current_user
from app.schemas.system import (
    ConcurrencySlotOut,
    GpuStatusOut,
    ResourceAlertOut,
    SchedulerLastTickOut,
    SystemAiStatusOut,
    SystemResourcesOut,
)
from app.services.ai_runtime_status import build_ai_runtime_status
from app.services.stream_cache import active_stream_reader_count

router = APIRouter(prefix="/api/system", tags=["system"])


def _ffmpeg_process_count() -> int:
    count = 0
    for proc in psutil.process_iter(["name"]):
        name = proc.info.get("name") or ""
        if "ffmpeg" in name.lower():
            count += 1
    return count


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
async def get_system_resources(_: Annotated[CurrentUser, Depends(get_current_user)]) -> SystemResourcesOut:
    cpu = round(psutil.cpu_percent(interval=0.1))
    ram = round(psutil.virtual_memory().percent)
    disk = round(psutil.disk_usage("/").percent)
    ffmpeg_count = _ffmpeg_process_count()
    stream_readers = active_stream_reader_count()

    return SystemResourcesOut(
        cpu=cpu,
        ram=ram,
        disk=disk,
        ffmpeg_process_count=ffmpeg_count,
        stream_reader_count=stream_readers,
        alerts=_build_alerts(cpu, ram, disk, ffmpeg_count),
    )


@router.get("/ai-status", response_model=SystemAiStatusOut)
async def get_ai_status(_: Annotated[CurrentUser, Depends(get_current_user)]) -> SystemAiStatusOut:
    raw = build_ai_runtime_status()
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
        gpu=GpuStatusOut(**raw["gpu"]),
        sweep_slots=ConcurrencySlotOut(**raw["sweep_slots"]),
        face_inference_gate=ConcurrencySlotOut(**raw["face_inference_gate"]),
        stream_reader_count=int(raw["stream_reader_count"]),
        embedding_sweep_cache_ttl_seconds=int(raw["embedding_sweep_cache_ttl_seconds"]),
    )
