from typing import Literal

from app.schemas.base import CamelModel


class AttendanceDayOut(CamelModel):
    """Matches src/types/index.ts `AttendanceDay` — plus early_leave, which
    the frontend type also carries (see app/routers/attendance.py's
    _to_out() for how it's derived: TT kriteriya 9, pure rule-based)."""

    date: str
    status: Literal["keldi", "kelmadi", "kech_keldi", "dam_olish"]
    check_in: str | None = None
    check_out: str | None = None
    early_leave: bool = False


class AttendanceRecordIn(CamelModel):
    student_staff_id: str
    date: str  # YYYY-MM-DD
    status: Literal["keldi", "kelmadi", "kech_keldi", "dam_olish"]
    check_in: str | None = None  # HH:MM
    check_out: str | None = None
