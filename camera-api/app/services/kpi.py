"""Rahbariyat KPI paneli — GET /api/kpi (app/routers/kpi.py).

Rahbar bitta ekranda to'rt savolga javob ko'rishi kerak: odamlar
kelyaptimi (davomat), kamera ularni taniyaptimi (tanish sifati),
signallarga tez javob berilyaptimi (xavfsizlik), tizimning o'zi
ishlayaptimi (infratuzilma). Har blok alohida sahifalarda allaqachon bor —
bu yerda faqat yig'iladi:

  * davomat foizi — situation_analytics.daily/period_kpis (Situatsion
    markaz tahlili bilan AYNAN bir qoida, raqamlar bir-biridan farq
    qilmasin);
  * biometrik qamrov — situation_analytics.enrollment;
  * kameralar — situation.camera_summary (is_reachable qoidasi).

Yangi SQL faqat hali hech qayerda hisoblanmaganlar uchun: kuniga
tanilganlar ulushi va hodisaga javob vaqti. Sinov rejimidagi modul
signallari (is_trial) hisobga kirmaydi — ular operator navbatiga ham
tushmaydi, javob vaqtini buzardi.
"""

from __future__ import annotations

from datetime import date as date_type, datetime, time, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AttendanceRecord, Event, StudentStaff, UnknownSighting
from app.services import situation as svc, situation_analytics as sa
from app.services.event_status import CONFIRMED_STATUSES, OPEN_STATUSES, REJECTED_STATUSES
from app.timezone import INSTITUTE_TZ
from app.timezone import day_start

# Kamera tanigan deb hisoblanadigan manbalar. Qo'lda kiritilgan va turniket
# yozuvi "yuz tanildi" degani emas; manbasi yo'q eski yozuvlar kamera
# davridan qolgan.
RECOGNISED_SOURCES = ("kamera", "dars")


def _bounds(start: date_type, end: date_type) -> tuple[datetime, datetime]:
    lo = day_start(start)
    hi = day_start(end + timedelta(days=1))
    return lo, hi


def _minutes(seconds: float | None) -> float | None:
    return round(float(seconds) / 60, 1) if seconds is not None else None


# ─────────────────────────────────────────── davomat

def _att_block(cur: dict, prev: dict) -> dict:
    late_pct = svc.pct(cur["late"], cur["present"])
    prev_late = svc.pct(prev["late"], prev["present"])
    return {
        "rate": cur["rate"],
        "prevRate": prev["rate"],
        "latePct": late_pct,
        "prevLatePct": prev_late,
        "present": cur["present"],
        "late": cur["late"],
        "absent": cur["absent"],
        "daysCovered": cur["days_covered"],
    }


async def attendance(db: AsyncSession, start: date_type, end: date_type) -> dict:
    prev_start, prev_end = sa.previous_period(start, end)
    out = {}
    for type_, key in (("talaba", "students"), ("xodim", "staff")):
        cur = sa.period_kpis((await sa.daily(db, type_, start, end)).values())
        prev = sa.period_kpis((await sa.daily(db, type_, prev_start, prev_end)).values())
        out[key] = _att_block(cur, prev)
    out["previous"] = {"from": prev_start.isoformat(), "to": prev_end.isoformat()}
    return out


# ─────────────────────────────────────────── tanish sifati

async def recognised_daily_pct(db: AsyncSession, start: date_type, end: date_type, enrolled: int) -> float | None:
    """Yuzi tasdiqlanganlarning kuniga necha foizini kamera tanidi (o'rtacha).

    Faqat kamida bitta tanilgan odam bo'lgan kunlar olinadi — dam olish
    kuni yoki tizim ishlamagan kun o'rtachani nolga tortmasin."""
    end = min(end, svc.today())
    if not enrolled or start > end:
        return None
    rows = await db.execute(
        select(AttendanceRecord.date, func.count(func.distinct(AttendanceRecord.student_staff_id)))
        .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
        .where(StudentStaff.active.is_(True), sa.enrolled_flag())
        .where(AttendanceRecord.date.between(start, end))
        .where(AttendanceRecord.status.in_(svc.PRESENT_STATUSES))
        .where(or_(AttendanceRecord.source.is_(None), AttendanceRecord.source.in_(RECOGNISED_SOURCES)))
        .group_by(AttendanceRecord.date)
    )
    counts = [n for _d, n in rows.all() if n]
    if not counts:
        return None
    return round(sum(min(n, enrolled) for n in counts) * 100 / (len(counts) * enrolled), 1)


async def recognition(db: AsyncSession, start: date_type, end: date_type) -> dict:
    enroll = await sa.enrollment(db)
    students, staff = enroll["students"], enroll["staff"]
    pending = (
        await db.execute(select(func.count()).select_from(UnknownSighting).where(UnknownSighting.status == "kutilmoqda"))
    ).scalar_one()
    return {
        "studentsCoverage": students["pct"],
        "staffCoverage": staff["pct"],
        "studentsEnrolled": students["confirmed"],
        "studentsTotal": students["total"],
        "staffEnrolled": staff["confirmed"],
        "staffTotal": staff["total"],
        "recognisedDailyPct": await recognised_daily_pct(db, start, end, students["confirmed"] + staff["confirmed"]),
        "unknownPending": int(pending),
    }


