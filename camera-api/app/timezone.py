"""The institute's local timezone — every human-facing time-of-day
setting in app/config.py (attendance_ai_late_cutoff, attendance_early_
leave_cutoff, attendance_off_hours_start/end) is written as a LOCAL
clock time: "09:00" means 9 AM at the institute, not 9 AM UTC. Anywhere
one of those gets compared against an actual moment, that moment has to
be converted to this timezone first.

Found as a real, demonstrated bug (not hypothetical): app/jobs/
attendance_ai.py was comparing occurred_at.time() straight off a
UTC-aware datetime. Tashkent is UTC+5, so a person walking in at a real
local 09:12 AM was recorded as UTC 09:12 — which the system then read as
2:12 PM local when checking it against the "09:00" late cutoff, correctly
tripping "late" only by coincidence (any arrival between local 9:00 AM
and 2:00 PM was silently misclassified in one direction or the other).
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement

INSTITUTE_TZ_NAME = "Asia/Tashkent"
INSTITUTE_TZ = ZoneInfo(INSTITUTE_TZ_NAME)


def local_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(INSTITUTE_TZ)


def to_local(moment: datetime) -> datetime:
    """Converts any timezone-aware datetime to the institute's local
    clock time — use this before extracting .date()/.time() to compare
    against a config setting like attendance_ai_late_cutoff."""
    return moment.astimezone(INSTITUTE_TZ)


def local_date(column: ColumnElement) -> ColumnElement:
    """SQL expression for the LOCAL calendar date of a timestamptz column.

    The Python helpers above only fix values that pass through Python.
    Anything grouped or filtered by date in SQL needs this instead, and
    plain func.date() is NOT it: Postgres casts a timestamptz using the
    session timezone, which in these containers is UTC.

    Found as a real bug in the daily report. At 10:57 local it counted 35
    events for "today" while the local day actually held 49 — every event
    between local midnight and 05:00 belongs to the previous UTC date, so
    the first five hours of each day were silently missing. Opened before
    05:00 local, the same report was labelled with YESTERDAY's date.
    """
    return func.date(func.timezone(INSTITUTE_TZ_NAME, column))
