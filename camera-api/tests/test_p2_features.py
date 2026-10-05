"""Tests for central AI scheduler registry and batch inference helpers."""

import pytest

from app.jobs.ai_scheduler import _build_registry, next_pause
from app.services.face_recognition import _detect_faces_batch_sync


class TestAISchedulerRegistry:
    def test_build_registry_includes_core_modules(self):
        registry = _build_registry()
        names = {e.name for e in registry}
        assert "zone_entry" in names
        assert "teacher_punctuality" in names
        if __import__("app.config", fromlist=["settings"]).settings.unified_face_sweep_enabled:
            assert "unified_face" in names
        else:
            assert "attendance" in names

    def test_each_sweep_waits_only_the_rest_of_its_own_interval(self):
        # Mustaqil tsikllar: sweep o'z intervalidan uzoq ishlasa ham boshqalarni kutmaydi.
        registry = _build_registry()
        entrance = next((e for e in registry if e.name == "entrance_exit_attendance"), None)
        if entrance is not None:
            assert next_pause(entrance.interval_seconds, 1.0) == entrance.interval_seconds - 1.0


class TestFaceBatchSync:
    def test_batch_sync_empty(self):
        assert _detect_faces_batch_sync([]) == []
