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

INSTITUTE_TZ = ZoneInfo("Asia/Tashkent")


def local_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(INSTITUTE_TZ)


def to_local(moment: datetime) -> datetime:
    """Converts any timezone-aware datetime to the institute's local
    clock time — use this before extracting .date()/.time() to compare
    against a config setting like attendance_ai_late_cutoff."""
    return moment.astimezone(INSTITUTE_TZ)
