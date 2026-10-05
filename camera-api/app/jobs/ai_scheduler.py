"""Central AI sweep coordinator (P2 #22).

When AI_SCHEDULER_ENABLED=true, individual per-module loops in app/main.py
are NOT started; this module runs every sweep instead.

MUSTAQIL TSIKLLAR. Avval rejalashtiruvchi "tick" asosida ishlardi: har
AI_SCHEDULER_POLL_SECONDS da muddati kelgan sweeplar yig'ilib gather
qilinar, tick esa ENG SEKIN sweep tugashini kutardi. Productionda
unified_face (100+ kamera, AVX'siz CPU) bir necha daqiqa davom etadi,
shuning uchun 6 soniyalik kirish/chiqish davomati sweepi amalda bir necha
daqiqada BIR MARTA ishlardi — odam eshikdan 2-3 soniyada o'tib ketadi va
hech qachon kadrga tushmaydi. Davomatga hech kim tushmasligining asosiy
sababi shu edi. Tick band bo'lganda keyingisi "overlap skip" deb 0 modul
yozardi — boshqaruv panelidagi "Oxirgi tick: 0 modul" ham shundan.

Endi har bir sweep o'z asyncio vazifasida aylanadi: ishini tugatadi,
intervalning qolgan qismini kutadi va qayta boshlaydi. Sekin sweep faqat
o'zini kechiktiradi. Umumiy yuklama hali ham global semaforlar bilan
cheklangan (app/jobs/sweep_concurrency.py, app/services/inference_gate.py),
kirish/chiqish sweepi esa o'z alohida semaforida.

camera_health_loop and cleanup_loop stay independent (different SLA).
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.config import settings
from app.database import SessionLocal
from app.jobs.absence_marker import run_absence_marking_once
from app.jobs.event_clips import run_event_clips_once
from app.jobs.attendance_ai import run_attendance_ai_sweep_once, run_entrance_exit_attendance_dispatch_once
from app.jobs.lesson_attendance import run_lesson_attendance_finalization_once
from app.jobs.lesson_quality_ai import run_lesson_quality_ai_sweep_once
from app.jobs.module_status import is_within_attendance_priority_window
from app.jobs.module_suppression import run_module_suppression_once
from app.jobs.report_schedules import INTERVAL_SECONDS as REPORT_SCHEDULES_INTERVAL, run_report_schedules_once
from app.jobs.scheduler_metrics import record_sweep_finished, record_sweep_paused, record_sweep_started, register_sweep
from app.jobs.teacher_punctuality_ai import run_teacher_punctuality_sweep_once
from app.jobs.unauthorized_person_ai import run_unauthorized_person_ai_sweep_once
from app.jobs.unified_face_sweep import run_unified_face_sweep_once

logger = logging.getLogger("app.ai_scheduler")

Tier = Literal["critical", "standard"]

# Sweep juda tez tugasa ham (masalan kamera yo'q) keyingi boshlanishgacha
# kamida shuncha kutiladi — bo'sh aylanib CPU yemasligi uchun.
MIN_PAUSE_SECONDS = 1.0
# Pauzadagi sweep tirband oyna tugaganini shuncha soniyada bir tekshiradi.
PAUSE_RECHECK_SECONDS = 30.0


# Sozlamada yozilgan bo'lsa ham hech qachon pauzaga qo'yilmaydigan
# sweeplar (hayot xavfsizligi). Yong'in moduli 2026-09-24 da olib
# tashlangan; to'plam kelajakdagi shunday modul uchun qoldirildi.
NEVER_PAUSED_SWEEPS: frozenset[str] = frozenset()


def attendance_priority_sweeps() -> set[str]:
    names = {name.strip() for name in settings.attendance_priority_paused_sweeps.split(",") if name.strip()}
    return names - NEVER_PAUSED_SWEEPS


def is_paused_for_attendance(name: str) -> bool:
    """Tirband soatda og'ir evristika CPU'ni kirish kameralaridagi davomatga
    bo'shatadimi (settings.attendance_priority_*)."""
    return (
        settings.attendance_priority_enabled
        and name in attendance_priority_sweeps()
        and is_within_attendance_priority_window()
    )


@dataclass
class _SweepEntry:
    name: str
    interval_seconds: int
    run_once: Callable[..., Awaitable[Any]]
    tier: Tier


def _face_entries() -> list[tuple[str, int, Callable[..., Awaitable[Any]], Tier]]:
    if settings.unified_face_sweep_enabled:
        return [
            (
                "entrance_exit_attendance",
                settings.entrance_exit_attendance_interval_seconds,
                # Fon dispetcher: har kirish kamerasi o'z vazifasida, eng
                # sekin kamera qolganlarini kutdirmaydi (attendance_ai.py).
                run_entrance_exit_attendance_dispatch_once,
                "critical",
            ),
            (
                "unified_face",
                settings.unified_face_sweep_interval_seconds,
                run_unified_face_sweep_once,
                "critical",
            ),
        ]
    return [
        ("attendance", settings.attendance_ai_interval_seconds, run_attendance_ai_sweep_once, "critical"),
        (
            "unauthorized",
            settings.unauthorized_person_ai_interval_seconds,
            run_unauthorized_person_ai_sweep_once,
            "critical",
        ),
    ]


