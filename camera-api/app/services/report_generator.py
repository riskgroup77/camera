"""Rule-based report generation — every number here is a real aggregate
query against this database (attendance records, AI events, camera
status), not fabricated prose. This is what `source='rule'` means on the
Report model.

`source='llm'` reports (an LLM turning raw stats into a nicer narrative)
are schema-ready but have no generator wired in — that needs a real LLM
API key and an explicit decision about which provider to call, which
isn't configured in this project. Don't fake it by writing static text
and labeling it 'llm'.

Two things this generator is deliberate about.

DATES ARE LOCAL. Events are stored as timestamptz and the containers run
in UTC, so grouping them with plain func.date() answers a question nobody
asked: which UTC day was it. Measured on production at 10:57 local, the
daily report counted 35 events while the local day held 49 — the first
five hours of every day fell into the previous report. Opened before
05:00 local it was labelled with yesterday's date outright.

MISSING DATA IS NOT ZERO. "Attendance 0%" and "no attendance records
exist yet" read identically in a number and mean opposite things: one
says nobody came, the other says nothing has been recorded. The daily
report used to print the first when it meant the second.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AttendanceRecord, Camera, Event, StudentStaff
from app.timezone import local_date, local_now

VALID_PERIODS = ("Kunlik", "Haftalik", "Oylik")

TOP_ROWS = 5
"""How many rows a "busiest N" table shows. Enough to see where the noise
comes from, short enough that the PDF stays one glance per section."""


@dataclass
class ReportSection:
    """A titled table in the report — rendered as rows of label/value."""

    title: str
    rows: list[dict]
    note: str | None = None
    """Shown under the table. Used where a number needs a caveat to be
    read honestly rather than silently misunderstood."""


@dataclass
class GeneratedReport:
    period_label: str
    summary: str
    body: str
    stats: list[dict]
    sections: list[ReportSection] = field(default_factory=list)


def _date_range(period: str, today: date) -> tuple[date, date, str]:
    if period == "Kunlik":
        return today, today, today.isoformat()
    if period == "Haftalik":
        start = today - timedelta(days=6)
        return start, today, f"{start.isoformat()} — {today.isoformat()}"
    if period == "Oylik":
        start = today.replace(day=1)
        return start, today, today.strftime("%Y-%m")
    raise ValueError(f"noto'g'ri period: {period}")


async def _attendance(db: AsyncSession, start: date, end: date) -> tuple[int, int, dict[str, int]]:
    """(records in range, of which present, count per status)."""
    rows = (
        await db.execute(
            select(AttendanceRecord.status, func.count())
            .where(AttendanceRecord.date.between(start, end))
            .group_by(AttendanceRecord.status)
        )
    ).all()
    by_status = {status: count for status, count in rows}
    total = sum(by_status.values())
    present = by_status.get("keldi", 0) + by_status.get("kech_keldi", 0)
    return total, present, by_status


async def generate_rule_based_report(db: AsyncSession, period: str, today: date | None = None) -> GeneratedReport:
    if period not in VALID_PERIODS:
        raise ValueError(f"period {VALID_PERIODS} dan biri bo'lishi kerak")

    # local_now(), not date.today(): the container clock is UTC, so before
    # 05:00 local "today" would be yesterday.
    today = today or local_now().date()
    start, end, period_label = _date_range(period, today)

    occurred_on = local_date(Event.occurred_at)
    in_range = occurred_on.between(start, end)

    total_records, present_records, attendance_by_status = await _attendance(db, start, end)
    attendance_pct = round((present_records / total_records) * 100, 1) if total_records else None

    enrolled = await db.scalar(
        select(func.count())
        .select_from(StudentStaff)
        .where(StudentStaff.biometrics_status == "tasdiqlangan")
    )

    total_events = await db.scalar(select(func.count()).select_from(Event).where(in_range))
    reviewed = (
        await db.execute(
            select(Event.status, func.count()).where(in_range).group_by(Event.status)
        )
    ).all()
    by_event_status = {status: count for status, count in reviewed}
    confirmed_events = by_event_status.get("tasdiqlangan", 0)
    rejected_events = by_event_status.get("rad_etilgan", 0)
    unreviewed_events = by_event_status.get("yangi", 0)

    active_cameras = await db.scalar(select(func.count()).select_from(Camera).where(Camera.status == "faol"))
    total_cameras = await db.scalar(select(func.count()).select_from(Camera))

    by_module = (
        await db.execute(
            select(Event.module_code, Event.module_name, func.count().label("n"))
            .where(in_range)
            .group_by(Event.module_code, Event.module_name)
            .order_by(func.count().desc())
        )
    ).all()

    by_camera = (
        await db.execute(
            select(Event.camera_name, func.count().label("n"))
            .where(in_range)
            .group_by(Event.camera_name)
            .order_by(func.count().desc())
            .limit(TOP_ROWS)
        )
    ).all()

    # Working hours vs the rest. An alert raised in an empty building is
    # worth separating out rather than averaging into a daily total.
    local_hour = func.extract("hour", func.timezone("Asia/Tashkent", Event.occurred_at))
    day_night = (
        await db.execute(
            select(
                func.count().filter(local_hour.between(7, 20)).label("day"),
                func.count().filter(~local_hour.between(7, 20)).label("night"),
            ).where(in_range)
        )
    ).one()
    daytime_events, nighttime_events = int(day_night.day or 0), int(day_night.night or 0)

    per_day = (
        await db.execute(
            select(occurred_on.label("d"), func.count())
            .where(in_range)
            .group_by(occurred_on)
            .order_by(occurred_on)
        )
    ).all()

    attendance_text = (
        f"{attendance_pct}% ({present_records}/{total_records} yozuv asosida)"
        if attendance_pct is not None
        else "hisoblanmadi — bu davr uchun davomat yozuvi yo'q"
    )

    summary = (
        f"{period_label}: davomat {attendance_text}, jami {total_events} ta AI signal "
        f"({confirmed_events} tasdiqlangan, {rejected_events} rad etilgan, {unreviewed_events} ko'rilmagan)."
    )
    body = (
        f"{period_label} davri bo'yicha institut davomati: {attendance_text}. "
        f"AI monitoring tizimi {total_events} ta hodisa qayd etdi — {daytime_events} tasi ish vaqtida "
        f"(07:00-21:00), {nighttime_events} tasi undan tashqarida. Operator tomonidan {confirmed_events} ta "
        f"hodisa tasdiqlangan, {rejected_events} tasi yolg'on signal deb rad etilgan, {unreviewed_events} tasi "
        f"hali ko'rilmagan. Kameralar: {active_cameras}/{total_cameras} faol. "
        f"Biometrik ro'yxatdan o'tgan shaxslar: {enrolled} ta."
    )

    stats = [
        {"label": "Davomat", "value": f"{attendance_pct}%" if attendance_pct is not None else "ma'lumot yo'q"},
        {"label": "AI signallar", "value": str(total_events)},
        {"label": "Ko'rilmagan signallar", "value": str(unreviewed_events)},
        {"label": "Tasdiqlangan", "value": str(confirmed_events)},
        {"label": "Rad etilgan (yolg'on)", "value": str(rejected_events)},
        {"label": "Faol kameralar", "value": f"{active_cameras}/{total_cameras}"},
    ]

    sections: list[ReportSection] = []

    if by_module:
        sections.append(
            ReportSection(
                title="Modul bo'yicha signallar",
                rows=[{"label": f"#{code} {name}", "value": str(n)} for code, name, n in by_module],
            )
        )

    if by_camera:
        sections.append(
            ReportSection(
                title=f"Eng ko'p signal bergan {min(TOP_ROWS, len(by_camera))} kamera",
                rows=[{"label": name, "value": str(n)} for name, n in by_camera],
                note=(
                    "Bitta kameradan kelgan signallar ulushi yuqori bo'lsa, bu odatda o'sha "
                    "kameraning ko'rish maydonidagi muammoni bildiradi, muhitdagi haqiqiy "
                    "hodisalar ko'pligini emas."
                ),
            )
        )

    sections.append(
        ReportSection(
            title="Signallarning vaqt bo'yicha taqsimoti",
            rows=[
                {"label": "Ish vaqtida (07:00-21:00)", "value": str(daytime_events)},
                {"label": "Ish vaqtidan tashqari", "value": str(nighttime_events)},
            ],
            note=(
                "Bino bo'sh bo'lgan vaqtda qayd etilgan signallar alohida tekshirilishi kerak."
                if nighttime_events
                else None
            ),
        )
    )

    if len(per_day) > 1:
        sections.append(
            ReportSection(
                title="Kunlar bo'yicha",
                rows=[{"label": d.isoformat(), "value": str(n)} for d, n in per_day],
            )
        )

    sections.append(
        ReportSection(
            title="Davomat tafsiloti",
            rows=(
                [{"label": status, "value": str(count)} for status, count in sorted(attendance_by_status.items())]
                or [{"label": "Yozuv yo'q", "value": "0"}]
            ),
            note=(
                f"Davomat faqat biometrik ro'yxatdan o'tgan shaxslar uchun yuritiladi — hozir {enrolled} ta. "
                "Ro'yxat to'ldirilmaguncha bu ko'rsatkich butun institutni aks ettirmaydi."
            ),
        )
    )

    return GeneratedReport(
        period_label=period_label,
        summary=summary,
        body=body,
        stats=stats,
        sections=sections,
    )
