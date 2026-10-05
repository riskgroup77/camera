"""Situatsion markaz ko'rinishlari (app/routers/situation.py) javob shakllari.

Holatlar:
- kunlik davomat (AttendanceStatus): bazadagi yozuv holati (keldi,
  kech_keldi, kelmadi, dam_olish), yozuv bo'lmasa — "kutilmoqda" (bugun,
  yuzi tasdiqlangan, hali ko'rinmagan) yoki "malumot_yoq" (o'tgan kun yoki
  yuzi tasdiqlanmagan: kamera uni printsipial ravishda taniy olmaydi);
- dars vaqti (LessonState): upcoming / ongoing / finished;
- o'qituvchining darsga kelishi (TeacherStatus): oz_vaqtida, kechikdi,
  kelmadi, kutilmoqda (dars hali boshlanmagan yoki kechikish chegarasi
  o'tmagan), nomalum (tekshirib bo'lmadi — kamera/jadval ma'lumoti yo'q).
"""

from typing import Literal

from app.schemas.base import CamelModel

AttendanceStatus = Literal["keldi", "kech_keldi", "kelmadi", "dam_olish", "kutilmoqda", "malumot_yoq"]
LessonState = Literal["upcoming", "ongoing", "finished"]
TeacherStatus = Literal["oz_vaqtida", "kechikdi", "kelmadi", "kutilmoqda", "nomalum"]


class CountsOut(CamelModel):
    """Bir to'plam odamning bir kundagi davomati.

    present — kelganlar (kech kelganlar ham shu yerda), late — ulardan kech
    kelganlari, absent — "kelmadi" yozuvi borlar, not_yet — yuzi tasdiqlangan,
    lekin bugun hali ko'rinmaganlar, no_data — holatini bilib bo'lmaydiganlar.
    rate = present / (present + absent + not_yet) * 100; asos 0 bo'lsa None."""

    total: int = 0
    enrolled: int = 0
    present: int = 0
    late: int = 0
    absent: int = 0
    day_off: int = 0
    not_yet: int = 0
    no_data: int = 0
    rate: float | None = None


# ─────────────────────────────────────────── 1. Umumiy holat

class TeachersTodayOut(CamelModel):
    """Shu kuni darsi bor o'qituvchilar (har biri bir marta sanaladi):
    absent — kamida bitta darsiga kelmagan, late — kechikkan (kelmagani
    yo'q), on_time — tekshirilgan darslarining hammasiga o'z vaqtida,
    unknown — hali tekshirilmagan / tekshirib bo'lmagan."""

    scheduled: int = 0
    on_time: int = 0
    late: int = 0
    absent: int = 0
    unknown: int = 0


class LessonsSummaryOut(CamelModel):
    total: int = 0
    finished: int = 0
    ongoing: int = 0
    upcoming: int = 0
    avg_attention: float | None = None


class CamerasSummaryOut(CamelModel):
    total: int = 0
    active: int = 0  # status == "faol"
    online: int = 0  # faol va tarmoqda javob beradi
    video_flowing: int = 0  # faol, tarmoqda va tasvir kelmoqda


class EventsSummaryOut(CamelModel):
    open: int = 0  # yangi + jarayonda (sinov signallarisiz)
    today: int = 0  # tanlangan kunda yuz bergan
    high_open: int = 0  # ochiq va "yuqori" muhimlikdagi
    overdue: int = 0  # ochiq va SLA muddati o'tgan


class FacultyStatOut(CountsOut):
    id: str | None = None  # None — "Fakultetsiz"
    name: str


class HourBucketOut(CamelModel):
    hour: int
    students: int = 0
    staff: int = 0
    # Shundan kech kelganlar (davomat yozuvi holati "kech_keldi" — hisobot
    # bilan bitta qoida). Qolgani — o'z vaqtida.
    students_late: int = 0
    staff_late: int = 0


class ArrivalOut(CamelModel):
    id: str
    full_name: str
    photo_url: str | None = None
    initials: str
    type: str  # "talaba" | "xodim"
    unit: str  # talaba — guruh, xodim — kafedra/lavozim
    faculty: str | None = None
    time: str  # "08:47"
    status: str


