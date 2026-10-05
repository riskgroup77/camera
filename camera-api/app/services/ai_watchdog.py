"""AI to'xtab qolganini sezish — boshqaruv panelidagi kritik ogohlantirish.

2026-09-17 16:23 dan 18.09 10:16 gacha AI hech kimni tanimagan (inference
slotlari oqib ketgan edi) va buni 18 soat hech kim sezmagan: sayt ishlab
turardi, kameralar online edi, faqat davomat yozilmasdi. Endi ish vaqtida
kirish kameralari `ai_watchdog_minutes` davomida birorta kadr tahlil
qilmasa, panelda (GET /api/system/resources) kritik ogohlantirish chiqadi.

Ma'lumot manbai — leader jarayonining statistikasi (Redis orqali,
app/services/runtime_snapshot.py): so'rov qaysi worker'ga tushishidan
qat'i nazar bir xil javob. Qotib qolgan kuzatuvchini qayta ishga tushirish
esa app/jobs/attendance_ai.py _reconcile_entrance_watchers ichida.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.jobs.module_status import is_within_behaviour_hours
from app.models import Camera
from app.services.runtime_snapshot import load_recognition_views
from app.timezone import to_local

# Jarayon endigina ishga tushgan bo'lsa statistika bo'sh — bu to'xtash emas.
_started_at = time.monotonic()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def ai_stall_message(db: AsyncSession) -> str | None:
    """Ogohlantirish matni yoki None (hammasi joyida / tekshirib bo'lmaydi)."""
    minutes = settings.ai_watchdog_minutes
    if minutes <= 0 or not is_within_behaviour_hours():
        return None
    if time.monotonic() - _started_at < minutes * 60:
        return None
    entrances = await db.scalar(
        select(func.count())
        .select_from(Camera)
        .where(Camera.status == "faol")
        .where(or_(Camera.is_entrance.is_(True), Camera.is_exit.is_(True)))
    )
    if not entrances:
        return None

    views = await load_recognition_views()
    moments = [view.last_frame_at for view in views.values() if view.cycles and view.last_frame_at]
    latest = max(moments) if moments else None
    if latest is not None and latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    if latest is not None and _now() - latest < timedelta(minutes=minutes):
        return None
    since = f"{to_local(latest):%H:%M} dan beri" if latest else "bugun hali"
    return (
        f"AI kirish kameralarida {since} birorta kadr tahlil qilmadi — davomat yozilmayapti. "
        "ai-worker (yoki api) konteynerini qayta ishga tushiring va loglarini tekshiring"
    )
