"""Tests for shared global camera sweep concurrency."""

import asyncio

import pytest

from app.jobs import sweep_concurrency
from app.jobs.sweep_concurrency import camera_sweep_slot, reset_global_camera_semaphore_for_tests


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
