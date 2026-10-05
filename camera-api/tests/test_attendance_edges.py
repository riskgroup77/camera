import pytest
"""Davomatning chegaraviy holatlari: 06:00 dan boshlanadigan ish kunida tun
yarmidan keyingi ko'rinish, qo'lda tuzatilgan yozuv va turniket sanasi."""

from datetime import datetime, time, timezone
from types import SimpleNamespace

from app.jobs.attendance_ai import _is_earlier_arrival, _is_later_sighting
from app.services.integrations.access_control import _attendance_changes
from app.timezone import business_date, business_seconds


pytestmark = pytest.mark.six_am_day


def rec(status="kech_keldi", check_in=time(9, 30), check_out=None, source="kamera"):
    return SimpleNamespace(status=status, check_in=check_in, check_out=check_out, source=source)


def test_business_seconds_orders_the_night_after_the_day():
    assert business_seconds(time(6, 0)) == 0
    assert business_seconds(time(1, 30)) > business_seconds(time(23, 0)) > business_seconds(time(9, 30))


def test_night_sighting_does_not_rewrite_the_morning_arrival():
    # 01:30 (tun) — o'sha ish kunining OXIRI, kelish emas.
    assert not _is_earlier_arrival(rec(), time(1, 30))
    assert _is_earlier_arrival(rec(), time(8, 0))
    assert _is_later_sighting(rec(), time(1, 30))


def test_manual_correction_is_never_overwritten():
    manual = rec(status="kelmadi", check_in=None, source="qolda")
    assert not _is_earlier_arrival(manual, time(8, 0))
    assert not _is_later_sighting(rec(source="qolda"), time(15, 0))
    assert _attendance_changes(manual, time(8, 0), "kirish", True, lambda d: ("keldi", time(8, 0))) == {}


def test_turnstile_night_exit_is_a_check_out_not_an_arrival():
    changes = _attendance_changes(rec(check_in=time(9, 0)), time(0, 40), "chiqish", True, lambda d: ("keldi", time(0, 40)))
    assert changes.get("check_out") in (time(0, 40), None)
    assert "check_in" not in changes


def test_turnstile_uses_the_business_date():
    # 00:40 Toshkent (19:40 UTC oldingi kun) — kechagi ish kuni.
    moment = datetime(2026, 9, 21, 19, 40, tzinfo=timezone.utc)
    assert business_date(moment).isoformat() == "2026-09-21"
