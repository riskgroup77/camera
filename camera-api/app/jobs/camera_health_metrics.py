"""Last camera health sweep metrics — read by /api/system/camera-network."""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class CameraHealthSweepStats:
    finished_at: datetime | None = None
    duration_seconds: float = 0.0
    faol_checked: int = 0
    reachable: int = 0
    skipped_overlap: bool = False


_last_sweep = CameraHealthSweepStats()


def record_camera_health_sweep(
    *,
    duration_seconds: float,
    faol_checked: int,
    reachable: int,
) -> None:
    global _last_sweep
    _last_sweep = CameraHealthSweepStats(
        finished_at=datetime.now(timezone.utc),
        duration_seconds=round(duration_seconds, 2),
        faol_checked=faol_checked,
        reachable=reachable,
        skipped_overlap=False,
    )


def record_camera_health_skip() -> None:
    global _last_sweep
    _last_sweep = CameraHealthSweepStats(
        finished_at=datetime.now(timezone.utc),
        duration_seconds=0.0,
        faol_checked=0,
        reachable=0,
        skipped_overlap=True,
    )


def get_camera_health_sweep_stats() -> CameraHealthSweepStats:
    return _last_sweep


def export_last_sweep() -> dict[str, object]:
    """JSON ko'rinishi — leader uni Redis orqali boshqa jarayonlarga beradi
    (app/services/runtime_snapshot.py); sweep faqat leader'da ishlaydi."""
    sweep = _last_sweep
    return {
        "finished_at": sweep.finished_at.isoformat() if sweep.finished_at else None,
        "duration_seconds": sweep.duration_seconds,
        "faol_checked": sweep.faol_checked,
        "reachable": sweep.reachable,
        "skipped_overlap": sweep.skipped_overlap,
    }
