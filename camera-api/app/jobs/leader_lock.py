"""Ensures only one uvicorn worker process runs the background AI sweep
loops (attendance_ai/vision_ai/fire_ai/camera_health) when the app is
deployed with multiple workers (WEB_CONCURRENCY>1 — see Dockerfile).

Without this, each worker process independently starts its own copy of
every sweep loop (main.py's lifespan runs once per worker process, not
once per app) — at N workers, every camera would be swept N times per
interval, producing duplicate attendance/event writes and N times the
inference load for zero benefit. A single worker process is plenty to run
these loops even at hundreds of cameras once the per-sweep work itself is
parallelized (see app/jobs/attendance_ai.py's _camera_semaphore etc.) —
the loops don't need to be spread across workers, just not duplicated.

Uses a Postgres session-level advisory lock (pg_try_advisory_lock) rather
than introducing a new dependency (Redis, etc.) purely for this: every
worker already has a DB connection, and advisory locks are automatically
released if the holding connection/process dies — a crashed or killed
leader doesn't permanently wedge the lock for the other workers.
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.database import engine

logger = logging.getLogger("app.leader_lock")

# Arbitrary but fixed 64-bit key — must be the same constant every time
# this app acquires it, and picked to be unlikely to collide with any
# other advisory lock this database might use for something unrelated.
_ADVISORY_LOCK_KEY = 847_552_901_337

_lock_connection: AsyncConnection | None = None


async def try_become_leader() -> bool:
    """Attempts to acquire the advisory lock on a DEDICATED connection
    held open for this process's lifetime — closing/returning the
    connection releases the lock, so it must not be reused for anything
    else. Returns True if this process is now the leader (should run the
    background sweep loops), False if another worker already holds it."""
    global _lock_connection
    conn = await engine.connect()
    result = await conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})
    acquired = bool(result.scalar())
    if not acquired:
        await conn.close()
        return False
    await conn.commit()  # advisory locks are session-scoped, not transaction-scoped; this just tidies up
    _lock_connection = conn
    return True


async def release_leadership() -> None:
    global _lock_connection
    if _lock_connection is None:
        return
    try:
        await _lock_connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _ADVISORY_LOCK_KEY})
        await _lock_connection.commit()
    finally:
        await _lock_connection.close()
        _lock_connection = None
