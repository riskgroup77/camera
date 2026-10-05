"""Hal qilish muddati (due_at) o'tgan hodisalarni ogohlantirish.

Har settings.event_escalation_interval_seconds da: sinov bo'lmagan, hali
qaror qilinmagan (yangi/jarayonda), muddati o'tgan va hali eskalatsiya
qilinmagan hodisalar olinadi, escalated_at qo'yiladi (qayta
yubormaslik uchun), keyin notify_event_overdue chaqiriladi va ochiq
sahifalarga "event_updated" yuboriladi.

Hodisa avval UPDATE ... RETURNING bilan "band qilinadi": bir vaqtda ikki
jarayon ishlasa ham bitta hodisa ikki marta ogohlantirilmaydi.
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import false, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.models import Event, User
from app.services.event_bus import event_to_out
from app.services.event_status import OPEN_STATUSES
from app.services.notifications import notify_event_overdue
from app.ws import manager

logger = logging.getLogger("app.event_escalation")

# Bir aylanishda eng ko'pi bilan shuncha hodisa — qolgani keyingisida.
BATCH_SIZE = 200
MIN_INTERVAL_SECONDS = 5


async def run_escalation_once(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
    *,
    now: datetime | None = None,
) -> int:
    """Eskalatsiya qilingan hodisalar sonini qaytaradi."""
    now = now or datetime.now(timezone.utc)
    async with session_factory() as db:
        due_ids = (
            select(Event.id)
            .where(Event.is_trial == false())
            .where(Event.status.in_(OPEN_STATUSES))
            .where(Event.due_at.is_not(None))
            .where(Event.due_at < now)
            .where(Event.escalated_at.is_(None))
            .order_by(Event.due_at)
            .limit(BATCH_SIZE)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        claimed = (
            (
                await db.execute(
                    update(Event)
                    .where(Event.id.in_(due_ids))
                    .values(escalated_at=now)
                    .returning(Event.id)
                    .execution_options(synchronize_session=False)
                )
            )
            .scalars()
            .all()
        )
        await db.commit()
        if not claimed:
            return 0

        events = (
            (await db.execute(select(Event).where(Event.id.in_(claimed)).order_by(Event.due_at))).scalars().all()
        )
        assignee_ids = {e.assigned_to_id for e in events if e.assigned_to_id}
        names = (
            dict((await db.execute(select(User.id, User.full_name).where(User.id.in_(assignee_ids)))).all())
            if assignee_ids
            else {}
        )
        for event in events:
            try:
                await notify_event_overdue(event)
            except Exception:
                # Bitta bildirishnoma xatosi qolganlarini to'xtatmasin.
                logger.exception("overdue notification failed", extra={"event_id": str(event.id)})
            try:
                out = event_to_out(event, assignee_name=names.get(event.assigned_to_id), now=now)
                await manager.broadcast({**out.model_dump(by_alias=True), "kind": "event_updated"})
            except Exception:
                logger.exception("overdue broadcast failed", extra={"event_id": str(event.id)})
        logger.info("events escalated", extra={"count": len(events)})
        return len(events)


async def event_escalation_loop() -> None:
    while True:
        try:
            await run_escalation_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Baza vaqtincha ishlamasa ham sikl to'xtamasligi kerak.
            logger.exception("event escalation sweep failed")
        await asyncio.sleep(max(MIN_INTERVAL_SECONDS, settings.event_escalation_interval_seconds))