class OverviewOut(CamelModel):
    date: str
    is_today: bool
    generated_at: str
    students: CountsOut
    staff: CountsOut
    teachers: TeachersTodayOut
    lessons: LessonsSummaryOut
    cameras: CamerasSummaryOut
    events: EventsSummaryOut
    by_faculty: list[FacultyStatOut]
    # Talabalarning yuzi tasdiqlangan ulushi >= 5% bo'lsagina ularning
    # davomat foizi ma'noli — aks holda UI xodimlar + ro'yxatga olish rejimiga o'tadi.
    students_data_available: bool = False
    students_enrolled_pct: float | None = None
    arrivals_by_hour: list[HourBucketOut]
    last_arrivals: list[ArrivalOut]
    # Kechikish chegarasi (ish vaqti sozlamasidan, "HH:MM"): shundan keyin
    # birinchi ko'rinish — "kech keldi". Kelish grafigidagi chiziq.
    late_after_students: str | None = None
    late_after_staff: str | None = None


# ─────────────────────────────────────────── 2-3. Fakultet va guruhlar

class GroupStatOut(CountsOut):
    name: str
    faculty_id: str | None = None
    faculty: str | None = None
    course: int | None = None
    curator: str | None = None


class CourseOut(CamelModel):
    course: int | None = None
    label: str  # "2-kurs" / "Kurs ko'rsatilmagan"
    groups: list[GroupStatOut]
    totals: CountsOut


class FacultyDetailOut(CamelModel):
    id: str
    name: str
    date: str
    is_today: bool
    totals: CountsOut
    courses: list[CourseOut]


# ─────────────────────────────────────────── 4. Guruh

class LessonOut(CamelModel):
    """Bitta dars: vaqti, xonasi, o'qituvchining kelishi, talabalar davomati.

    Dars yakunlangan bo'lsa (finalized) present/late/absent — yakuniy
    natija. Aks holda present — hozircha ishonchli ko'ringanlar, late —
    ulardan kechikib ko'ringanlari, absent — None (hali noma'lum).
    expected — guruhdagi yuzi tasdiqlangan faol talabalar soni."""

    id: str
    date: str
    subject: str
    group_name: str
    faculty: str
    teacher: str
    teacher_id: str | None = None
    teacher_photo_url: str | None = None
    starts_at: str | None = None  # "09:00", Toshkent vaqti
    ends_at: str | None = None
    room: str | None = None  # dars kamerasining nomi
    building: str | None = None
    state: LessonState
    teacher_status: TeacherStatus
    teacher_arrived_at: str | None = None
    teacher_on_time: bool | None = None  # AI tekshiruvining xom natijasi
    expected: int = 0
    present: int = 0
    late: int = 0
    absent: int | None = None
    seen: int = 0
    finalized: bool = False
    attention_score: int | None = None
    activity_score: int | None = None
    sleep_incidents: int = 0


class GroupStudentOut(CamelModel):
    id: str
    full_name: str
    photo_url: str | None = None
    initials: str
    status: AttendanceStatus
    check_in: str | None = None
    check_out: str | None = None
    biometrics_status: str


class TrendPointOut(CamelModel):
    date: str
    rate: float | None = None
    present: int = 0
    late: int = 0
    absent: int = 0


class GroupInfoOut(CamelModel):
    name: str
    faculty_id: str | None = None
    faculty: str | None = None
    course: int | None = None
    totals: CountsOut


class GroupDetailOut(CamelModel):
    date: str
    is_today: bool
    group: GroupInfoOut
    students: list[GroupStudentOut]
    lessons: list[LessonOut]
    trend: list[TrendPointOut]


# ─────────────────────────────────────────── 5-6. Kafedralar

UnitKind = Literal["kafedra", "dekanat", "bolim", "lavozim"]


class KafedraStatOut(CamelModel):
    id: str  # Department.id, "u-<sha1[:10]>" (matndan olingan) yoki "unassigned"
    name: str
    kind: UnitKind = "kafedra"
    building: str | None = None
    unassigned: bool = False
    staff_total: int = 0
    enrolled: int = 0
    present: int = 0
    late: int = 0
    absent: int = 0
    day_off: int = 0
    not_yet: int = 0
    no_data: int = 0
    rate: float | None = None
    lessons_today: int = 0
    teacher_late_lessons: int = 0
    teacher_missed_lessons: int = 0


class TeacherRowOut(CamelModel):
    id: str
    full_name: str
    photo_url: str | None = None
    initials: str
    position: str
    biometrics_status: str
    status: AttendanceStatus
    check_in: str | None = None
    check_out: str | None = None
    # Tanlangan kun (date) darslari
    lessons_scheduled: int = 0
    lessons_on_time: int = 0
    lessons_late: int = 0
    lessons_missed: int = 0
    # Davr (dateFrom..dateTo)
    period_lessons: int = 0
    period_on_time: int = 0
    period_late: int = 0
    period_missed: int = 0
    on_time_rate: float | None = None  # on_time / (on_time + late + missed) * 100
    avg_activity_score: float | None = None
    period_present_days: int = 0
    period_late_days: int = 0
    period_absent_days: int = 0


