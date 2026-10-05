"""Hisobot kriteriyalari — "karta -> ro'yxat -> isbot" uch darajasi.

Sahifa shunday ishlaydi: avval populyatsiya (o'qituvchi/xodim yoki
talaba) va davr tanlanadi, so'ng har kriteriya alohida karta bo'lib
raqamlari bilan chiqadi; kartani bosganda o'sha raqam ORTIDAGI odamlar
ro'yxati; odamni bosganda esa uning to'liq ma'lumoti va kamera
isbotlari.
"""

from typing import Literal

from app.schemas.base import CamelModel

Population = Literal["xodim", "talaba"]
PeriodKey = Literal["bugun", "kecha", "hafta", "oy"]


class ReportPeriodOut(CamelModel):
    key: str
    label: str
    start: str
    end: str
    days: int


class ReportBucketOut(CamelModel):
    """Karta ichidagi bitta raqam — ro'yxatga kirish nuqtasi ham shu."""

    key: str
    label: str
    count: int
    tone: Literal["green", "amber", "red", "slate", "indigo"] = "slate"


class ReportCriterionOut(CamelModel):
    key: str
    title: str
    subtitle: str
    total: int = 0
    unit: str = ""
    """Raqam nimani bildiradi: "odam", "kun-yozuv", "signal"."""

    buckets: list[ReportBucketOut] = []
    detail: Literal["people", "events", "none"] = "people"
    """Kartani bosganda nima ochiladi: odamlar ro'yxati yoki signallar."""

    module_codes: list[int] = []
    """Signal kriteriyasi uchun — hodisalar jurnalidagi modul kodlari."""

    note: str | None = None
    """Ma'lumot yig'ilmayotgan bo'lsa — SABABI. Bo'sh raqamni izohsiz
    ko'rsatish "hech kim kelmadi" degan yolg'on xulosaga olib keladi."""


class ReportCriteriaOut(CamelModel):
    population: str
    population_label: str
    period: ReportPeriodOut
    people_total: int
    enrolled_total: int
    criteria: list[ReportCriterionOut] = []


class ReportPersonRowOut(CamelModel):
    """Ro'yxatdagi bitta qator — kartaning raqami ortidagi odam."""

    id: str
    full_name: str
    initials: str
    photo_url: str | None = None
    faculty: str = ""
    unit: str = ""
    biometrics_status: str = "yoq"
    present_days: int = 0
    late_days: int = 0
    absent_days: int = 0
    first_check_in: str | None = None
    last_check_out: str | None = None
    visits: int = 0
    cameras: int = 0
    last_seen_at: str | None = None
    """Oxirgi marta qaysi kamerada ko'rilgani — "isbot bor" belgisi."""

    last_seen_camera: str | None = None


class ReportPersonDayOut(CamelModel):
    date: str
    weekday: str
    status: str | None = None
    check_in: str | None = None
    check_out: str | None = None
    visits: int = 0
    first_camera: str | None = None


class ReportPersonDetailOut(CamelModel):
    """Odamning davr bo'yicha to'liq kesimi. Kunni bosganda o'sha kunning
    kamera tashriflari GET /api/presence/people/{id}/day dan olinadi —
    o'sha yerda har tashrifning kamerasi, vaqti va davomiyligi bor."""

    id: str
    full_name: str
    initials: str
    type: str
    photo_url: str | None = None
    faculty: str = ""
    unit: str = ""
    biometrics_status: str = "yoq"
    biometrics_confirmed_label: str | None = None
    period: ReportPeriodOut
    present_days: int = 0
    late_days: int = 0
    absent_days: int = 0
    working_days: int = 0
    visits: int = 0
    cameras: int = 0
    buildings: list[str] = []
    first_check_in: str | None = None
    last_check_out: str | None = None
    days: list[ReportPersonDayOut] = []
    note: str | None = None
