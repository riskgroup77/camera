"""AI rejalashtiruvchi: har bir sweep mustaqil tsiklda.

Asosiy regressiya: sekin sweep (unified_face) tez sweepni (kirish/chiqish
davomati) bloklamasligi kerak — aynan shu bloklash davomatga hech kim
tushmasligining sababi edi."""

import asyncio

import pytest

from app.jobs import ai_scheduler, scheduler_metrics
from app.jobs.ai_scheduler import _SweepEntry, _sweep_loop, next_pause, run_sweep_once


@pytest.fixture(autouse=True)
def _clean_metrics():
    scheduler_metrics.reset_for_tests()
    yield
    scheduler_metrics.reset_for_tests()


class TestIndependentLoops:
    async def test_slow_sweep_does_not_block_fast_sweep(self, monkeypatch):
        monkeypatch.setattr(ai_scheduler, "MIN_PAUSE_SECONDS", 0.01)
        fast_runs = {"n": 0}

        async def slow(*, session_factory=None):
            await asyncio.sleep(10)
            return 0

        async def fast(*, session_factory=None):
            fast_runs["n"] += 1
            return 0

        slow_entry = _SweepEntry(name="slow", interval_seconds=30, run_once=slow, tier="critical")
        fast_entry = _SweepEntry(name="fast", interval_seconds=0, run_once=fast, tier="critical")
        tasks = [asyncio.create_task(_sweep_loop(slow_entry, 0)), asyncio.create_task(_sweep_loop(fast_entry, 0))]
        await asyncio.sleep(0.3)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        # Eski tick modelida tez sweep sekin sweep tugaguncha (10 s) faqat bir marta ishlardi.
        assert fast_runs["n"] >= 5

    async def test_failing_sweep_is_recorded_and_loop_continues(self, monkeypatch):
        monkeypatch.setattr(ai_scheduler, "MIN_PAUSE_SECONDS", 0.01)
        calls = {"n": 0}

        async def boom(*, session_factory=None):
            calls["n"] += 1
            raise RuntimeError("simulated sweep failure")

        scheduler_metrics.register_sweep("bad", "standard", 0)
        entry = _SweepEntry(name="bad", interval_seconds=0, run_once=boom, tier="standard")
        task = asyncio.create_task(_sweep_loop(entry, 0))
        await asyncio.sleep(0.1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        assert calls["n"] >= 2
        stats = next(s for s in scheduler_metrics.get_sweep_stats() if s.name == "bad")
        assert stats.failures >= 2
        assert "simulated sweep failure" in (stats.last_error or "")


class TestMetrics:
    async def test_dashboard_tick_counts_recent_sweeps(self):
        async def two(*, session_factory=None):
            return {"attendance": 2, "sleep": 0}

        async def zero(*, session_factory=None):
            return 0

        scheduler_metrics.register_sweep("face", "critical", 30)
        scheduler_metrics.register_sweep("dress", "standard", 60)
        await run_sweep_once(_SweepEntry(name="face", interval_seconds=30, run_once=two, tier="critical"))
        await run_sweep_once(_SweepEntry(name="dress", interval_seconds=60, run_once=zero, tier="standard"))

        tick = scheduler_metrics.get_scheduler_tick_stats()
        assert tick.modules_ran == 2
        assert tick.critical_ran == 1
        assert tick.standard_ran == 1
        assert tick.skipped_overlap is False
        face = next(s for s in scheduler_metrics.get_sweep_stats() if s.name == "face")
        assert face.last_result == 2 and face.runs == 1

    def test_pause_is_interval_minus_duration(self):
        assert next_pause(6, 2) == pytest.approx(4)
        assert next_pause(6, 20) == ai_scheduler.MIN_PAUSE_SECONDS


class TestBuildRegistry:
    def test_registry_includes_zone_entry_interval(self, monkeypatch):
        monkeypatch.setattr(ai_scheduler.settings, "unified_face_sweep_enabled", True)
        registry = ai_scheduler._build_registry()
        zone = next(e for e in registry if e.name == "zone_entry")
        assert zone.interval_seconds == ai_scheduler.settings.zone_ai_interval_seconds

    def test_removed_heuristic_modules_are_gone(self, monkeypatch):
        """Ishonchsiz evristikalar olib tashlangan (2026-09-24)."""
        monkeypatch.setattr(ai_scheduler.settings, "unified_face_sweep_enabled", True)
        names = {e.name for e in ai_scheduler._build_registry()}
        assert not names & {"fire", "fight", "disorder", "dress_code", "ppe", "smoking"}

    def test_critical_modules_tagged(self, monkeypatch):
        monkeypatch.setattr(ai_scheduler.settings, "unified_face_sweep_enabled", True)
        registry = ai_scheduler._build_registry()
        critical_names = {e.name for e in registry if e.tier == "critical"}
        assert {"unified_face", "entrance_exit_attendance", "zone_entry"} <= critical_names

    def test_badge_module_is_gone(self, monkeypatch):
        monkeypatch.setattr(ai_scheduler.settings, "unified_face_sweep_enabled", True)
        assert "badge" not in {e.name for e in ai_scheduler._build_registry()}

    def test_face_path_splits_when_unified_disabled(self, monkeypatch):
        monkeypatch.setattr(ai_scheduler.settings, "unified_face_sweep_enabled", False)
        registry = ai_scheduler._build_registry()
        names = {e.name for e in registry}
        assert "unified_face" not in names
        assert {"attendance", "vision_sleep", "unauthorized"} <= names


class TestLaggingIncludesChronicSlowness:
    """Productionda yuz tekshiruvi 30 s o'rniga 296 s davom etgan, panel esa
    "kechikmayapti" degan edi."""

    def _stats(self, *, interval: int, duration: float, finished_ago: float):
        from datetime import datetime, timedelta, timezone

        from app.jobs.scheduler_metrics import SweepRunStats

        now = datetime.now(timezone.utc)
        stats = SweepRunStats(name="unified_face", tier="critical", interval_seconds=interval)
        stats.last_duration_seconds = duration
        stats.last_finished_at = now - timedelta(seconds=finished_ago)
        return stats, now

    def test_a_round_ten_times_longer_than_its_interval_is_lagging(self):
        stats, now = self._stats(interval=30, duration=296, finished_ago=5)
        assert stats.is_lagging(now) is True

    def test_a_round_within_budget_is_not_lagging(self):
        stats, now = self._stats(interval=30, duration=12, finished_ago=5)
        assert stats.is_lagging(now) is False

    def test_short_interval_gets_a_one_minute_floor(self):
        stats, now = self._stats(interval=6, duration=40, finished_ago=1)
        assert stats.is_lagging(now) is False
