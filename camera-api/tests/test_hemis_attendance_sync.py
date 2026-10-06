"""HEMIS davomatini muntazam olish: bitta odam bo'yicha qaror va qachon nima olinadi."""

from datetime import date, time
from types import SimpleNamespace

import pytest

from app.config import settings
from app.jobs import hemis_photos
from app.jobs.hemis_attendance_sync import plan_runs
from app.services.hemis_attendance_sync import SOURCE, plan_person


def record(source=SOURCE, status="kelmadi", check_in=None):
    return SimpleNamespace(source=source, status=status, check_in=check_in)


class TestPlanPerson:
    def test_new_person_is_inserted(self):
        assert plan_person("talaba", "keldi", time(8, 30), None) == ("insert", ("keldi", time(8, 30)))
        assert plan_person("talaba", "kelmadi", None, None) == ("insert", ("kelmadi", None))

    def test_absent_in_the_morning_present_later_is_upgraded(self):
        """Ertalabki darslarda yo'q -> "kelmadi"; keyingi darsda belgilandi -> "keldi"."""
        assert plan_person("talaba", "keldi", time(11, 30), record()) == ("upgrade", time(11, 30))

    @pytest.mark.parametrize("source", ["kamera", "turniket", "qolda"])
    def test_camera_turnstile_and_manual_records_are_never_touched(self, source):
        assert plan_person("talaba", "keldi", time(9), record(source=source)) == ("skip", None)
        assert plan_person("talaba", "kelmadi", None, record(source=source, status="keldi")) == ("skip", None)

    def test_hemis_present_is_not_downgraded_and_untimed_gets_a_time(self):
        assert plan_person("talaba", "kelmadi", None, record(status="keldi")) == ("skip", None)
        assert plan_person("xodim", "keldi", time(8), record(status="keldi")) == ("retime", time(8))
        assert plan_person("xodim", None, None, None) == ("skip", None)


class TestPlanRuns:
    @pytest.fixture(autouse=True)
    def hours(self, monkeypatch):
        monkeypatch.setattr(settings, "hemis_attendance_start_hour", 8)
        monkeypatch.setattr(settings, "hemis_attendance_end_hour", 19)

    def test_working_hours_sync_today_and_finalize_yesterday_once(self):
        today = date(2026, 10, 6)
        assert plan_runs(10, today, set()) == [(date(2026, 10, 5), True), (today, False)]
        assert plan_runs(10, today, {date(2026, 10, 5)}) == [(today, False)]

    def test_after_hours_today_is_finalized_once(self):
        today = date(2026, 10, 6)
        finalized = {date(2026, 10, 5)}
        assert plan_runs(19, today, finalized) == [(today, True)]
        assert plan_runs(22, today, finalized | {today}) == []

    def test_night_does_nothing_new(self):
        assert plan_runs(3, date(2026, 10, 6), {date(2026, 10, 5)}) == []


def test_single_photo_rule_applies_to_staff_only(monkeypatch):
    monkeypatch.setattr(settings, "hemis_photo_staff_single", True)
    assert hemis_photos.single_photo_allowed(SimpleNamespace(type="xodim"))
    assert not hemis_photos.single_photo_allowed(SimpleNamespace(type="talaba"))
    monkeypatch.setattr(settings, "hemis_photo_staff_single", False)
    assert not hemis_photos.single_photo_allowed(SimpleNamespace(type="xodim"))
