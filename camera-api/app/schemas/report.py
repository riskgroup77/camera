from datetime import date as date_type
from typing import Literal

from pydantic import Field

from app.schemas.base import CamelModel


class ReportStatOut(CamelModel):
    label: str
    value: str


class ReportSectionOut(CamelModel):
    title: str
    rows: list[ReportStatOut]
    note: str | None = None


# ── Jonli tahlil: GET /api/reports/analytics (app/services/analytics.py) ──


class DateRangeOut(CamelModel):
    start: str  # "2026-09-01"
    end: str
    days: int
    label: str  # "1–15-sentabr, 2026"


class KpiOut(CamelModel):
    key: str
    label: str
    value: float | None = None
    display: str
    unit: str = ""
    previous: float | None = None
    previous_display: str | None = None
    delta: float | None = None
    delta_display: str | None = None
    # Qaysi yo'nalish yaxshi: davomat o'sishi yaxshi, kechikish o'sishi yomon.
    better: Literal["up", "down", "none"] = "none"
    trend: list[float | None] = []
    note: str | None = None
    reliable: bool = True


class InsightOut(CamelModel):
    level: Literal["critical", "warning", "info", "ok"]
    title: str
    text: str
    action_label: str | None = None
    action_href: str | None = None


class DailyAttendanceOut(CamelModel):
    date: str
    label: str
    keldi: int = 0
    kech_keldi: int = 0
    kelmadi: int = 0
    rate: float | None = None


class GroupRateOut(CamelModel):
    name: str
    total: int
    present: int
    late: int
    rate: float | None = None


class HistogramBinOut(CamelModel):
    label: str
    count: int


class ReliabilityOut(CamelModel):
    reliable: bool
    short: str | None = None
    warnings: list[str] = []


class AttendancePopulationOut(CamelModel):
    type: Literal["xodim", "talaba"]
    label: str
    enrolled: int
    population: int
    records: int
    present: int
    late: int
    absent: int
    rate: float | None = None
    late_share: float | None = None
    avg_arrival: str | None = None
    by_day: list[DailyAttendanceOut] = []
    by_faculty: list[GroupRateOut] = []
    arrival_histogram: list[HistogramBinOut] = []
    reliability: ReliabilityOut


class AttendanceAnalyticsOut(CamelModel):
    staff: AttendancePopulationOut
    students: AttendancePopulationOut


class SecurityDayOut(CamelModel):
    date: str
    label: str
    past: int = 0
    orta: int = 0
    yuqori: int = 0
    total: int = 0


class ModuleRowOut(CamelModel):
    code: int
    name: str
    count: int
    share: float
    confirmed: int
    rejected: int
    unreviewed: int
    precision: float | None = None


class CameraRowOut(CamelModel):
    name: str
    building: str
    count: int
    share: float


class SecurityAnalyticsOut(CamelModel):
    total: int
    serious: int
    past: int
    orta: int
    yuqori: int
    confirmed: int
    rejected: int
    unreviewed: int
    precision: float | None = None
    night: int
    by_day: list[SecurityDayOut] = []
    # 7 × 24: [dushanba..yakshanba][soat 0..23], institut vaqtida.
    heatmap: list[list[int]] = []
    heatmap_max: int = 0
    top_modules: list[ModuleRowOut] = []
    top_cameras: list[CameraRowOut] = []
    # Hozirgi navbat (davrga bog'liq emas): eng eski ko'rilmagan signal yoshi.
    oldest_unreviewed_hours: float | None = None
    stale_serious_unreviewed: int = 0


class LessonDayOut(CamelModel):
    date: str
    label: str
    sessions: int
    attention: float | None = None
    sleep: int = 0


class LessonsAnalyticsOut(CamelModel):
    sessions: int
    analyzed_sessions: int
    avg_attention: float | None = None
    avg_teacher_activity: float | None = None
    sleep_incidents: int
    checked_sessions: int
    teacher_on_time_rate: float | None = None
    by_day: list[LessonDayOut] = []


class CoverageStatOut(CamelModel):
    type: Literal["xodim", "talaba"]
    label: str
    total: int
    confirmed: int
    percent: float | None = None


class SystemAnalyticsOut(CamelModel):
    cameras_total: int
    cameras_active: int
    cameras_live: int
    live_rate: float | None = None
    coverage: list[CoverageStatOut] = []


class ReportAnalyticsOut(CamelModel):
    period: DateRangeOut
    previous_period: DateRangeOut
    generated_at: str
    working_days: int
    kpis: list[KpiOut]
    insights: list[InsightOut]
    attendance: AttendanceAnalyticsOut
    security: SecurityAnalyticsOut
    lessons: LessonsAnalyticsOut
    system: SystemAnalyticsOut


# ── Saqlangan hisobotlar (arxiv) ──


class ReportOut(CamelModel):
    """Matches src/types/index.ts `Report` exactly."""

    id: str
    period: Literal["Kunlik", "Haftalik", "Oylik"]
    period_label: str
    generated_at: str
    source: Literal["rule", "llm"]
    summary: str
    body: str
    stats: list[ReportStatOut]
    sections: list[ReportSectionOut] = []
    range_start: str | None = None
    range_end: str | None = None
    created_by: str | None = None
    # Yangi formatdagi (tahlil ma'lumoti saqlangan) hisobot.
    has_analytics: bool = False
    kpis: list[KpiOut] = []


class ReportDetailOut(ReportOut):
    analytics: ReportAnalyticsOut | None = None


class ReportGenerateIn(CamelModel):
    period: Literal["Kunlik", "Haftalik", "Oylik"]


class ReportCreateIn(CamelModel):
    date_from: date_type = Field(alias="from")
    date_to: date_type = Field(alias="to")
    title: str | None = Field(default=None, max_length=120)
