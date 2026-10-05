import asyncio

import pytest

from app.jobs.sweep_guard import SweepGuard


class TestSweepGuard:
    async def test_runs_sweep_when_idle(self):
        guard = SweepGuard("test")
        calls = {"n": 0}

        async def sweep():
            calls["n"] += 1
            return 3

        result = await guard.run(sweep)
        assert result == 3
        assert calls["n"] == 1

    async def test_skips_when_previous_tick_still_running(self):
        guard = SweepGuard("test")
        started = asyncio.Event()
        release = asyncio.Event()
        calls = {"n": 0}

        async def slow_sweep():
            calls["n"] += 1
            started.set()
            await release.wait()
            return 1

        first = asyncio.create_task(guard.run(slow_sweep))
        await started.wait()
        skipped = await guard.run(slow_sweep)
        assert skipped is None
        assert calls["n"] == 1
        release.set()
        assert await first == 1
