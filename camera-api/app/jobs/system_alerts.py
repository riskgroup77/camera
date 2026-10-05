"""Tizim nosozliklari haqida Telegram ogohlantirishi ("system" bildirishnoma turi).

2026-09-25 da ma'lum bo'ldi: kunlik zaxira 5 kun ishlamagan, AI to'xtashi
esa faqat boshqaruv panelida ko'rinadi — hech kim panelga qaramasa, muammo
soatlab sezilmaydi. Bu vazifa har settings.system_alerts_interval_seconds da
tekshiradi va muammo PAYDO BO'LGANDA bir marta, hal bo'lmasa har
settings.system_alerts_repeat_hours da yana, hal bo'lganda "tiklandi" deb
xabar beradi:

  * ai          — ish vaqtida kirish kameralarida AI kadr tahlil qilmayapti
                  (app/services/ai_watchdog.py);
  * disk        — server diski settings.system_alerts_disk_percent dan to'la;
  * hemis       — HEMIS sinxronlashi oxirgi marta xato bilan tugagan yoki
                  settings.system_alerts_hemis_hours dan beri muvaffaqiyatli
                  bo'lmagan.

Xabar olish uchun Bildirishnomalar sahifasida "Tizim" turiga qoida kerak.
Holat jarayon xotirasida (vazifa faqat leader'da ishlaydi).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import IntegrationSyncRun
from app.services.ai_watchdog import ai_stall_message
from app.services.integrations import hemis
from app.services.notifications import dispatcher
from app.services.notifications.messages import Message

logger = logging.getLogger("app.jobs.system_alerts")

KIND = "system"
TITLES = {
    "ai": "AI to'xtab qoldi",
    "disk": "Server diski to'lmoqda",
    "hemis": "HEMIS sinxronlashi ishlamayapti",
}

# muammo kaliti -> oxirgi yuborilgan payt (monotonic)
_active: dict[str, float] = {}


def disk_problem(path: str = "/") -> str | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    percent = usage.used / usage.total * 100 if usage.total else 0.0
    if percent < settings.system_alerts_disk_percent:
        return None
    free_gb = usage.free / 1024**3
    return f"Disk {percent:.0f}% band, {free_gb:.0f} GB qoldi — eski yozuvlar/zaxiralarni tozalang yoki disk qo'shing"


async def hemis_problem(db, now: datetime) -> str | None:
    if not hemis.hemis_configured():
        return None
    runs = (
        await db.execute(
            select(IntegrationSyncRun)
            .where(IntegrationSyncRun.source == hemis.SOURCE, IntegrationSyncRun.status != "ishlamoqda")
            .order_by(IntegrationSyncRun.started_at.desc())
            .limit(20)
        )
    ).scalars().all()
    if not runs:
        return None
    last = runs[0]
    if last.status == "xato":
        reason = (last.error or "sabab noma'lum")[:200]
        return f"Oxirgi sinxronlash xato bilan tugadi: {reason}"
    success = next((r for r in runs if r.status == "muvaffaqiyatli"), None)
    moment = (success.finished_at or success.started_at) if success else None
    if moment is not None and now - moment > timedelta(hours=settings.system_alerts_hemis_hours):
        hours = int((now - moment).total_seconds() // 3600)
        return f"{hours} soatdan beri muvaffaqiyatli sinxronlash bo'lmadi"
    return None


#: Tekshiruvning o'zi yiqildi — holat noma'lum: oldingi holat saqlanadi
#: ("tiklandi" deb ham, yangi ogohlantirish deb ham yuborilmaydi).
CHECK_FAILED = "<tekshiruv-yiqildi>"


async def collect_problems(db, now: datetime) -> dict[str, str]:
    problems: dict[str, str] = {}
    checks = (
        ("ai", lambda: ai_stall_message(db)),
        ("hemis", lambda: hemis_problem(db, now)),
    )
    for key, check in checks:
        try:
            text = await check()
        except Exception:
            logger.warning("system check failed", extra={"check": key}, exc_info=True)
            # Yiqilgan SQL tranzaksiyani buzadi — keyingi tekshiruvlar ishlashi uchun.
            try:
                await db.rollback()
            except Exception:
                pass
            if key in _active:
                problems[key] = CHECK_FAILED
            continue
        if text:
            problems[key] = text
    disk = disk_problem()
    if disk:
        problems["disk"] = disk
    return problems


def plan_messages(problems: dict[str, str], *, now_mono: float) -> list[Message]:
    """Qaysi xabarlar yuboriladi (va _active holatini yangilaydi)."""
    repeat = settings.system_alerts_repeat_hours * 3600
    messages: list[Message] = []
    for key, text in problems.items():
        if text == CHECK_FAILED:
            continue
        last = _active.get(key)
        if last is None or now_mono - last >= repeat:
            _active[key] = now_mono
            messages.append(Message(title=TITLES[key], lines=[("Holat", text)]))
    for key in [k for k in _active if k not in problems]:
        del _active[key]
        messages.append(Message(title=f"{TITLES[key]} — tiklandi", lines=[("Holat", "Muammo hal bo'ldi")]))
    return messages


async def run_system_alerts_once(now: datetime | None = None) -> int:
    if not settings.system_alerts_enabled:
        return 0
    moment = now or datetime.now(timezone.utc)
    async with SessionLocal() as db:
        problems = await collect_problems(db, moment)
        messages = plan_messages(problems, now_mono=time.monotonic())
        for message in messages:
            try:
                logs = await dispatcher._dispatch_rules(db, KIND, message, ref_id=None, filters={"building_id": None})
                if logs:
                    await dispatcher._save_logs(db, logs)
            except Exception:
                logger.warning("system alert dispatch failed", exc_info=True)
        if messages:
            await db.commit()
            logger.warning("system alerts", extra={"event": "system_alerts", "problems": sorted(problems)})
    return len(messages)


async def system_alerts_loop() -> None:
    while True:
        await asyncio.sleep(settings.system_alerts_interval_seconds)
        try:
            await run_system_alerts_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("system alerts failed")


def reset_for_tests() -> None:
    _active.clear()
