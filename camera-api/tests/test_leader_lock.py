"""app/jobs/leader_lock.py — ensures only one uvicorn worker process runs
the AI sweep loops when WEB_CONCURRENCY>1 (see its module docstring).

Every test here uses a lock key far away from the module's real
_ADVISORY_LOCK_KEY, and/or monkeypatches that constant directly — Postgres
advisory locks are held per (database connection, key), so as long as
these tests never reuse the app's real key, they can run safely even
while a real instance of this app is up and holding its own lock (a
realistic condition in dev, not just a test-isolation nicety)."""

from sqlalchemy import text

from app.database import engine
from app.jobs import leader_lock

TEST_LOCK_KEY = 9_182_736_450_192  # nowhere near the real _ADVISORY_LOCK_KEY (847_552_901_337)


class TestAdvisoryLockMechanics:
    """The underlying pg_try_advisory_lock semantics try_become_leader()/
    release_leadership() are built on."""

    async def test_second_connection_cannot_acquire_a_held_lock(self):
        conn_a = await engine.connect()
        conn_b = await engine.connect()
        try:
            got_a = (await conn_a.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": TEST_LOCK_KEY})).scalar()
            got_b = (await conn_b.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": TEST_LOCK_KEY})).scalar()
            assert got_a is True
            assert got_b is False
        finally:
            await conn_a.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": TEST_LOCK_KEY})
            await conn_a.close()
            await conn_b.close()

    async def test_releasing_frees_the_lock_for_the_next_acquirer(self):
        conn_a = await engine.connect()
        try:
            got_a = (await conn_a.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": TEST_LOCK_KEY})).scalar()
            assert got_a is True
            await conn_a.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": TEST_LOCK_KEY})
        finally:
            await conn_a.close()

        conn_b = await engine.connect()
        try:
            got_b = (await conn_b.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": TEST_LOCK_KEY})).scalar()
            assert got_b is True
            await conn_b.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": TEST_LOCK_KEY})
        finally:
            await conn_b.close()


class TestTryBecomeLeaderAndRelease:
    """End to end through the public functions, with the module's lock
    key monkeypatched to a test-only value each time so these never
    contend with whatever a real running instance of this app might
    currently hold."""

    async def test_round_trip_acquire_then_release(self, monkeypatch):
        monkeypatch.setattr(leader_lock, "_ADVISORY_LOCK_KEY", TEST_LOCK_KEY + 1)

        acquired = await leader_lock.try_become_leader()
        assert acquired is True

        await leader_lock.release_leadership()
        assert leader_lock._lock_connection is None

    async def test_second_attempt_fails_while_first_holds_it(self, monkeypatch):
        monkeypatch.setattr(leader_lock, "_ADVISORY_LOCK_KEY", TEST_LOCK_KEY + 2)

        first = await leader_lock.try_become_leader()
        assert first is True
        try:
            # try_become_leader()'s own module-global state can only track
            # one holder per process, so the "second worker" side of this
            # is simulated with a raw second connection on the same key.
            conn = await engine.connect()
            try:
                got = (
                    await conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": TEST_LOCK_KEY + 2})
                ).scalar()
                assert got is False
            finally:
                await conn.close()
        finally:
            await leader_lock.release_leadership()

    async def test_release_without_ever_acquiring_is_a_safe_no_op(self, monkeypatch):
        monkeypatch.setattr(leader_lock, "_lock_connection", None)
        await leader_lock.release_leadership()  # must not raise