class PeriodTotalsOut(CamelModel):
    date_from: str
    date_to: str
    lessons: int = 0
    on_time: int = 0
    late: int = 0
    missed: int = 0
    unknown: int = 0
    on_time_rate: float | None = None
    avg_activity_score: float | None = None
    present_days: int = 0
    late_days: int = 0
    absent_days: int = 0


class KafedraDetailOut(CamelModel):
    id: str
    name: str
    kind: UnitKind = "kafedra"
    building: str | None = None
    unassigned: bool = False
    date: str
    is_today: bool
    today: CountsOut
    teachers: list[TeacherRowOut]
    period: PeriodTotalsOut


# ─────────────────────────────────────────── 7. Darslar

class LessonStateCountsOut(CamelModel):
    upcoming: int = 0
    ongoing: int = 0
    finished: int = 0


class LessonPageOut(CamelModel):
    items: list[LessonOut]
    total: int
    page: int
    page_size: int
    total_pages: int
    date: str
    counts: LessonStateCountsOut  # holat filtrisiz (tablar uchun)


# ─────────────────────────────────────────── 8. Shaxs

class PersonInfoOut(CamelModel):
    id: str
    full_name: str
    type: str
    photo_url: str | None = None
    initials: str
    faculty_id: str | None = None
    faculty: str | None = None
    unit: str  # group_or_position xom holda
    # HEMIS lavozimi (xodim).
    position: str | None = None
    # Ro'yxatdan o'tishda saqlangan tomonlar (old, chap, o'ng): 0..3.
    photo_angles: int = 0
    group: str | None = None  # talaba guruhi
    course: int | None = None
    department_id: str | None = None  # xodim kafedrasi (nom bo'yicha topilgan)
    department: str | None = None
    biometrics_status: str
    parent_notify: bool = False
    active: bool = True


class CalendarDayOut(CamelModel):
    date: str
    status: AttendanceStatus
    check_in: str | None = None
    check_out: str | None = None


class PersonTotalsOut(CamelModel):
    days: int = 0
    present: int = 0
    late: int = 0
    absent: int = 0
    day_off: int = 0
    no_data: int = 0
    rate: float | None = None  # present / (present + absent) * 100
    avg_arrival: str | None = None  # "08:41"


class PersonLessonOut(LessonOut):
    # Talaba uchun — shu darsdagi o'z holati (dars yakunlanmagan bo'lsa None)
    attendance_status: str | None = None
    first_seen: str | None = None


class PersonVisitOut(CamelModel):
    id: str
    date: str
    camera: str
    building: str | None = None
    zone: str | None = None
    first_seen: str  # "09:03"
    last_seen: str
    duration_minutes: int
    sightings: int


class PersonProfileOut(CamelModel):
    person: PersonInfoOut
    date_from: str
    date_to: str
    calendar: list[CalendarDayOut]
    totals: PersonTotalsOut
    lessons: list[PersonLessonOut]
    recent_visits: list[PersonVisitOut]


# ─────────────────────────────────────────── 9. Tahlil (app/routers/situation_analytics.py)

PersonType = Literal["xodim", "talaba"]


class PeriodKpisOut(CamelModel):
    rate: float | None = None  # present / (present + absent [+ bugun notYet]) * 100
    avg_arrival: str | None = None  # "08:41"
    avg_arrival_minutes: int | None = None  # kun boshidan daqiqa (solishtirish uchun)
    present: int = 0  # odam-kun (kech kelganlar ham)
    late: int = 0
    absent: int = 0
    punctual_pct: float | None = None  # (present - late) / present * 100
    days_covered: int = 0  # kamida bitta yozuvi bor kunlar


class PeriodDeltaOut(CamelModel):
    """Joriy − oldingi davr. avgArrivalMinutes > 0 — kechroq kelishgan."""

    rate: float | None = None
    avg_arrival_minutes: int | None = None
    late: int = 0
    absent: int = 0
    punctual_pct: float | None = None


class DailyPointOut(CamelModel):
    date: str
    present: int = 0
    late: int = 0
    absent: int = 0
    expected: int = 0
    rate: float | None = None
    avg_arrival: str | None = None


class AnalyticsSummaryOut(CamelModel):
    type: PersonType
    date_from: str
    date_to: str
    previous_from: str
    previous_to: str
    current: PeriodKpisOut
    previous: PeriodKpisOut
    delta: PeriodDeltaOut
    daily: list[DailyPointOut]