# ─────────────────────────────────────────── xavfsizlik

async def security(db: AsyncSession, start: date_type, end: date_type) -> dict:
    lo, hi = _bounds(start, end)
    in_range = and_(Event.occurred_at >= lo, Event.occurred_at < hi, Event.is_trial.is_(False))
    reviewed = Event.status.not_in(OPEN_STATUSES)
    rejected = Event.status.in_(REJECTED_STATUSES)
    confirmed = Event.status.in_(CONFIRMED_STATUSES)
    review_secs = func.extract("epoch", Event.reviewed_at - Event.occurred_at)
    resolve_secs = func.extract("epoch", Event.resolved_at - Event.occurred_at)
    has_review = and_(Event.reviewed_at.is_not(None), Event.reviewed_at >= Event.occurred_at)
    has_resolve = and_(Event.resolved_at.is_not(None), Event.resolved_at >= Event.occurred_at)
    cols = (
        func.count(),
        func.count().filter(reviewed),
        func.count().filter(rejected),
        func.count().filter(confirmed),
        func.avg(review_secs).filter(has_review),
        func.avg(resolve_secs).filter(has_resolve),
    )
    rows = (
        await db.execute(
            select(Event.module_code, func.max(Event.module_name), *cols)
            .where(in_range)
            .group_by(Event.module_code)
            .order_by(func.count().desc())
        )
    ).all()
    total_row = (await db.execute(select(*cols).where(in_range))).one()

    def block(count, n_reviewed, n_rejected, n_confirmed, review_avg, resolve_avg) -> dict:
        return {
            "events": int(count),
            "reviewed": int(n_reviewed),
            "rejected": int(n_rejected),
            "confirmed": int(n_confirmed),
            "open": int(count) - int(n_reviewed),
            "falsePct": svc.pct(int(n_rejected), int(n_reviewed)),
            "reviewMinutes": _minutes(review_avg),
            "resolveMinutes": _minutes(resolve_avg),
        }

    modules = [{"code": int(code), "name": name or f"#{code}", **block(*rest)} for code, name, *rest in rows]
    return {**block(*total_row), "modules": modules}


# ─────────────────────────────────────────── infratuzilma

async def infrastructure(db: AsyncSession) -> dict:
    cams = await svc.camera_summary(db)
    return {
        "camerasTotal": cams["total"],
        "camerasActive": cams["active"],
        "camerasOnline": cams["online"],
        "videoFlowing": cams["video_flowing"],
        "onlinePct": svc.pct(cams["online"], cams["active"]),
    }


async def build(db: AsyncSession, start: date_type, end: date_type) -> dict:
    return {
        "period": {"from": start.isoformat(), "to": end.isoformat(), "days": (end - start).days + 1},
        "attendance": await attendance(db, start, end),
        "recognition": await recognition(db, start, end),
        "security": await security(db, start, end),
        "infrastructure": await infrastructure(db),
    }


# ─────────────────────────────────────────── qisqa matn (Telegram izohi)

def _p(value: float | None) -> str:
    return "—" if value is None else f"{value:g}%"


def _trend(cur: float | None, prev: float | None) -> str:
    if cur is None or prev is None:
        return ""
    diff = round(cur - prev, 1)
    if diff == 0:
        return " (=)"
    return f" ({'+' if diff > 0 else ''}{diff:g})"


def _mins(value: float | None) -> str:
    if value is None:
        return "—"
    if value < 60:
        return f"{round(value)} daq"
    return f"{value / 60:.1f} soat"


def summary_lines(kpi: dict) -> list[str]:
    """Telegram izohi uchun 4-5 qator: rahbar faylni ochmasdan asosiy
    raqamlarni ko'rsin."""
    att, rec, sec, inf = kpi["attendance"], kpi["recognition"], kpi["security"], kpi["infrastructure"]
    st, sf = att["students"], att["staff"]
    return [
        f"Davomat: xodimlar {_p(sf['rate'])}{_trend(sf['rate'], sf['prevRate'])}, "
        f"talabalar {_p(st['rate'])}{_trend(st['rate'], st['prevRate'])}",
        f"Kechikish: xodimlar {_p(sf['latePct'])}, talabalar {_p(st['latePct'])}",
        f"Yuz bazasi: xodimlar {_p(rec['staffCoverage'])}, talabalar {_p(rec['studentsCoverage'])}; "
        f"notanish kutmoqda: {rec['unknownPending']}",
        f"Hodisalar: {sec['events']}, yolg'on {_p(sec['falsePct'])}, "
        f"javob {_mins(sec['reviewMinutes'])}",
        f"Kameralar: {inf['camerasOnline']}/{inf['camerasActive']} ishlayapti",
    ]
