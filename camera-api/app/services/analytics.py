"""Hisobotlar sahifasining jonli tahlili — GET /api/reports/analytics.

Eski hisobot (report_generator.py) matn va "yorliq: qiymat" qatorlaridan
iborat edi: grafik ham, oldingi davr bilan solishtirish ham, "nimaga
e'tibor berish kerak" degan xulosa ham yo'q edi — rahbar uni o'qib
qaror chiqara olmasdi. Bu modul bitta davr uchun tuzilgan ma'lumotni
qaytaradi; frontend uni xulosa, KPI va grafiklar sifatida chizadi.
Arxivga saqlanganda aynan shu ma'lumot (reports.payload) saqlanadi, ya'ni
saqlangan hisobot sahifada ko'ringan hisobot bilan bir xil.

report_generator.py dagi ikki qoida bu yerda ham amal qiladi:
  * SANALAR MAHALLIY — timestamptz ustunlar institut vaqtida guruhlanadi
    (app/timezone.local_date), filtr esa indeks ishlashi uchun institut
    yarim tunlariga mos UTC chegaralar bilan;
  * MA'LUMOT YO'QLIGI NOL EMAS — yozuv bo'lmasa foiz None ("—"), 0 emas.

Hisoblangan ifodalar bo'yicha GROUP BY tartib raqami bilan yoziladi
(GROUP BY 1, 2): ifoda ichidagi bog'langan parametrlar SELECT va GROUP BY
da alohida joylashsa Postgres ularni bir xil ifoda deb tanimasligi mumkin.

Server CPU cheklangan: natija qisqa muddat keshlanadi (get_analytics_cached).
"""

from __future__ import annotations

import time as time_module
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import and_, case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIModuleConfig, AttendanceRecord, Camera, Event, Faculty, LessonSession, StudentStaff
from app.schemas.report import (
    AttendanceAnalyticsOut,
    AttendancePopulationOut,
    CameraRowOut,
    CoverageStatOut,
    DailyAttendanceOut,
    DateRangeOut,
    GroupRateOut,
    HistogramBinOut,
    KpiOut,
    LessonDayOut,
    LessonsAnalyticsOut,
    ModuleRowOut,
    ReliabilityOut,
    ReportAnalyticsOut,
    SecurityAnalyticsOut,
    SecurityDayOut,
    SystemAnalyticsOut,
)
from app.services.event_status import OPEN_STATUSES, fold_review_counts, review_bucket
from app.services.report_generator import _attendance_reliability, _working_days
from app.services.attendance_policy import load_policy
from app.services.report_insights import WEAK_PRECISION, InsightInputs, build_insights
from app.timezone import INSTITUTE_TZ, INSTITUTE_TZ_NAME, UZ_MONTHS, local_date, local_now
from app.timezone import business_today, day_start

MAX_RANGE_DAYS = 92
MIN_REVIEWS_FOR_PRECISION = 10
TOP_MODULES = 8
TOP_CAMERAS = 6
TOP_FACULTIES = 12
HIST_START_MINUTES = 6 * 60
HIST_END_MINUTES = 11 * 60
HIST_STEP_MINUTES = 15
# report_generator bilan bir xil: 07:00–20:59 ish vaqti.
WORK_HOUR_START = 7
WORK_HOUR_END = 20

PRESENT = ("keldi", "kech_keldi")
SERIOUS = ("o'rta", "yuqori")
POPULATION_LABELS = {"xodim": "Xodimlar", "talaba": "Talabalar"}
NO_FACULTY = "Fakultetsiz"

CURRENT_TTL_SECONDS = 60
PAST_TTL_SECONDS = 600


class AnalyticsRangeError(ValueError):
    """Noto'g'ri sanalar oralig'i — router 422 qaytaradi."""


def validate_range(start: date, end: date) -> None:
    if start > end:
        raise AnalyticsRangeError("Boshlanish sanasi tugash sanasidan keyin bo'lishi mumkin emas")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise AnalyticsRangeError(f"Oraliq {MAX_RANGE_DAYS} kundan oshmasligi kerak")


def previous_range(start: date, end: date) -> tuple[date, date]:
    """Teng uzunlikdagi, darhol oldin keladigan davr."""
    days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    return prev_end - timedelta(days=days - 1), prev_end


