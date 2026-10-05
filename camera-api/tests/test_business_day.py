import pytest
"""Ish kuni 06:00 da almashadi (app/timezone.py business_*)."""

from datetime import date, datetime, timedelta, timezone

from app.timezone import INSTITUTE_TZ, business_date, day_bounds, day_start


pytestmark = pytest.mark.six_am_day


def test_early_morning_belongs_to_the_previous_day():
    assert business_date(datetime(2026, 9, 26, 5, 59, tzinfo=INSTITUTE_TZ)) == date(2026, 9, 25)
    assert business_date(datetime(2026, 9, 26, 6, 0, tzinfo=INSTITUTE_TZ)) == date(2026, 9, 26)
    assert business_date(datetime(2026, 9, 26, 23, 59, tzinfo=INSTITUTE_TZ)) == date(2026, 9, 26)
    # UTC paytda ham: 00:30 UTC = 05:30 Toshkent -> kechagi kun
    assert business_date(datetime(2026, 9, 26, 0, 30, tzinfo=timezone.utc)) == date(2026, 9, 25)


def test_day_bounds_run_from_six_to_six():
    start, end = day_bounds(date(2026, 9, 26))
    assert start == datetime(2026, 9, 26, 6, 0, tzinfo=INSTITUTE_TZ) == day_start(date(2026, 9, 26))
    assert end - start == timedelta(days=1)
