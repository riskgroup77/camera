"""Central AI sweep coordinator (P2 #22).

When AI_SCHEDULER_ENABLED=true, individual per-module asyncio loops are
NOT started (see app/main.py). Instead this module polls every
AI_SCHEDULER_POLL_SECONDS and runs each sweep's run_*_once function when
its configured interval has elapsed — one global SweepGuard prevents
overlapping global ticks.

camera_health_loop and cleanup_loop stay independent (different SLA).
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.config import settings
from app.database import SessionLocal
from app.jobs.badge_ai import run_badge_ai_sweep_once
from app.jobs.abandoned_object_ai import run_abandoned_object_ai_sweep_once
from app.jobs.attendance_ai import run_attendance_ai_sweep_once
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
from app.jobs.sweep_guard import SweepGuard
from app.jobs.teacher_punctuality_ai import run_teacher_punctuality_sweep_once
from app.jobs.unauthorized_person_ai import run_unauthorized_person_ai_sweep_once
from app.jobs.unified_face_sweep import run_unified_face_sweep_once
from app.jobs.vehicle_ai import run_vehicle_ai_sweep_once
from app.jobs.vision_ai import run_vision_ai_sweep_once
from app.jobs.zone_entry_ai import run_zone_entry_ai_sweep_once

logger = logging.getLogger("app.ai_scheduler")

_guard = SweepGuard("ai_scheduler")


@dataclass
class _SweepEntry:
    name: str
    interval_seconds: int
    run_once: Callable[[], Awaitable[int]]
    last_run: float = field(default=0.0)


def _build_registry() -> list[_SweepEntry]:
    face = (
        [("unified_face", settings.unified_face_sweep_interval_seconds, run_unified_face_sweep_once)]
        if settings.unified_face_sweep_enabled
        else [
            ("attendance", settings.attendance_ai_interval_seconds, run_attendance_ai_sweep_once),
            ("vision_sleep", settings.vision_ai_interval_seconds, run_vision_ai_sweep_once),
            ("unauthorized", settings.unauthorized_person_ai_interval_seconds, run_unauthorized_person_ai_sweep_once),
            ("crowd", settings.crowd_ai_interval_seconds, run_crowd_density_ai_sweep_once),
        ]
    )
    rest = [
        ("fire", settings.fire_ai_interval_seconds, run_fire_ai_sweep_once),
        ("teacher_punctuality", settings.teacher_punctuality_interval_seconds, run_teacher_punctuality_sweep_once),
        ("abandoned_object", settings.abandoned_object_ai_interval_seconds, run_abandoned_object_ai_sweep_once),
        ("disorder", settings.disorder_ai_interval_seconds, run_disorder_ai_sweep_once),
        ("dress_code", settings.dress_code_ai_interval_seconds, run_dress_code_ai_sweep_once),
        ("phone", settings.phone_ai_interval_seconds, run_phone_ai_sweep_once),
        ("badge", settings.badge_ai_interval_seconds, run_badge_ai_sweep_once),
        ("ppe", settings.ppe_ai_interval_seconds, run_ppe_ai_sweep_once),
        ("smoking", settings.smoking_ai_interval_seconds, run_smoking_ai_sweep_once),
        ("student_dress", settings.student_uniform_ai_interval_seconds, run_student_dress_code_ai_sweep_once),
        ("vehicle", settings.vehicle_ai_interval_seconds, run_vehicle_ai_sweep_once),
        ("fall", settings.fall_ai_interval_seconds, run_fall_ai_sweep_once),
        ("zone_entry", settings.zone_entry_ai_interval_seconds, run_zone_entry_ai_sweep_once),
        ("lesson_quality", settings.lesson_quality_ai_interval_seconds, run_lesson_quality_ai_sweep_once),
        ("fight", settings.fight_ai_interval_seconds, run_fight_ai_sweep_once),
    ]
    return [_SweepEntry(name=n, interval_seconds=i, run_once=fn) for n, i, fn in face + rest]


async def run_scheduler_tick(registry: list[_SweepEntry]) -> int:
    """Run all due sweeps sequentially within one global tick."""
    now = time.monotonic()
    ran = 0
    for entry in registry:
        if now - entry.last_run < entry.interval_seconds:
            continue
        try:
            result = await entry.run_once(session_factory=SessionLocal)
            entry.last_run = time.monotonic()
            ran += 1
            count = sum(result.values()) if isinstance(result, dict) else int(result or 0)
            if count:
                logger.info(
                    "scheduler sweep completed",
                    extra={"sweep": entry.name, "events_or_actions": count},
                )
        except Exception:
            logger.exception("scheduler sweep failed", extra={"sweep": entry.name})
            entry.last_run = time.monotonic()
    return ran


async def ai_scheduler_loop() -> None:
    registry = _build_registry()
    logger.info(
        "AI scheduler started",
        extra={
            "poll_seconds": settings.ai_scheduler_poll_seconds,
            "modules": [e.name for e in registry],
        },
    )
    while True:
        try:

            async def tick() -> None:
                await run_scheduler_tick(registry)

            await _guard.run(tick)
        except Exception:
            logger.exception("AI scheduler tick failed")
        await asyncio.sleep(settings.ai_scheduler_poll_seconds)
