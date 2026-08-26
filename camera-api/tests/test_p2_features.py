"""Tests for central AI scheduler registry and batch inference helpers."""

import pytest

from app.jobs.ai_scheduler import _build_registry, run_scheduler_tick
from app.services.face_recognition import _detect_faces_batch_sync


class TestAISchedulerRegistry:
    def test_build_registry_includes_core_modules(self):
        registry = _build_registry()
        names = {e.name for e in registry}
        assert "fire" in names
        assert "phone" in names
        if __import__("app.config", fromlist=["settings"]).settings.unified_face_sweep_enabled:
            assert "unified_face" in names
        else:
            assert "attendance" in names

    async def test_scheduler_tick_respects_intervals(self, monkeypatch):
        registry = _build_registry()
        calls: list[str] = []

        async def fake_run(**kwargs):
            calls.append("ran")
            return 0

        registry[0].run_once = fake_run  # type: ignore[method-assign]
        registry[0].interval_seconds = 9999
        registry[0].last_run = 0.0

        ran = await run_scheduler_tick(registry)
        assert ran == 0
        assert calls == []


class TestFaceBatchSync:
    def test_batch_sync_empty(self):
        assert _detect_faces_batch_sync([]) == []
