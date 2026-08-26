"""Regression tests for parallel AI scheduler ticks (P0)."""

import asyncio
import time

import pytest

from app.jobs import ai_scheduler
from app.jobs.ai_scheduler import _SweepEntry, run_scheduler_tick


class TestParallelSchedulerTick:
    async def test_due_modules_in_same_tier_run_in_parallel(self):
        started: list[float] = []
        finished: list[float] = []

        async def slow_run(*, session_factory=None):
            started.append(time.monotonic())
            await asyncio.sleep(0.15)
            finished.append(time.monotonic())
            return 0

        registry = [
            _SweepEntry(name="a", interval_seconds=1, run_once=slow_run, tier="standard", last_run=0.0),
            _SweepEntry(name="b", interval_seconds=1, run_once=slow_run, tier="standard", last_run=0.0),
        ]
        t0 = time.monotonic()
        total, critical_ran, standard_ran = await run_scheduler_tick(registry)
        elapsed = time.monotonic() - t0

        assert total == 2
        assert critical_ran == 0
        assert standard_ran == 2
        assert len(started) == 2
        # Sequential would be ~0.30s+; parallel should finish closer to ~0.15s.
        assert elapsed < 0.28
        assert max(finished) - min(started) < 0.25

    async def test_critical_tier_finishes_before_standard_starts(self):
        order: list[str] = []

        async def critical_run(*, session_factory=None):
            order.append("critical_start")
            await asyncio.sleep(0.05)
            order.append("critical_end")
            return 0

        async def standard_run(*, session_factory=None):
            order.append("standard_start")
            return 0

        registry = [
            _SweepEntry(name="crit", interval_seconds=1, run_once=critical_run, tier="critical", last_run=0.0),
            _SweepEntry(name="std", interval_seconds=1, run_once=standard_run, tier="standard", last_run=0.0),
        ]
        await run_scheduler_tick(registry)

        assert order.index("critical_end") < order.index("standard_start")

    async def test_not_due_modules_are_skipped(self):
        calls = {"n": 0}

        async def run(*, session_factory=None):
            calls["n"] += 1
            return 0

        registry = [
            _SweepEntry(name="fresh", interval_seconds=60, run_once=run, tier="standard", last_run=time.monotonic()),
        ]
        total, _, _ = await run_scheduler_tick(registry)
        assert total == 0
        assert calls["n"] == 0

    async def test_one_module_failing_does_not_block_siblings(self):
        async def ok(*, session_factory=None):
            return 1

        async def boom(*, session_factory=None):
            raise RuntimeError("simulated sweep failure")

        registry = [
            _SweepEntry(name="ok", interval_seconds=1, run_once=ok, tier="critical", last_run=0.0),
            _SweepEntry(name="bad", interval_seconds=1, run_once=boom, tier="critical", last_run=0.0),
        ]
        total, critical_ran, _ = await run_scheduler_tick(registry)
        assert total == 2
        assert critical_ran == 2


class TestBuildRegistry:
    def test_registry_includes_dress_code_interval(self, monkeypatch):
        monkeypatch.setattr(ai_scheduler.settings, "unified_face_sweep_enabled", True)
        registry = ai_scheduler._build_registry()
        dress = next(e for e in registry if e.name == "dress_code")
        assert dress.interval_seconds == ai_scheduler.settings.dress_code_ai_interval_seconds

    def test_critical_modules_tagged(self, monkeypatch):
        monkeypatch.setattr(ai_scheduler.settings, "unified_face_sweep_enabled", True)
        registry = ai_scheduler._build_registry()
        critical_names = {e.name for e in registry if e.tier == "critical"}
        assert {"unified_face", "fire", "fall", "zone_entry", "fight"} <= critical_names

    def test_face_path_splits_when_unified_disabled(self, monkeypatch):
        monkeypatch.setattr(ai_scheduler.settings, "unified_face_sweep_enabled", False)
        registry = ai_scheduler._build_registry()
        names = {e.name for e in registry}
        assert "unified_face" not in names
        assert {"attendance", "vision_sleep", "unauthorized", "crowd"} <= names
