"""Rule-based report generation — every number here is a real aggregate
query against this database (attendance records, AI events, camera
status), not fabricated prose. This is what `source='rule'` means on the
Report model.

`source='llm'` reports (an LLM turning raw stats into a nicer narrative)
are schema-ready but have no generator wired in — that needs a real LLM
API key and an explicit decision about which provider to call, which
isn't configured in this project. Don't fake it by writing static text
and labeling it 'llm'.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AttendanceRecord, Camera, Event

VALID_PERIODS = ("Kunlik", "Haftalik", "Oylik")


@dataclass
class GeneratedReport:
    period_label: str
    summary: str
    body: str
    stats: list[dict]


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


async def generate_rule_based_report(db: AsyncSession, period: str, today: date | None = None) -> GeneratedReport:
    if period not in VALID_PERIODS:
        raise ValueError(f"period {VALID_PERIODS} dan biri bo'lishi kerak")

    today = today or date.today()
    start, end, period_label = _date_range(period, today)

    total_attendance = await db.scalar(
        select(func.count()).select_from(AttendanceRecord).where(AttendanceRecord.date.between(start, end))
    )
    present_attendance = await db.scalar(
        select(func.count())
        .select_from(AttendanceRecord)
        .where(AttendanceRecord.date.between(start, end))
        .where(AttendanceRecord.status.in_(["keldi", "kech_keldi"]))
    )
    attendance_pct = round((present_attendance / total_attendance) * 100, 1) if total_attendance else 0.0

    event_date = func.date(Event.occurred_at)
    total_events = await db.scalar(select(func.count()).select_from(Event).where(event_date.between(start, end)))
    confirmed_events = await db.scalar(
        select(func.count()).select_from(Event).where(event_date.between(start, end)).where(Event.status == "tasdiqlangan")
    )
    rejected_events = await db.scalar(
        select(func.count()).select_from(Event).where(event_date.between(start, end)).where(Event.status == "rad_etilgan")
    )

    active_cameras = await db.scalar(select(func.count()).select_from(Camera).where(Camera.status == "faol"))
    total_cameras = await db.scalar(select(func.count()).select_from(Camera))

    summary = (
        f"{period_label} davri uchun umumiy davomat {attendance_pct}%, jami {total_events} ta AI signal "
        f"qayd etildi ({confirmed_events} tasdiqlangan, {rejected_events} rad etilgan)."
    )
    body = (
        f"{period_label} davomida institut bo'yicha umumiy davomat {attendance_pct}% ni tashkil etdi "
        f"({present_attendance}/{total_attendance} yozuv asosida). AI monitoring tizimi jami {total_events} ta "
        f"hodisani qayd etdi — shulardan {confirmed_events} tasi admin tomonidan tasdiqlandi, {rejected_events} tasi "
        f"yolg'on ijobiy sifatida rad etildi. Hozirgi holatda {active_cameras}/{total_cameras} kamera faol holatda "
        f"ishlamoqda."
    )
    stats = [
        {"label": "Umumiy davomat", "value": f"{attendance_pct}%"},
        {"label": "AI signallar", "value": str(total_events)},
        {"label": "Tasdiqlangan hodisalar", "value": str(confirmed_events)},
        {"label": "Rad etilgan (yolg'on ijobiy)", "value": str(rejected_events)},
        {"label": "Faol kameralar", "value": f"{active_cameras}/{total_cameras}"},
    ]

    return GeneratedReport(period_label=period_label, summary=summary, body=body, stats=stats)
