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


class AttendancePersonOut(CamelModel):
    """Davomat sahifasidagi odam kartasi — JSHSHIR va pasportsiz."""

    id: str
    full_name: str
    type: Literal["talaba", "xodim"]
    faculty: str
    unit: str
    biometrics_status: Literal["tasdiqlangan", "kutilmoqda", "yoq"]
    initials: str
    biometric_photo_url: str | None = None


class AttendanceMonthOut(CamelModel):
    """Bir oy yig'indisi. Yozuv bo'lmasa rate va o'rtachalar None — "ma'lumot
    yo'q" 0% bilan bir xil emas."""

    month: str  # "2026-09"
    recorded_days: int  # keldi + kech_keldi + kelmadi (dam olish sanalmaydi)
    present: int
    late: int
    absent: int
    early_leave: int
    rate: float | None = None
    avg_arrival: str | None = None  # "08:47"
    avg_presence_minutes: int | None = None  # kelgan va ketgan vaqt orasi


class AttendanceSummaryOut(CamelModel):
    person: AttendancePersonOut
    months: list[AttendanceMonthOut]
    """Eskidan yangiga; oxirgisi — joriy oy (Toshkent vaqti)."""
    working_weekdays: list[int]
    """ISO hafta kunlari (1 — dushanba). Kalendar "dam olish" va "ma'lumot
    yo'q" kunlarini absence_marker bilan bir xil qoida bo'yicha ajratadi."""