def range_label(start: date, end: date) -> str:
    def day_month(d: date) -> str:
        return f"{d.day}-{UZ_MONTHS[d.month - 1]}"

    if start == end:
        return f"{day_month(start)}, {start.year}"
    if start.year == end.year and start.month == end.month:
        return f"{start.day}–{day_month(end)}, {end.year}"
    if start.year == end.year:
        return f"{day_month(start)} – {day_month(end)}, {end.year}"
    return f"{day_month(start)}, {start.year} – {day_month(end)}, {end.year}"


def _range_out(start: date, end: date) -> DateRangeOut:
    return DateRangeOut(
        start=start.isoformat(), end=end.isoformat(), days=(end - start).days + 1, label=range_label(start, end)
    )


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _day_label(d: date) -> str:
    return f"{d.day:02d}.{d.month:02d}"


def _utc_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """[start 00:00, end+1 00:00) institut vaqtida — timestamptz bilan solishtiriladi."""
    lo = day_start(start)
    hi = day_start(end + timedelta(days=1))
    return lo, hi


def _pct(part: float, whole: float) -> float | None:
    return round(part * 100 / whole, 1) if whole else None


def _fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}%"


def _fmt_count(value: float | None) -> str:
    return "—" if value is None else f"{int(value):,}".replace(",", " ")


def _minutes_to_hhmm(minutes: float) -> str:
    total = int(round(minutes))
    return f"{total // 60:02d}:{total % 60:02d}"


# ── Davomat ─────────────────────────────────────────────────────────────────


def _histogram(counts: dict[int, int]) -> list[HistogramBinOut]:
    first = HIST_START_MINUTES // HIST_STEP_MINUTES
    last = HIST_END_MINUTES // HIST_STEP_MINUTES
    earlier = sum(n for bucket, n in counts.items() if bucket < first)
    later = sum(n for bucket, n in counts.items() if bucket >= last)
    bins = [HistogramBinOut(label=f"{_minutes_to_hhmm(HIST_START_MINUTES)} gacha", count=earlier)]
    bins += [
        HistogramBinOut(label=_minutes_to_hhmm(bucket * HIST_STEP_MINUTES), count=counts.get(bucket, 0))
        for bucket in range(first, last)
    ]
    bins.append(HistogramBinOut(label=f"{_minutes_to_hhmm(HIST_END_MINUTES)} dan keyin", count=later))
    return bins


def _population_out(
    type_: str,
    days: list[date],
    working_days: int,
    day_counts: dict[date, dict[str, int]],
    faculty_counts: dict[str, dict[str, int]],
    hist: dict[int, int],
    avg_minutes: float | None,
    people: dict[str, int],
) -> AttendancePopulationOut:
    by_day: list[DailyAttendanceOut] = []
    totals: dict[str, int] = defaultdict(int)
    for d in days:
        counts = day_counts.get(d, {})
        for status_value, n in counts.items():
            totals[status_value] += n
        keldi, kech, kelmadi = counts.get("keldi", 0), counts.get("kech_keldi", 0), counts.get("kelmadi", 0)
        by_day.append(
            DailyAttendanceOut(
                date=d.isoformat(),
                label=_day_label(d),
                keldi=keldi,
                kech_keldi=kech,
                kelmadi=kelmadi,
                # Maxraj — o'lchangan ish kunlari (dam_olish kirmaydi), hisobot
                # sahifasi va "Institut holati" bilan bir xil.
                rate=_pct(keldi + kech, keldi + kech + kelmadi),
            )
        )

    records = sum(totals.values())
    present = totals["keldi"] + totals["kech_keldi"]
    late = totals["kech_keldi"]

    faculties = sorted(
        (
            GroupRateOut(
                name=name,
                total=sum(c.values()),
                present=c.get("keldi", 0) + c.get("kech_keldi", 0),
                late=c.get("kech_keldi", 0),
                rate=_pct(
                    c.get("keldi", 0) + c.get("kech_keldi", 0),
                    c.get("keldi", 0) + c.get("kech_keldi", 0) + c.get("kelmadi", 0),
                ),
            )
            for name, c in faculty_counts.items()
        ),
        key=lambda row: -row.total,
    )[:TOP_FACULTIES]

    enrolled = people.get("confirmed", 0)
    population = people.get("total", 0)
    short, warnings = _attendance_reliability(records, present, dict(totals), enrolled, population, working_days)
    return AttendancePopulationOut(
        type=type_,
        label=POPULATION_LABELS[type_],
        enrolled=enrolled,
        population=population,
        records=records,
        present=present,
        late=late,
        absent=totals["kelmadi"],
        rate=_pct(present, present + totals["kelmadi"]),
        late_share=_pct(late, present),
        avg_arrival=_minutes_to_hhmm(avg_minutes) if avg_minutes is not None else None,
        by_day=by_day,
        by_faculty=faculties,
        arrival_histogram=_histogram(hist),
        reliability=ReliabilityOut(reliable=records > 0 and short is None, short=short, warnings=warnings),
    )


