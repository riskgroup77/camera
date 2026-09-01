"""Central AI sweep coordinator (P2 #22, P0 parallel tick).

When AI_SCHEDULER_ENABLED=true, individual per-module asyncio loops are
NOT started (see app/main.py). This module polls every
AI_SCHEDULER_POLL_SECONDS and runs each sweep's run_*_once function when
its configured interval has elapsed.

Due sweeps in the same tier run in PARALLEL (asyncio.gather) so a 30s
interval means wall-clock ~30s, not (sum of all other modules). A global
camera semaphore (app/jobs/sweep_concurrency.py) caps total concurrent
camera pipelines across all modules.

Critical-tier sweeps (fire, fall, fight, zone, face path) run before
standard-tier sweeps in each tick so life-safety criteria aren't stuck
behind dress-code/heuristic modules.

camera_health_loop and cleanup_loop stay independent (different SLA).
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from app.config import settings
from app.database import SessionLocal
from app.jobs.abandoned_object_ai import run_abandoned_object_ai_sweep_once
from app.jobs.attendance_ai import run_attendance_ai_sweep_once, run_entrance_exit_attendance_sweep_once
from app.jobs.badge_ai import run_badge_ai_sweep_once
from app.jobs.crowd_density_ai import run_crowd_density_ai_sweep_once
from app.jobs.disorder_ai import run_disorder_ai_sweep_once
from app.jobs.dress_code_ai import run_dress_code_ai_sweep_once
from app.jobs.fall_ai import run_fall_ai_sweep_once
from app.jobs.fight_ai import run_fight_ai_sweep_once
from app.jobs.fire_ai import run_fire_ai_sweep_once
from app.jobs.lesson_quality_ai import run_lesson_quality_ai_sweep_once
from app.jobs.phone_ai import run_phone_ai_sweep_once
from app.jobs.ppe_ai import run_ppe_ai_sweep_once
from app.jobs.smoking_ai import run_smoking_ai_sweep_once
from app.jobs.student_dress_code_ai import run_student_dress_code_ai_sweep_once
from app.jobs.scheduler_metrics import record_scheduler_skip, record_scheduler_tick
from app.jobs.sweep_guard import SweepGuard
from app.jobs.teacher_punctuality_ai import run_teacher_punctuality_sweep_once
from app.jobs.unauthorized_person_ai import run_unauthorized_person_ai_sweep_once
from app.jobs.unified_face_sweep import run_unified_face_sweep_once
from app.jobs.vehicle_ai import run_vehicle_ai_sweep_once
from app.jobs.vision_ai import run_vision_ai_sweep_once
from app.jobs.zone_entry_ai import run_zone_entry_ai_sweep_once

logger = logging.getLogger("app.ai_scheduler")

_guard = SweepGuard("ai_scheduler")

Tier = Literal["critical", "standard"]


@dataclass
class _SweepEntry:
    name: str
    interval_seconds: int
    run_once: Callable[..., Awaitable[Any]]
    tier: Tier
    last_run: float = field(default=0.0)


def _face_entries() -> list[tuple[str, int, Callable[..., Awaitable[Any]], Tier]]:
    if settings.unified_face_sweep_enabled:
        return [
            (
                "unified_face",
                settings.unified_face_sweep_interval_seconds,
                run_unified_face_sweep_once,
                "critical",
            ),
            (
                "entrance_exit_attendance",
                settings.entrance_exit_attendance_interval_seconds,
                run_entrance_exit_attendance_sweep_once,
                "critical",
            ),
        ]
    return [
        ("attendance", settings.attendance_ai_interval_seconds, run_attendance_ai_sweep_once, "critical"),
        ("vision_sleep", settings.vision_ai_interval_seconds, run_vision_ai_sweep_once, "critical"),
        (
            "unauthorized",
            settings.unauthorized_person_ai_interval_seconds,
            run_unauthorized_person_ai_sweep_once,
            "critical",
        ),
        ("crowd", settings.crowd_ai_interval_seconds, run_crowd_density_ai_sweep_once, "critical"),
    ]


def _build_registry() -> list[_SweepEntry]:
    rest: list[tuple[str, int, Callable[..., Awaitable[Any]], Tier]] = [
        ("fire", settings.fire_ai_interval_seconds, run_fire_ai_sweep_once, "critical"),
        ("fall", settings.fall_ai_interval_seconds, run_fall_ai_sweep_once, "critical"),
        ("zone_entry", settings.zone_ai_interval_seconds, run_zone_entry_ai_sweep_once, "critical"),
        ("fight", settings.fight_ai_interval_seconds, run_fight_ai_sweep_once, "critical"),
        ("teacher_punctuality", settings.teacher_punctuality_interval_seconds, run_teacher_punctuality_sweep_once, "standard"),
        ("abandoned_object", settings.abandoned_object_ai_interval_seconds, run_abandoned_object_ai_sweep_once, "standard"),
        ("disorder", settings.disorder_ai_interval_seconds, run_disorder_ai_sweep_once, "standard"),
        ("dress_code", settings.dress_code_ai_interval_seconds, run_dress_code_ai_sweep_once, "standard"),
        ("phone", settings.phone_ai_interval_seconds, run_phone_ai_sweep_once, "standard"),
        ("badge", settings.badge_ai_interval_seconds, run_badge_ai_sweep_once, "standard"),
        ("ppe", settings.ppe_ai_interval_seconds, run_ppe_ai_sweep_once, "standard"),
        ("smoking", settings.smoking_ai_interval_seconds, run_smoking_ai_sweep_once, "standard"),
        ("student_dress", settings.student_uniform_ai_interval_seconds, run_student_dress_code_ai_sweep_once, "standard"),
        ("vehicle", settings.vehicle_ai_interval_seconds, run_vehicle_ai_sweep_once, "standard"),
        ("lesson_quality", settings.lesson_quality_ai_interval_seconds, run_lesson_quality_ai_sweep_once, "standard"),
    ]
    specs = _face_entries() + rest
    return [_SweepEntry(name=n, interval_seconds=i, run_once=fn, tier=t) for n, i, fn, t in specs]


def _due_entries(registry: list[_SweepEntry], now: float) -> tuple[list[_SweepEntry], list[_SweepEntry]]:
    critical: list[_SweepEntry] = []
    standard: list[_SweepEntry] = []
    for entry in registry:
        if now - entry.last_run < entry.interval_seconds:
            continue
        if entry.tier == "critical":
            critical.append(entry)
        else:
            standard.append(entry)
    return critical, standard


def _count_result(result: Any) -> int:
    if isinstance(result, dict):
        return sum(result.values())
    return int(result or 0)


async def _run_one_entry(entry: _SweepEntry) -> None:
    try:
        result = await entry.run_once(session_factory=SessionLocal)
        count = _count_result(result)
        if count:
            logger.info(
                "scheduler sweep completed",
                extra={"sweep": entry.name, "tier": entry.tier, "events_or_actions": count},
            )
    except Exception:
        logger.exception("scheduler sweep failed", extra={"sweep": entry.name, "tier": entry.tier})
    finally:
        entry.last_run = time.monotonic()


async def _run_tier_parallel(entries: list[_SweepEntry]) -> int:
    if not entries:
        return 0
    await asyncio.gather(*(_run_one_entry(entry) for entry in entries))
    return len(entries)


async def run_scheduler_tick(registry: list[_SweepEntry]) -> tuple[int, int, int]:
    """Run due sweeps: critical tier in parallel, then standard tier in parallel.
    Returns (total_modules_ran, critical_ran, standard_ran)."""
    now = time.monotonic()
    critical, standard = _due_entries(registry, now)
    if not critical and not standard:
        return 0, 0, 0

    critical_ran = await _run_tier_parallel(critical)
    standard_ran = await _run_tier_parallel(standard)
    return critical_ran + standard_ran, critical_ran, standard_ran


async def ai_scheduler_loop() -> None:
    registry = _build_registry()
    logger.info(
        "AI scheduler started (parallel tiers)",
        extra={
            "poll_seconds": settings.ai_scheduler_poll_seconds,
            "global_camera_concurrency": settings.ai_global_sweep_concurrency,
            "critical": [e.name for e in registry if e.tier == "critical"],
            "standard": [e.name for e in registry if e.tier == "standard"],
        },
    )
    while True:
        try:

            async def tick() -> None:
                started = time.monotonic()
                total, critical_ran, standard_ran = await run_scheduler_tick(registry)
                record_scheduler_tick(
                    duration_seconds=time.monotonic() - started,
                    modules_ran=total,
                    critical_ran=critical_ran,
                    standard_ran=standard_ran,
                )

            result = await _guard.run(tick)
            if result is None:
                record_scheduler_skip()
        except Exception:
            logger.exception("AI scheduler tick failed")
        await asyncio.sleep(settings.ai_scheduler_poll_seconds)