class HeatmapWeekdayOut(CamelModel):
    weekday: int  # ISO: 1 = dushanba .. 6 = shanba
    label: str
    counts: list[int]  # `hours` bilan bir xil tartibda
    total: int = 0
    present: int = 0
    late: int = 0
    late_rate: float | None = None


class HeatmapOut(CamelModel):
    type: PersonType
    date_from: str
    date_to: str
    hours: list[int]  # 6..20
    weekdays: list[HeatmapWeekdayOut]
    max: int = 0
    outside: int = 0  # yakshanba yoki 6..20 dan tashqaridagi kelishlar


class UnitAnalyticsOut(CamelModel):
    id: str  # xodim — bo'linma id si; talaba — guruh nomi
    name: str
    kind: Literal["kafedra", "dekanat", "bolim", "lavozim", "guruh"]
    headcount: int = 0
    enrolled: int = 0
    present_days: int = 0
    late_days: int = 0
    absent_days: int = 0
    rate: float | None = None
    avg_arrival: str | None = None
    avg_arrival_minutes: int | None = None
    punctual_pct: float | None = None
    previous_rate: float | None = None
    trend: float | None = None  # rate − previousRate


class PersonRankOut(CamelModel):
    id: str
    full_name: str
    photo_url: str | None = None
    initials: str
    unit_id: str
    unit: str
    present_days: int = 0
    late_days: int = 0
    absent_days: int = 0
    rate: float | None = None
    avg_arrival: str | None = None
    avg_arrival_minutes: int | None = None
    last_seen: str | None = None  # oxirgi kelgan kun (`to` gacha)
    streak: int = 0  # hozirgi uzluksiz kelmadi/kech_keldi kunlari
    streak_kind: Literal["kelmadi", "kech_keldi", "aralash"] | None = None


class ChronicOut(CamelModel):
    id: str
    full_name: str
    photo_url: str | None = None
    initials: str
    unit_id: str
    unit: str
    absent_days: int = 0
    late_days: int = 0
    absent_dates: list[str]
    late_dates: list[str]
    reasons: list[Literal["kelmadi", "kech_keldi"]]


class EnrollCountsOut(CamelModel):
    total: int = 0
    confirmed: int = 0  # biometricsStatus == "tasdiqlangan"
    pending: int = 0  # "kutilmoqda"
    none: int = 0  # "yoq"
    pct: float | None = None  # confirmed / total * 100


class EnrollFacultyOut(EnrollCountsOut):
    id: str | None = None
    name: str


class EnrollmentOut(CamelModel):
    students: EnrollCountsOut
    staff: EnrollCountsOut
    by_faculty: list[EnrollFacultyOut]  # faqat talabalar
    students_data_available: bool = False


class EnrollGroupOut(CamelModel):
    name: str
    faculty_id: str | None = None
    faculty: str | None = None
    course: int | None = None
    total: int = 0
    confirmed: int = 0
    pending: int = 0
    pct: float | None = None


class EnrollMissingPersonOut(CamelModel):
    id: str
    full_name: str
    initials: str
    biometrics_status: str


class EnrollMissingOut(CamelModel):
    group: str
    total: int = 0
    missing: list[EnrollMissingPersonOut]
    enroll_url: str
    #: Guruhning ro'yxatdan o'tish kodi — kartada chop etiladi va
    #: havolaga ham qo'shiladi (app/services/enrollment_code.py).
    enroll_code: str = ""


class WallUnitOut(CamelModel):
    id: str
    name: str
    kind: str
    total: int = 0
    present: int = 0
    rate: float | None = None


class WallEventOut(CamelModel):
    id: str
    module_name: str
    camera_name: str
    building: str
    time: str
    status: str


class SpotlightOut(CamelModel):
    kind: Literal["unit", "group"]
    id: str
    name: str
    rate: float | None = None


class WallOut(CamelModel):
    date: str
    generated_at: str
    students: CountsOut
    staff: CountsOut
    students_data_available: bool = False
    top_units: list[WallUnitOut]
    bottom_units: list[WallUnitOut]
    last_arrivals: list[ArrivalOut]
    high_events: list[WallEventOut]
    cameras_online: int = 0
    # faol (ishlashi kerak bo'lgan) kameralar soni
    cameras_total: int = 0
    # ochiq yuqori xavfli hodisalarning to'liq soni (high_events — so'nggi 5 tasi)
    high_open: int = 0
    enrollment: EnrollmentOut
    spotlight: list[SpotlightOut]