async def _attendance(
    db: AsyncSession, start: date, end: date, days: list[date], working_days: int
) -> tuple[AttendanceAnalyticsOut, dict[str, dict[str, int]]]:
    person = StudentStaff.id == AttendanceRecord.student_staff_id
    # Faqat faol odamlar — hisobot, "Institut holati" va reyting bilan bir xil to'plam.
    in_range = and_(AttendanceRecord.date.between(start, end), StudentStaff.active.is_(True))

    day_rows = (
        await db.execute(
            select(StudentStaff.type, AttendanceRecord.date, AttendanceRecord.status, func.count())
            .join(StudentStaff, person)
            .where(in_range)
            .group_by(StudentStaff.type, AttendanceRecord.date, AttendanceRecord.status)
        )
    ).all()
    faculty_rows = (
        await db.execute(
            select(StudentStaff.type, Faculty.name, AttendanceRecord.status, func.count())
            .join(StudentStaff, person)
            .outerjoin(Faculty, StudentStaff.faculty_id == Faculty.id)
            .where(in_range)
            .group_by(StudentStaff.type, Faculty.name, AttendanceRecord.status)
        )
    ).all()

    minutes = func.extract("hour", AttendanceRecord.check_in) * 60 + func.extract("minute", AttendanceRecord.check_in)
    arrived = and_(in_range, AttendanceRecord.status.in_(PRESENT), AttendanceRecord.check_in.is_not(None))
    hist_rows = (
        await db.execute(
            select(StudentStaff.type, func.floor(minutes / HIST_STEP_MINUTES), func.count())
            .join(StudentStaff, person)
            .where(arrived)
            .group_by(text("1"), text("2"))
        )
    ).all()
    avg_rows = (
        await db.execute(
            select(StudentStaff.type, func.avg(minutes)).join(StudentStaff, person).where(arrived).group_by(text("1"))
        )
    ).all()
    people_rows = (
        await db.execute(
            select(StudentStaff.type, StudentStaff.biometrics_status, func.count())
            .where(StudentStaff.active.is_(True))
            .group_by(StudentStaff.type, StudentStaff.biometrics_status)
        )
    ).all()

    per_day: dict[str, dict[date, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for type_, day, status_value, count in day_rows:
        per_day[type_][day][status_value] += count
    per_faculty: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for type_, faculty_name, status_value, count in faculty_rows:
        per_faculty[type_][faculty_name or NO_FACULTY][status_value] += count
    per_hist: dict[str, dict[int, int]] = defaultdict(dict)
    for type_, bucket, count in hist_rows:
        per_hist[type_][int(bucket)] = count
    avg_by_type = {type_: float(avg) for type_, avg in avg_rows if avg is not None}
    people: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "confirmed": 0})
    for type_, bio_status, count in people_rows:
        people[type_]["total"] += count
        if bio_status == "tasdiqlangan":
            people[type_]["confirmed"] += count

    def build(type_: str) -> AttendancePopulationOut:
        return _population_out(
            type_,
            days,
            working_days,
            per_day[type_],
            per_faculty[type_],
            per_hist[type_],
            avg_by_type.get(type_),
            people[type_],
        )

    return AttendanceAnalyticsOut(staff=build("xodim"), students=build("talaba")), people


# ── Xavfsizlik (AI signallar) ───────────────────────────────────────────────


