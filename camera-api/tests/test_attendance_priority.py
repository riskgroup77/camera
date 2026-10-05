"""Tirband soatlarda davomatga ustuvorlik va kirish kameralarini fonda tekshirish.

Productionda o'lchangan: bitta AVX'siz CPU'da 6 s lik kirish tekshiruvi
263 s davom etgan — og'ir evristikalar (yong'in, jang, tartib, xalat,
niqob) bilan talashgani va bitta sweep 11 kameraning eng sekini tugashini
kutgani uchun."""

import asyncio
from datetime import time

import pytest

from app.config import settings
from app.jobs import ai_scheduler, scheduler_metrics
from app.jobs.ai_scheduler import _SweepEntry, _sweep_loop, is_paused_for_attendance
from app.jobs.module_status import is_within_attendance_priority_window
from app.services import recognition_stats


@pytest.fixture(autouse=True)
def _clean():
    scheduler_metrics.reset_for_tests()
    recognition_stats.reset_for_tests()
    yield
    scheduler_metrics.reset_for_tests()
    recognition_stats.reset_for_tests()


class TestPriorityWindow:
    @pytest.mark.parametrize(
        "moment,expected",
        [(time(7, 29), False), (time(7, 30), True), (time(9, 30), True), (time(12, 0), False),
         (time(16, 30), True), (time(18, 1), False)],
    )
    def test_default_rush_hours(self, monkeypatch, moment, expected):
        monkeypatch.setattr(settings, "attendance_priority_windows", "07:30-09:30,16:00-18:00")
        assert is_within_attendance_priority_window(moment) is expected

    def test_window_across_midnight(self, monkeypatch):
        monkeypatch.setattr(settings, "attendance_priority_windows", "22:00-02:00")
        assert is_within_attendance_priority_window(time(23, 0)) is True
        assert is_within_attendance_priority_window(time(1, 0)) is True
        assert is_within_attendance_priority_window(time(12, 0)) is False

    def test_malformed_window_never_pauses_all_day(self, monkeypatch):
        monkeypatch.setattr(settings, "attendance_priority_windows", "yomon, 25:99-xx")
        assert is_within_attendance_priority_window(time(8, 0)) is False


class TestWhichSweepsPause:
    def _inside(self, monkeypatch):
        monkeypatch.setattr(ai_scheduler, "is_within_attendance_priority_window", lambda: True)

    def test_heavy_heuristics_pause_attendance_never(self, monkeypatch):
        self._inside(monkeypatch)
        monkeypatch.setattr(settings, "attendance_priority_enabled", True)
        monkeypatch.setattr(settings, "attendance_priority_paused_sweeps", "lesson_quality,zone_entry")
        for name in ("lesson_quality", "zone_entry"):
            assert is_paused_for_attendance(name) is True
        # Yong'in — hayot xavfsizligi: sozlamada yozilgan bo'lsa ham to'xtamaydi.
        for name in ("entrance_exit_attendance", "unified_face", "absence_marking"):
            assert is_paused_for_attendance(name) is False

    def test_disabled_setting_pauses_nothing(self, monkeypatch):
        self._inside(monkeypatch)
        monkeypatch.setattr(settings, "attendance_priority_enabled", False)
        assert is_paused_for_attendance("zone_entry") is False

    async def test_paused_loop_does_not_run_and_is_not_reported_as_lagging(self, monkeypatch):
        calls = {"n": 0}

        async def run(*, session_factory=None):
            calls["n"] += 1
            return 0

        monkeypatch.setattr(ai_scheduler, "is_paused_for_attendance", lambda name: True)
        monkeypatch.setattr(ai_scheduler, "PAUSE_RECHECK_SECONDS", 0.01)
        scheduler_metrics.register_sweep("zone_entry", "critical", 30)
        task = asyncio.create_task(_sweep_loop(_SweepEntry(name="zone_entry", interval_seconds=30, run_once=run, tier="critical"), 0))
        await asyncio.sleep(0.1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        assert calls["n"] == 0
        stats = scheduler_metrics.get_sweep_stats()[0]
        assert stats.paused is True
        from datetime import datetime, timedelta, timezone

        assert stats.is_lagging(datetime.now(timezone.utc) + timedelta(hours=2)) is False
        assert scheduler_metrics.export_sweeps()[0]["paused"] is True


class TestCycleTiming:
    def test_cycle_time_is_exported_for_other_workers(self):
        recognition_stats.record_cycle("cam-9", total_seconds=263.4, grab_seconds=240.04)
        row = recognition_stats.export_snapshot()["cam-9"]
        assert row["cycles"] == 1
        assert row["last_cycle_seconds"] == 263.4 and row["last_grab_seconds"] == 240.0
        view = recognition_stats.view_from_dict(row)
        assert view.last_cycle_seconds == 263.4
