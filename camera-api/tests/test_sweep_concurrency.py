"""Tests for shared global camera sweep concurrency."""

import asyncio

import pytest

from app.jobs import sweep_concurrency
from app.jobs.sweep_concurrency import (
    camera_sweep_slot,
    entrance_exit_sweep_slot,
    reset_global_camera_semaphore_for_tests,
)


class TestGlobalCameraSemaphore:
    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_global_camera_semaphore_for_tests()
        yield
        reset_global_camera_semaphore_for_tests()

    async def test_caps_total_concurrent_holders(self, monkeypatch):
        monkeypatch.setattr(sweep_concurrency.settings, "ai_global_sweep_concurrency", 2)
        reset_global_camera_semaphore_for_tests()

        inside = {"n": 0}
        peak = {"n": 0}
        lock = asyncio.Lock()

        async def hold():
            async with camera_sweep_slot():
                async with lock:
                    inside["n"] += 1
                    peak["n"] = max(peak["n"], inside["n"])
                await asyncio.sleep(0.05)
                async with lock:
                    inside["n"] -= 1

        await asyncio.gather(*(hold() for _ in range(6)))
        assert peak["n"] == 2


class TestEntranceExitSemaphore:
    """Its own pool, separate from camera_sweep_slot — see
    entrance_exit_sweep_concurrency's docstring in app/config.py for the
    real starvation this separation fixed: entrance/exit's fast, frequent
    burst-grabs were repeatedly claiming a large share of the shared pool
    and delaying every other sweep well past its own configured interval."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_global_camera_semaphore_for_tests()
        yield
        reset_global_camera_semaphore_for_tests()

    async def test_caps_total_concurrent_holders_independently_of_global_pool(self, monkeypatch):
        monkeypatch.setattr(sweep_concurrency.settings, "entrance_exit_sweep_concurrency", 2)
        reset_global_camera_semaphore_for_tests()

        inside = {"n": 0}
        peak = {"n": 0}
        lock = asyncio.Lock()

        async def hold():
            async with entrance_exit_sweep_slot():
                async with lock:
                    inside["n"] += 1
                    peak["n"] = max(peak["n"], inside["n"])
                await asyncio.sleep(0.05)
                async with lock:
                    inside["n"] -= 1

        await asyncio.gather(*(hold() for _ in range(6)))
        assert peak["n"] == 2

    async def test_does_not_share_capacity_with_the_global_pool(self, monkeypatch):
        monkeypatch.setattr(sweep_concurrency.settings, "ai_global_sweep_concurrency", 1)
        monkeypatch.setattr(sweep_concurrency.settings, "entrance_exit_sweep_concurrency", 1)
        reset_global_camera_semaphore_for_tests()

        order: list[str] = []

        async def hold_global():
            async with camera_sweep_slot():
                order.append("global-enter")
                await asyncio.sleep(0.05)
                order.append("global-exit")

        async def hold_entrance_exit():
            async with entrance_exit_sweep_slot():
                order.append("entrance-enter")
                await asyncio.sleep(0.05)
                order.append("entrance-exit")

        # Both pools are capped at 1, but they're independent — a holder
        # of one must NOT block a holder of the other from entering
        # immediately, which sharing a single semaphore would cause.
        await asyncio.gather(hold_global(), hold_entrance_exit())
        assert order[0] in ("global-enter", "entrance-enter")
        assert order[1] in ("global-enter", "entrance-enter")
