"""Shovqinli kamera × modul juftliklarini avtomatik o'chirish.

Operator bir kameraning bir modul signalini qayta-qayta "yolg'on" deb rad
etsa, bu kamera o'sha detektor uchun yaroqsiz (burchak, yorug'lik, xona
turi) — har yangi signal faqat navbatni to'ldiradi. Juftlik
settings.suppression_* chegaralaridan o'tsa module_camera_suppressions ga
yoziladi va app/jobs/module_status.camera_allows_module uni sweeplardan
chiqaradi. AI Modullari sahifasida ko'rinadi va bir tugma bilan
qaytariladi; qaytarilgandan keyin faqat undan KEYINGI baholashlar
hisoblanadi — aks holda juftlik keyingi tekshiruvda yana o'chib qolardi.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.models import Event, ModuleCameraSuppression

logger = logging.getLogger("app.module_suppression")


def _review_columns():
    return (
        func.count().filter(Event.status.in_(("tasdiqlangan", "hal_qilindi"))),
        func.count().filter(Event.status == "rad_etilgan"),
    )


async def run_module_suppression_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> int:
    """Yangi o'chirilgan juftliklar sonini qaytaradi."""
    if not settings.suppression_enabled:
        return 0
    since = datetime.now(timezone.utc) - timedelta(days=settings.suppression_window_days)

    async with session_factory() as db:
        rows = (
            await db.execute(
                select(Event.camera_id, Event.module_code, *_review_columns())
                .where(Event.camera_id.is_not(None))
                .where(Event.reviewed_at >= since)
                .group_by(Event.camera_id, Event.module_code)
            )
        ).all()
        if not rows:
            return 0

        existing = (
            await db.execute(
                select(
                    ModuleCameraSuppression.camera_id,
                    ModuleCameraSuppression.module_code,
                    ModuleCameraSuppression.restored_at,
                )
            )
        ).all()
        active = {(camera_id, code) for camera_id, code, restored in existing if restored is None}
        last_restored: dict[tuple, datetime] = {}
        for camera_id, code, restored in existing:
            if restored is not None and restored > last_restored.get((camera_id, code), since):
                last_restored[(camera_id, code)] = restored

        created = 0
        for camera_id, code, confirmed, rejected in rows:
            pair = (camera_id, code)
            if pair in active:
                continue
            if pair in last_restored:
                confirmed, rejected = (
                    await db.execute(
                        select(*_review_columns())
                        .where(Event.camera_id == camera_id)
                        .where(Event.module_code == code)
                        .where(Event.reviewed_at > last_restored[pair])
                    )
                ).one()
            reviewed = confirmed + rejected
            if reviewed == 0 or rejected < settings.suppression_min_rejected:
                continue
            precision = round(confirmed * 100 / reviewed, 1)
            if precision >= settings.suppression_max_precision:
                continue
            db.add(
                ModuleCameraSuppression(
                    camera_id=camera_id,
                    module_code=code,
                    confirmed=confirmed,
                    rejected=rejected,
                    precision=precision,
                    reason=(
                        f"Oxirgi {settings.suppression_window_days} kunda baholangan {reviewed} ta signalning "
                        f"{rejected} tasi rad etilgan (aniqlik {precision}%)"
                    ),
                )
            )
            created += 1
            logger.warning(
                "module auto-suppressed on camera",
                extra={
                    "camera_id": str(camera_id),
                    "module_code": code,
                    "confirmed": confirmed,
                    "rejected": rejected,
                    "precision": precision,
                },
            )
        if created:
            await db.commit()
        return created
