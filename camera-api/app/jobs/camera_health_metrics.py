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
