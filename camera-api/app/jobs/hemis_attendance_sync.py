"""Davomatni HEMIS'dan muntazam olish (app/services/hemis_attendance_sync.py).

O'qituvchilar HEMIS'da har darsni kun davomida belgilab boradi. Shu sababli:
  * ish soatlarida (settings.hemis_attendance_start_hour..end_hour) har
    hemis_attendance_interval_minutes da BUGUNGI kun olinadi;
  * tugash soatidan keyin bir marta — bugun yakuniy (darsi jadvalda
    bo'lib, birorta darsi o'tkazilmagan o'qituvchi "kelmadi");
  * jarayon ishga tushganda va har yangi kun ertalab — KECHA yakuniy
    (kechqurun belgilanganlar ham tushadi).
Hammasi idempotent: qayta ishga tushirish yozuvlarni ikkilantirmaydi.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

from app.config import settings
from app.services.hemis_attendance_sync import sync_day
from app.services.integrations import hemis
from app.timezone import business_today, local_now

logger = logging.getLogger("app.jobs.hemis_attendance_sync")


def plan_runs(hour: int, today: date, finalized: set[date]) -> list[tuple[date, bool]]:
    """Shu tekshiruvda nima olinadi: [(kun, yakuniy)]. Toza funksiya — sinovlanadi."""
    runs: list[tuple[date, bool]] = []
    yesterday = today - timedelta(days=1)
    if yesterday not in finalized:
        runs.append((yesterday, True))
    start, end = settings.hemis_attendance_start_hour, settings.hemis_attendance_end_hour
    if start <= hour < end:
        runs.append((today, False))
    elif hour >= end and today not in finalized:
        runs.append((today, True))
    return runs


async def run_hemis_attendance_once(finalized: set[date]) -> list[str]:
    if not settings.hemis_attendance_sync_enabled or not hemis.hemis_active():
        return []
    report: list[str] = []
    for day, final in plan_runs(local_now().hour, business_today(), finalized):
        result = await sync_day(day, apply=True, finalize=final)
        if final:
            finalized.add(day)
        report.append(
            f"{day}{' (yakuniy)' if final else ''}: +{sum(result.inserted.values())} yozuv, "
            f"o'qituvchi kelmadi {result.teachers_absent}, kelmadi->keldi {result.upgraded}"
        )
        logger.info(
            "HEMIS attendance synced",
            extra={
                "event": "hemis_attendance",
                "day": day.isoformat(),
                "final": final,
                "inserted": dict((f"{k[0]}:{k[1]}", v) for k, v in result.inserted.items()),
                "teachers_absent": result.teachers_absent,
                "upgraded": result.upgraded,
            },
        )
    # Xotira cheksiz o'smasin.
    for day in [d for d in finalized if d < business_today() - timedelta(days=3)]:
        finalized.discard(day)
    return report


async def hemis_attendance_loop() -> None:
    finalized: set[date] = set()
    # Boshqa ishga tushish vazifalari (HEMIS sinxronlash, oqimlar) bilan bir paytga tushmasin.
    await asyncio.sleep(90)
    while True:
        try:
            await run_hemis_attendance_once(finalized)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("HEMIS attendance sync failed")
        await asyncio.sleep(max(60, settings.hemis_attendance_interval_minutes * 60))