async def _security(
    db: AsyncSession, start: date, end: date, days: list[date]
) -> tuple[SecurityAnalyticsOut, list[tuple[str, float, int]]]:
    lo, hi = _utc_bounds(start, end)
    # Sinov rejimidagi modullar signali rahbariyat hisobotiga kirmaydi.
    in_range = and_(Event.occurred_at >= lo, Event.occurred_at < hi, Event.is_trial.is_(False))
    local_ts = func.timezone(INSTITUTE_TZ_NAME, Event.occurred_at)

    day_rows = (
        await db.execute(
            select(local_date(Event.occurred_at), Event.severity, func.count())
            .where(in_range)
            .group_by(text("1"), text("2"))
        )
    ).all()
    # Ish jarayoni holatlari uch toifaga yig'iladi (app/services/event_status.py).
    status_counts = fold_review_counts(
        dict((await db.execute(select(Event.status, func.count()).where(in_range).group_by(Event.status))).all())
    )
    heat_rows = (
        await db.execute(
            select(func.extract("isodow", local_ts), func.extract("hour", local_ts), func.count())
            .where(in_range)
            .group_by(text("1"), text("2"))
        )
    ).all()
    module_rows = (
        await db.execute(
            select(Event.module_code, Event.module_name, Event.status, func.count())
            .where(in_range)
            .group_by(Event.module_code, Event.module_name, Event.status)
        )
    ).all()
    camera_rows = (
        await db.execute(
            select(Event.camera_name, Event.building, func.count())
            .where(in_range)
            .group_by(Event.camera_name, Event.building)
            .order_by(func.count().desc())
            .limit(TOP_CAMERAS)
        )
    ).all()
    # "Ko'rib chiqilmagan" ogohlantirishlari faqat hozirgi modullar bo'yicha:
    # olib tashlangan kriteriyaning eski signalini endi hech kim ko'rib
    # chiqmaydi, u abadiy "shoshilinch" bo'lib turardi.
    registered = select(AIModuleConfig.code)
    registered_codes = set((await db.execute(registered)).scalars().all())
    oldest = await db.scalar(
        select(func.min(Event.occurred_at))
        .where(Event.is_trial.is_(False))
        .where(Event.status.in_(OPEN_STATUSES))
        .where(Event.module_code.in_(registered))
    )
    now = datetime.now(timezone.utc)
    stale_serious = (
        await db.scalar(
            select(func.count())
            .select_from(Event)
            .where(Event.is_trial.is_(False))
            .where(Event.status.in_(OPEN_STATUSES))
            .where(Event.module_code.in_(registered))
            .where(Event.severity.in_(SERIOUS))
            .where(Event.occurred_at < now - timedelta(hours=24))
        )
        or 0
    )

    per_day: dict[date, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for day, severity, count in day_rows:
        per_day[day][severity] += count
    by_day: list[SecurityDayOut] = []
    for d in days:
        c = per_day.get(d, {})
        past, orta, yuqori = c.get("past", 0), c.get("o'rta", 0), c.get("yuqori", 0)
        by_day.append(
            SecurityDayOut(date=d.isoformat(), label=_day_label(d), past=past, orta=orta, yuqori=yuqori, total=past + orta + yuqori)
        )

    heatmap = [[0] * 24 for _ in range(7)]
    for dow, hour, count in heat_rows:
        heatmap[int(dow) - 1][int(hour)] += count
    heatmap_max = max((v for row in heatmap for v in row), default=0)
    night = sum(
        heatmap[d][h] for d in range(7) for h in range(24) if h < WORK_HOUR_START or h > WORK_HOUR_END
    )

    modules: dict[int, dict[str, int | str]] = {}
    for code, name, status_value, count in module_rows:
        row = modules.setdefault(code, {"name": name, "count": 0, "tasdiqlangan": 0, "rad_etilgan": 0, "yangi": 0})
        row["count"] = int(row["count"]) + count
        bucket = review_bucket(status_value)
        row[bucket] = int(row.get(bucket, 0)) + count
    total = sum(int(r["count"]) for r in modules.values())

    module_out: list[ModuleRowOut] = []
    weak: list[tuple[str, float, int]] = []
    for code, r in modules.items():
        confirmed, rejected = int(r["tasdiqlangan"]), int(r["rad_etilgan"])
        reviewed = confirmed + rejected
        precision = _pct(confirmed, reviewed) if reviewed >= MIN_REVIEWS_FOR_PRECISION else None
        module_out.append(
            ModuleRowOut(
                code=code,
                name=str(r["name"]),
                count=int(r["count"]),
                share=_pct(int(r["count"]), total) or 0.0,
                confirmed=confirmed,
                rejected=rejected,
                unreviewed=int(r["yangi"]),
                precision=precision,
            )
        )
        # "Chegarani oshiring" maslahati faqat hali mavjud modulga ma'noli.
        if precision is not None and precision < WEAK_PRECISION and code in registered_codes:
            weak.append((str(r["name"]), precision, reviewed))
    module_out.sort(key=lambda m: -m.count)

    confirmed_total = status_counts.get("tasdiqlangan", 0)
    rejected_total = status_counts.get("rad_etilgan", 0)
    reviewed_total = confirmed_total + rejected_total
    orta_total = sum(d.orta for d in by_day)
    yuqori_total = sum(d.yuqori for d in by_day)

    return (
        SecurityAnalyticsOut(
            total=total,
            serious=orta_total + yuqori_total,
            past=sum(d.past for d in by_day),
            orta=orta_total,
            yuqori=yuqori_total,
            confirmed=confirmed_total,
            rejected=rejected_total,
            unreviewed=status_counts.get("yangi", 0),
            precision=_pct(confirmed_total, reviewed_total) if reviewed_total >= MIN_REVIEWS_FOR_PRECISION else None,
            night=night,
            by_day=by_day,
            heatmap=heatmap,
            heatmap_max=heatmap_max,
            top_modules=module_out[:TOP_MODULES],
            top_cameras=[
                CameraRowOut(name=name, building=building or "", count=count, share=_pct(count, total) or 0.0)
                for name, building, count in camera_rows
            ],
            oldest_unreviewed_hours=round((now - oldest).total_seconds() / 3600, 1) if oldest is not None else None,
            stale_serious_unreviewed=stale_serious,
        ),
        weak,
    )


# ── Darslar ─────────────────────────────────────────────────────────────────


async def _lessons(db: AsyncSession, start: date, end: date, days: list[date]) -> LessonsAnalyticsOut:
    # Faqat haqiqatan o'lchangan darslar: namunasi yo'q dars o'rtachaga
    # qo'shilsa foiz sun'iy ravishda o'zgarardi (ilgari import qilingan
    # darslar soxta 50% bilan kirardi). "Tekshirilgan" — natijasi bor
    # dars; kadr olinmay yopilgani hisobga kirmaydi.
    analyzed = LessonSession.attention_samples > 0
    checked = LessonSession.teacher_on_time.is_not(None)
    active_teacher = LessonSession.activity_samples > 0
    rows = (
        await db.execute(
            select(
                LessonSession.date,
                func.count(),
                func.count().filter(analyzed),
                func.coalesce(func.sum(case((analyzed, LessonSession.attention_score), else_=0)), 0),
                func.coalesce(func.sum(LessonSession.sleep_incidents), 0),
                func.count().filter(checked),
                func.count().filter(and_(checked, LessonSession.teacher_on_time.is_(True))),
                func.count().filter(active_teacher),
                func.coalesce(func.sum(case((active_teacher, LessonSession.teacher_activity_score), else_=0)), 0),
            )
            .where(LessonSession.date.between(start, end))
            .group_by(LessonSession.date)
        )
    ).all()

    per_day = {row[0]: row for row in rows}
    by_day: list[LessonDayOut] = []
    sessions = analyzed_n = attention_sum = sleep = checked_n = on_time = activity_n = activity_sum = 0
    for d in days:
        row = per_day.get(d)
        if row is None:
            by_day.append(LessonDayOut(date=d.isoformat(), label=_day_label(d), sessions=0))
            continue
        _, s, a_n, a_sum, sl, ch, ot, act_n, act_sum = row
        sessions += s
        analyzed_n += a_n
        attention_sum += int(a_sum)
        sleep += int(sl)
        checked_n += ch
        on_time += ot
        activity_n += act_n
        activity_sum += int(act_sum)
        by_day.append(
            LessonDayOut(
                date=d.isoformat(),
                label=_day_label(d),
                sessions=s,
                attention=round(int(a_sum) / a_n, 1) if a_n else None,
                sleep=int(sl),
            )
        )

    return LessonsAnalyticsOut(
        sessions=sessions,
        analyzed_sessions=analyzed_n,
        avg_attention=round(attention_sum / analyzed_n, 1) if analyzed_n else None,
        avg_teacher_activity=round(activity_sum / activity_n, 1) if activity_n else None,
        sleep_incidents=sleep,
        checked_sessions=checked_n,
        teacher_on_time_rate=_pct(on_time, checked_n),
        by_day=by_day,
    )


# ── Tizim holati ────────────────────────────────────────────────────────────


async def _system(db: AsyncSession, people: dict[str, dict[str, int]]) -> SystemAnalyticsOut:
    # Kech import: routers.public ko'p modulni yuklaydi, servis moduli esa
    # import paytida routerlarga bog'lanib qolmasligi kerak.
    from app.routers.public import _is_live_expr

    total = await db.scalar(select(func.count()).select_from(Camera)) or 0
    active = await db.scalar(select(func.count()).select_from(Camera).where(Camera.status == "faol")) or 0
    live = await db.scalar(select(func.count()).select_from(Camera).where(_is_live_expr())) or 0
    coverage = [
        CoverageStatOut(
            type=type_,
            label=POPULATION_LABELS[type_],
            total=people[type_]["total"],
            confirmed=people[type_]["confirmed"],
            percent=_pct(people[type_]["confirmed"], people[type_]["total"]),
        )
        for type_ in ("xodim", "talaba")
    ]
    return SystemAnalyticsOut(
        cameras_total=total, cameras_active=active, cameras_live=live, live_rate=_pct(live, active), coverage=coverage
    )


# ── Oldingi davr (faqat KPI solishtirish uchun) ─────────────────────────────


async def _core(db: AsyncSession, start: date, end: date) -> dict[str, float | int | None]:
    staff_counts = dict(
        (
            await db.execute(
                select(AttendanceRecord.status, func.count())
                .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
                .where(AttendanceRecord.date.between(start, end))
                .where(StudentStaff.type == "xodim")
                .group_by(AttendanceRecord.status)
            )
        ).all()
    )
    records = sum(staff_counts.values())
    present = staff_counts.get("keldi", 0) + staff_counts.get("kech_keldi", 0)

    lo, hi = _utc_bounds(start, end)
    # Sinov rejimidagi modullar signali rahbariyat hisobotiga kirmaydi.
    in_range = and_(Event.occurred_at >= lo, Event.occurred_at < hi, Event.is_trial.is_(False))
    # Ish jarayoni holatlari uch toifaga yig'iladi (app/services/event_status.py).
    status_counts = fold_review_counts(
        dict((await db.execute(select(Event.status, func.count()).where(in_range).group_by(Event.status))).all())
    )
    serious = (
        await db.scalar(select(func.count()).select_from(Event).where(in_range).where(Event.severity.in_(SERIOUS)))
        or 0
    )
    confirmed = status_counts.get("tasdiqlangan", 0)
    reviewed = confirmed + status_counts.get("rad_etilgan", 0)
    return {
        "staff_records": records,
        "staff_rate": _pct(present, records),
        "staff_late": staff_counts.get("kech_keldi", 0) if records else None,
        "serious": serious,
        "unreviewed": status_counts.get("yangi", 0),
        "precision": _pct(confirmed, reviewed) if reviewed >= MIN_REVIEWS_FOR_PRECISION else None,
    }


def _kpi(
    key: str,
    label: str,
    value: float | None,
    previous: float | None,
    *,
    unit: str,
    better: str,
    trend: list[float | None],
    note: str | None = None,
    reliable: bool = True,
) -> KpiOut:
    percent = unit == "%"
    fmt = _fmt_pct if percent else _fmt_count
    delta = None if value is None or previous is None else round(value - previous, 1)
    delta_display = None
    if delta is not None:
        sign = "+" if delta > 0 else ("−" if delta < 0 else "±")
        delta_display = f"{sign}{abs(delta):.1f} f.p." if percent else f"{sign}{int(abs(delta))}"
    return KpiOut(
        key=key,
        label=label,
        value=value,
        display=fmt(value),
        unit=unit,
        previous=previous,
        previous_display=None if previous is None else fmt(previous),
        delta=delta,
        delta_display=delta_display,
        better=better,
        trend=trend,
        note=note,
        reliable=reliable,
    )


async def build_analytics(db: AsyncSession, start: date, end: date) -> ReportAnalyticsOut:
    validate_range(start, end)
    prev_start, prev_end = previous_range(start, end)
    days = _days(start, end)
    working_days = _working_days(start, end)

    attendance, people = await _attendance(db, start, end, days, working_days)
    security, weak_modules = await _security(db, start, end, days)
    lessons = await _lessons(db, start, end, days)
    system = await _system(db, people)
    previous = await _core(db, prev_start, prev_end)

    staff = attendance.staff
    kpis = [
        _kpi(
            "staff_attendance",
            "Xodimlar davomati",
            staff.rate,
            previous["staff_rate"],
            unit="%",
            better="up",
            trend=[d.rate for d in staff.by_day],
            note=staff.reliability.short,
            reliable=staff.reliability.reliable,
        ),
        _kpi(
            "staff_late",
            "Kech qolgan xodimlar",
            staff.late if staff.records else None,
            previous["staff_late"],
            unit="ta",
            better="down",
            trend=[d.kech_keldi for d in staff.by_day],
        ),
        _kpi(
            "serious_events",
            "Jiddiy AI signallar",
            security.serious,
            previous["serious"],
            unit="ta",
            better="down",
            trend=[d.orta + d.yuqori for d in security.by_day],
        ),
        _kpi(
            "unreviewed",
            "Ko'rib chiqilmagan signallar",
            security.unreviewed,
            previous["unreviewed"],
            unit="ta",
            better="down",
            trend=[],
        ),
        _kpi(
            "precision",
            "Signallar aniqligi",
            security.precision,
            previous["precision"],
            unit="%",
            better="up",
            trend=[],
            note=None
            if security.precision is not None
            else f"Kamida {MIN_REVIEWS_FOR_PRECISION} ta ko'rib chiqilgan signal kerak",
            reliable=security.precision is not None,
        ),
        _kpi(
            "cameras_live",
            "Ishlayotgan kameralar",
            system.live_rate,
            None,
            unit="%",
            better="up",
            trend=[],
            note="Hozirgi holat",
        ),
    ]

    await load_policy(db)  # tavsiyadagi kechikish chegarasi (report_insights)
    top_camera = security.top_cameras[0] if security.top_cameras else None
    students_coverage = next(c for c in system.coverage if c.type == "talaba")
    insights = build_insights(
        InsightInputs(
            staff_rate=staff.rate,
            staff_previous_rate=previous["staff_rate"],
            staff_previous_records=int(previous["staff_records"] or 0),
            staff_reliable=staff.reliability.reliable,
            staff_records=staff.records,
            staff_present=staff.present,
            staff_late_share=staff.late_share,
            stale_serious_unreviewed=security.stale_serious_unreviewed,
            oldest_unreviewed_hours=security.oldest_unreviewed_hours,
            total_events=security.total,
            night_events=security.night,
            top_camera_name=top_camera.name if top_camera else None,
            top_camera_share=top_camera.share if top_camera else None,
            weak_modules=weak_modules,
            cameras_active=system.cameras_active,
            cameras_live_rate=system.live_rate,
            students_coverage=students_coverage.percent,
            students_population=students_coverage.total,
        )
    )

    return ReportAnalyticsOut(
        period=_range_out(start, end),
        previous_period=_range_out(prev_start, prev_end),
        generated_at=local_now().strftime("%Y-%m-%d %H:%M"),
        working_days=working_days,
        kpis=kpis,
        insights=insights,
        attendance=attendance,
        security=security,
        lessons=lessons,
        system=system,
    )


_cache: dict[tuple[date, date], tuple[float, ReportAnalyticsOut]] = {}


async def get_analytics_cached(db: AsyncSession, start: date, end: date) -> ReportAnalyticsOut:
    """Sahifa davrlar orasida tez almashtiriladi; bir xil davr uchun hisoblash
    joriy davrda 60 s, o'tgan davrda 10 daqiqa qayta bajarilmaydi."""
    validate_range(start, end)
    key = (start, end)
    now = time_module.monotonic()
    hit = _cache.get(key)
    if hit is not None and hit[0] > now:
        return hit[1]
    result = await build_analytics(db, start, end)
    ttl = CURRENT_TTL_SECONDS if end >= business_today() else PAST_TTL_SECONDS
    if len(_cache) > 64:
        _cache.clear()
    _cache[key] = (now + ttl, result)
    return result


def reset_cache_for_tests() -> None:
    _cache.clear()
