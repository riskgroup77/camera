"""Last AI scheduler tick metrics — read by /api/system/ai-status."""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class SchedulerTickStats:
    finished_at: datetime | None = None
    duration_seconds: float = 0.0
    modules_ran: int = 0
    critical_ran: int = 0
    standard_ran: int = 0
    skipped_overlap: bool = False


_last_tick = SchedulerTickStats()


def record_scheduler_tick(
    *,
    duration_seconds: float,
    modules_ran: int,
    critical_ran: int,
    standard_ran: int,
) -> None:
    global _last_tick
    _last_tick = SchedulerTickStats(
        finished_at=datetime.now(timezone.utc),
        duration_seconds=round(duration_seconds, 2),
        modules_ran=modules_ran,
        critical_ran=critical_ran,
        standard_ran=standard_ran,
        skipped_overlap=False,
    )


def record_scheduler_skip() -> None:
    global _last_tick
    _last_tick = SchedulerTickStats(
        finished_at=datetime.now(timezone.utc),
        duration_seconds=0.0,
        modules_ran=0,
        critical_ran=0,
        standard_ran=0,
        skipped_overlap=True,
    )


def get_scheduler_tick_stats() -> SchedulerTickStats:
    return _last_tick