def _build_registry() -> list[_SweepEntry]:
    rest: list[tuple[str, int, Callable[..., Awaitable[Any]], Tier]] = [
        ("teacher_punctuality", settings.teacher_punctuality_interval_seconds, run_teacher_punctuality_sweep_once, "standard"),
        ("lesson_quality", settings.lesson_quality_ai_interval_seconds, run_lesson_quality_ai_sweep_once, "standard"),
        ("lesson_attendance", settings.lesson_attendance_finalize_interval_seconds, run_lesson_attendance_finalization_once, "standard"),
        # Kamera talab qilmaydi (faqat DB); o'zi ish kuni tugaguncha hech
        # narsa qilmaydi (app/jobs/absence_marker.py).
        ("absence_marking", settings.attendance_absence_marking_interval_seconds, run_absence_marking_once, "standard"),
        # Arxivdan hodisa klipi va umumiy disk nazorati (app/jobs/event_clips.py).
        ("event_clips", 30, run_event_clips_once, "standard"),
        # Faqat DB: operatorlar ko'p rad etgan kamera×modul juftliklarini o'chiradi.
        ("module_suppression", settings.suppression_interval_seconds, run_module_suppression_once, "standard"),
        # Faqat DB + Telegram: haftalik/oylik hisobotni rahbarga yuboradi.
        ("report_schedules", REPORT_SCHEDULES_INTERVAL, run_report_schedules_once, "standard"),
    ]
    specs = _face_entries() + rest
    return [_SweepEntry(name=n, interval_seconds=i, run_once=fn, tier=t) for n, i, fn, t in specs]


def _count_result(result: Any) -> int:
    if isinstance(result, dict):
        return sum(int(v or 0) for v in result.values())
    return int(result or 0)


async def run_sweep_once(entry: _SweepEntry, session_factory=SessionLocal) -> float:
    """Sweepni bir marta bajaradi, xatoni yutadi va ko'rsatkichlarni yozadi.
    Davomiylikni (soniya) qaytaradi."""
    started = time.monotonic()
    record_sweep_started(entry.name)
    error: str | None = None
    count = 0
    try:
        count = _count_result(await entry.run_once(session_factory=session_factory))
        if count:
            logger.info(
                "scheduler sweep completed",
                extra={"sweep": entry.name, "tier": entry.tier, "events_or_actions": count},
            )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:300]
        logger.exception("scheduler sweep failed", extra={"sweep": entry.name, "tier": entry.tier})
    duration = time.monotonic() - started
    record_sweep_finished(entry.name, duration_seconds=duration, result=count, error=error)
    return duration


def next_pause(interval_seconds: float, duration_seconds: float) -> float:
    """Boshlanishdan-boshlanishgacha interval: sweep 2 s davom etgan bo'lsa
    va interval 6 s bo'lsa, 4 s kutiladi. Interval oshib ketgan bo'lsa —
    faqat MIN_PAUSE_SECONDS."""
    return max(MIN_PAUSE_SECONDS, interval_seconds - duration_seconds)


async def _sweep_loop(entry: _SweepEntry, initial_delay: float) -> None:
    if initial_delay > 0:
        await asyncio.sleep(initial_delay)
    while True:
        if is_paused_for_attendance(entry.name):
            record_sweep_paused(entry.name, True)
            await asyncio.sleep(PAUSE_RECHECK_SECONDS)
            continue
        record_sweep_paused(entry.name, False)
        duration = await run_sweep_once(entry)
        await asyncio.sleep(next_pause(entry.interval_seconds, duration))


# O'z alohida sikli (app/main.py dagi *_loop) bo'lmagan sweeplar.
_STANDALONE_SWEEPS = {
    "entrance_exit_attendance", "absence_marking", "module_suppression", "event_clips", "report_schedules",
}


# Kunlik video tahlil rejimida ham kerak bo'lgan, kameraga murojaat
# qilmaydigan sweeplar (davomat va "kelmadi" belgilash tahlilning o'zida).
_DAILY_MODE_SWEEPS = {"module_suppression", "report_schedules"}


def daily_mode_sweep_loops() -> list:
    entries = [e for e in _build_registry() if e.name in _DAILY_MODE_SWEEPS]
    for entry in entries:
        register_sweep(entry.name, entry.tier, entry.interval_seconds)
    return [_sweep_loop(entry, initial_delay=0) for entry in entries]


def standalone_sweep_loops() -> list:
    """AI_SCHEDULER_ENABLED=false bo'lganda ham ishlashi kerak bo'lgan
    sweeplar uchun sikllar. Ilgari bu rejimda kirish/chiqish davomati,
    "kelmadi" belgilash va avtomatik o'chirish umuman ishga tushmasdi —
    ularning faqat rejalashtiruvchida yozuvi bor edi."""
    entries = [e for e in _build_registry() if e.name in _STANDALONE_SWEEPS]
    for entry in entries:
        register_sweep(entry.name, entry.tier, entry.interval_seconds)
    return [_sweep_loop(entry, initial_delay=0) for entry in entries]


async def ai_scheduler_loop() -> None:
    registry = _build_registry()
    for entry in registry:
        register_sweep(entry.name, entry.tier, entry.interval_seconds)
    logger.info(
        "AI scheduler started (independent sweep loops)",
        extra={
            "global_camera_concurrency": settings.ai_global_sweep_concurrency,
            "critical": [e.name for e in registry if e.tier == "critical"],
            "standard": [e.name for e in registry if e.tier == "standard"],
        },
    )
    # Kritik sweeplar birinchi boshlanadi; qolganlari ai_loop_stagger_seconds
    # oralig'ida — hammasi bir lahzada kamera/inference uchun talashmasin.
    ordered = [e for e in registry if e.tier == "critical"] + [e for e in registry if e.tier == "standard"]
    stagger = settings.ai_loop_stagger_seconds
    tasks = [
        asyncio.create_task(_sweep_loop(entry, index * stagger), name=f"ai-sweep:{entry.name}")
        for index, entry in enumerate(ordered)
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
