"""Background maintenance sweep — deletes rows that exist for a bounded
time and are useless once past it: RevokedToken (blocklist entries past
their own JWT exp — see the model's docstring), PasswordResetToken (past
expiry or already used/single-use), and AuditLog rows older than the
retention window. No Celery/cron dependency: this runs as a plain asyncio
task started from main.py's lifespan, since a single periodic sweep
doesn't justify a task queue.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal
from app.models import AuditLog, Event, PasswordResetToken, RevokedToken

logger = logging.getLogger("app.cleanup")


async def run_cleanup_once(db: AsyncSession) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    retention_cutoff = now - timedelta(days=settings.audit_log_retention_days)

    revoked_result = await db.execute(delete(RevokedToken).where(RevokedToken.expires_at < now))
    reset_result = await db.execute(
        delete(PasswordResetToken).where(
            (PasswordResetToken.expires_at < now) | (PasswordResetToken.used_at.is_not(None))
        )
    )
    audit_result = await db.execute(delete(AuditLog).where(AuditLog.occurred_at < retention_cutoff))
    event_cutoff = now - timedelta(days=settings.event_retention_days)
    event_result = await db.execute(delete(Event).where(Event.occurred_at < event_cutoff))
    await db.commit()

    counts = {
        "revoked_tokens": revoked_result.rowcount or 0,
        "password_reset_tokens": reset_result.rowcount or 0,
        "audit_logs": audit_result.rowcount or 0,
        "events": event_result.rowcount or 0,
    }
    if any(counts.values()):
        logger.info("cleanup sweep removed expired rows", extra=counts)
    return counts


async def cleanup_loop() -> None:
    """Runs forever, sleeping between sweeps. Errors are caught and logged
    rather than left to crash the loop, so one bad sweep (e.g. a transient
    DB hiccup) doesn't silently stop all future cleanup."""
    interval_seconds = timedelta(hours=settings.cleanup_interval_hours).total_seconds()
    while True:
        try:
            async with SessionLocal() as db:
                await run_cleanup_once(db)
        except Exception:
            logger.exception("cleanup sweep failed")
        await asyncio.sleep(interval_seconds)
