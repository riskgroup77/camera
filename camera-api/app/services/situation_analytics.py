"""Situatsion markaz tahlili: davr KPI lari, issiqlik xaritasi, bo'linma va
shaxs reytingi, surunkali kechikish/kelmaslik, biometrik ro'yxatga olish
tayyorligi va devor ekrani (app/routers/situation_analytics.py).

Hamma hisob AttendanceRecord ustida GROUP BY bilan (kun yoki odam
kesimida) — xom qatorlar Python'ga faqat reyting qilinadigan kichik
to'plam uchun olinadi. Natija 30 soniya keshlanadi.

Foiz qoidasi app/services/situation.py dagi bilan bir xil: rate =
kelgan / (kelgan + kelmagan [+ bugun hali kelmagan]) — "dam_olish" va
yozuvsiz (ma'lumot yo'q) kunlar asosga kirmaydi.
"""

import uuid
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import date as date_type, timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AttendanceRecord, StudentStaff
from app.services import situation as svc

ANALYTICS_CACHE_SECONDS = 30
PRESENT = svc.PRESENT_STATUSES
HEATMAP_HOURS = range(6, 21)  # 06:00 .. 20:59
HEATMAP_WEEKDAYS = range(1, 7)  # ISO: 1 = dushanba .. 6 = shanba
WEEKDAY_LABELS = {1: "Du", 2: "Se", 3: "Cho", 4: "Pa", 5: "Ju", 6: "Sha", 7: "Ya"}
NO_GROUP_LABEL = "Guruh ko'rsatilmagan"

_cache = svc._TtlCache(ANALYTICS_CACHE_SECONDS)
svc._all_caches.append(_cache)


async def cached(key: Any, loader: Callable[[], Awaitable[Any]]) -> Any:
    found, value = _cache.get(key)
    if found:
        return value
    value = await loader()
    _cache.put(key, value)
    return value


def clear_cache() -> None:
    _cache.clear()


# ─────────────────────────────────────────── yordamchi

def minutes_hm(value: float | None) -> str | None:
    if value is None:
        return None
    m = round(value)
    return f"{m // 60:02d}:{m % 60:02d}"


def arrival_minutes():
    """check_in (vaqt) -> kun boshidan daqiqalar (SQL)."""
    return func.extract("hour", AttendanceRecord.check_in) * 60 + func.extract("minute", AttendanceRecord.check_in)


def previous_period(start: date_type, end: date_type) -> tuple[date_type, date_type]:
    """Xuddi shu uzunlikdagi oldingi davr (oxiri — start dan bir kun oldin)."""
    length = (end - start).days + 1
    return start - timedelta(days=length), start - timedelta(days=1)


def population(type_: str):
    return and_(StudentStaff.type == type_, StudentStaff.active.is_(True))


def enrolled_flag():
    return StudentStaff.biometrics_status == "tasdiqlangan"


# ─────────────────────────────────────────── 1. kunlik agregat va KPI

@dataclass
class DayAgg:
    present: int = 0
    late: int = 0
    absent: int = 0
    day_off: int = 0
    not_yet: int = 0  # faqat bugun: tasdiqlangan, hali ko'rinmagan
    arrival_sum: float = 0.0
    arrival_n: int = 0

    @property
    def expected(self) -> int:
        return self.present + self.absent + self.not_yet

    @property
    def covered(self) -> bool:
        """Shu kun tizim ishlagan (kamida bitta yozuv bor)."""
        return bool(self.present + self.absent + self.day_off)

    def merge(self, other: "DayAgg") -> "DayAgg":
        for name in ("present", "late", "absent", "day_off", "not_yet", "arrival_sum", "arrival_n"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        return self


async def daily(db: AsyncSession, type_: str, start: date_type, end: date_type) -> dict[date_type, DayAgg]:
    """Kun -> DayAgg (bitta GROUP BY). Kelajak kunlari kirmaydi."""
    end = min(end, svc.today())
    if start > end:
        return {}
    is_present = AttendanceRecord.status.in_(PRESENT)
    has_time = and_(is_present, AttendanceRecord.check_in.is_not(None))
    rows = await db.execute(
        select(
            AttendanceRecord.date,
            func.count().filter(is_present),
            func.count().filter(AttendanceRecord.status == "kech_keldi"),
            func.count().filter(AttendanceRecord.status == "kelmadi"),
            func.count().filter(AttendanceRecord.status == "dam_olish"),
            func.coalesce(func.sum(arrival_minutes()).filter(has_time), 0),
            func.count().filter(has_time),
        )
        .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
        .where(population(type_))
        .where(AttendanceRecord.date.between(start, end))
        .group_by(AttendanceRecord.date)
    )
    out = {
        d: DayAgg(present=p, late=l, absent=a, day_off=off, arrival_sum=float(s), arrival_n=n)
        for d, p, l, a, off, s, n in rows.all()
    }
    today = svc.today()
    # Dam olish kuni / bayram — hech kim "kutilmoqda" emas (situation.pending_state):
    # aks holda yakshanba KPI maxrajiga ~700 xodim qo'shilib, foiz 0% bo'lardi.
    if start <= today <= end and svc.pending_state(today) is True:
        # Bugun: yuzi tasdiqlangan, lekin hali yozuvi yo'qlar "kutilmoqda".
        no_record = ~(
            select(AttendanceRecord.id)
            .where(AttendanceRecord.student_staff_id == StudentStaff.id)
            .where(AttendanceRecord.date == today)
            .exists()
        )
        waiting = (
            await db.execute(select(func.count()).select_from(StudentStaff).where(population(type_))
                             .where(enrolled_flag()).where(no_record))
        ).scalar_one()
        out.setdefault(today, DayAgg()).not_yet = waiting
    return out


def period_kpis(days: Iterable[DayAgg]) -> dict:
    total = DayAgg()
    covered = 0
    for d in days:
        total.merge(d)
        covered += d.covered
    return {
        "rate": svc.pct(total.present, total.expected),
        "avg_arrival": minutes_hm(total.arrival_sum / total.arrival_n) if total.arrival_n else None,
        "avg_arrival_minutes": round(total.arrival_sum / total.arrival_n) if total.arrival_n else None,
        "present": total.present,
        "late": total.late,
        "absent": total.absent,
        "punctual_pct": svc.pct(total.present - total.late, total.present),
        "days_covered": covered,
    }


def _diff(a, b, digits: int | None = 1):
    if a is None or b is None:
        return None
    return round(a - b, digits) if digits is not None else a - b


def compare(current: dict, previous: dict) -> dict:
    """Joriy davr − oldingi davr. avgArrivalMinutes musbat — kechroq kelishgan."""
    return {
        "rate": _diff(current["rate"], previous["rate"]),
        "avg_arrival_minutes": _diff(current["avg_arrival_minutes"], previous["avg_arrival_minutes"], None),
        "late": current["late"] - previous["late"],
        "absent": current["absent"] - previous["absent"],
        "punctual_pct": _diff(current["punctual_pct"], previous["punctual_pct"]),
    }


def daily_points(days: dict[date_type, DayAgg], start: date_type, end: date_type) -> list[dict]:
    out = []
    d = start
    last = min(end, svc.today())
    while d <= last:
        agg = days.get(d, DayAgg())
        out.append({
            "date": d.isoformat(), "present": agg.present, "late": agg.late, "absent": agg.absent,
            "expected": agg.expected, "rate": svc.pct(agg.present, agg.expected),
            "avg_arrival": minutes_hm(agg.arrival_sum / agg.arrival_n) if agg.arrival_n else None,
        })
        d += timedelta(days=1)
    return out


async def summary(db: AsyncSession, type_: str, start: date_type, end: date_type) -> dict:
    prev_start, prev_end = previous_period(start, end)
    current = await daily(db, type_, start, end)
    previous = await daily(db, type_, prev_start, prev_end)
    cur, prev = period_kpis(current.values()), period_kpis(previous.values())
    return {
        "type": type_, "date_from": start.isoformat(), "date_to": end.isoformat(),
        "previous_from": prev_start.isoformat(), "previous_to": prev_end.isoformat(),
        "current": cur, "previous": prev, "delta": compare(cur, prev),
        "daily": daily_points(current, start, end),
    }


# ─────────────────────────────────────────── 2. issiqlik xaritasi

def heatmap_buckets(arrivals: Iterable[tuple[int, int, int]], lateness: Iterable[tuple[int, int, int]]) -> dict:
    """arrivals: (isodow, soat, son); lateness: (isodow, kelgan, kech kelgan).
    Yakshanba va 6..20 dan tashqaridagi soatlar `outside` ga tushadi."""
    grid = {(wd, h): 0 for wd in HEATMAP_WEEKDAYS for h in HEATMAP_HOURS}
    outside = 0
    for wd, hour, n in arrivals:
        key = (int(wd), int(hour))
        if key in grid:
            grid[key] += n
        else:
            outside += n
    late_by = {int(wd): (present, late) for wd, present, late in lateness}
    weekdays = []
    for wd in HEATMAP_WEEKDAYS:
        present, late = late_by.get(wd, (0, 0))
        weekdays.append({
            "weekday": wd, "label": WEEKDAY_LABELS[wd], "counts": [grid[(wd, h)] for h in HEATMAP_HOURS],
            "total": sum(grid[(wd, h)] for h in HEATMAP_HOURS), "present": present, "late": late,
            "late_rate": svc.pct(late, present),
        })
    return {"hours": list(HEATMAP_HOURS), "weekdays": weekdays, "max": max(grid.values(), default=0),
            "outside": outside}


async def heatmap(db: AsyncSession, type_: str, start: date_type, end: date_type) -> dict:
    wd = func.extract("isodow", AttendanceRecord.date)
    hour = func.extract("hour", AttendanceRecord.check_in)
    base = (
        select()
        .select_from(AttendanceRecord)
        .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
        .where(population(type_))
        .where(AttendanceRecord.date.between(start, end))
        .where(AttendanceRecord.status.in_(PRESENT))
    )
    arrivals = await db.execute(
        base.add_columns(wd, hour, func.count()).where(AttendanceRecord.check_in.is_not(None)).group_by(wd, hour)
    )
    lateness = await db.execute(
        base.add_columns(wd, func.count(), func.count().filter(AttendanceRecord.status == "kech_keldi")).group_by(wd)
    )
    out = heatmap_buckets(arrivals.all(), lateness.all())
    return {"type": type_, "date_from": start.isoformat(), "date_to": end.isoformat(), **out}


# ─────────────────────────────────────────── 3. odam kesimida agregat

@dataclass
class PersonAgg:
    present: int = 0
    late: int = 0
    absent: int = 0
    arrival_sum: float = 0.0
    arrival_n: int = 0

    @property
    def rate(self) -> float | None:
        return svc.pct(self.present, self.present + self.absent)

    @property
    def avg_minutes(self) -> float | None:
        return self.arrival_sum / self.arrival_n if self.arrival_n else None

    def merge(self, other: "PersonAgg") -> "PersonAgg":
        for name in ("present", "late", "absent", "arrival_sum", "arrival_n"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        return self


async def person_aggs(db: AsyncSession, type_: str, start: date_type, end: date_type,
                      ids: list[uuid.UUID] | None = None) -> dict[uuid.UUID, PersonAgg]:
    is_present = AttendanceRecord.status.in_(PRESENT)
    has_time = and_(is_present, AttendanceRecord.check_in.is_not(None))
    stmt = (
        select(
            AttendanceRecord.student_staff_id,
            func.count().filter(is_present),
            func.count().filter(AttendanceRecord.status == "kech_keldi"),
            func.count().filter(AttendanceRecord.status == "kelmadi"),
            func.coalesce(func.sum(arrival_minutes()).filter(has_time), 0),
            func.count().filter(has_time),
        )
        .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
        .where(population(type_))
        .where(AttendanceRecord.date.between(start, min(end, svc.today())))
        .group_by(AttendanceRecord.student_staff_id)
    )
    if ids is not None:
        stmt = stmt.where(AttendanceRecord.student_staff_id.in_(ids))
    return {pid: PersonAgg(p, l, a, float(s), n) for pid, p, l, a, s, n in (await db.execute(stmt)).all()}


@dataclass
class UnitRef:
    id: str
    name: str
    kind: str


async def unit_resolver(db: AsyncSession, type_: str) -> Callable[[str | None], UnitRef]:
    """group_or_position -> bo'linma (xodim) yoki guruh (talaba)."""
    if type_ == "xodim":
        catalog = await svc.unit_catalog(db)

        def staff_unit(raw: str | None) -> UnitRef:
            info = catalog.units[catalog.unit_id(raw)]
            return UnitRef(info.id, info.name, info.kind)

        return staff_unit

    def student_unit(raw: str | None) -> UnitRef:
        _course, group = svc.student_group(raw)
        return UnitRef(group, group or NO_GROUP_LABEL, "guruh")

    return student_unit


async def people_info(db: AsyncSession, type_: str, ids: Iterable[uuid.UUID] | None = None) -> list[tuple]:
    """(id, F.I.Sh., group_or_position, rasm kaliti, tasdiqlanganmi)."""
    stmt = select(StudentStaff.id, StudentStaff.full_name, svc.unit_source(),
                  StudentStaff.biometric_photo_key, enrolled_flag()).where(population(type_))
    if ids is not None:
        stmt = stmt.where(StudentStaff.id.in_(list(ids)))
    return [tuple(r) for r in (await db.execute(stmt)).all()]


# ─────────────────────────────────────────── 4. bo'linmalar reytingi

UNIT_SORTS = {
    "rate": lambda r: r["rate"],
    "late": lambda r: r["late_days"],
    "absent": lambda r: r["absent_days"],
    "arrival": lambda r: r["avg_arrival_minutes"],
    "punctual": lambda r: r["punctual_pct"],
    "trend": lambda r: r["trend"],
    "headcount": lambda r: r["headcount"],
    "name": lambda r: svc.norm_name(r["name"]),
}


def sort_rows(rows: list[dict], key: Callable[[dict], Any], descending: bool) -> list[dict]:
    """None qiymatlar tartibdan qat'i nazar oxirida."""
    known = [r for r in rows if key(r) is not None]
    unknown = [r for r in rows if key(r) is None]
    known.sort(key=key, reverse=descending)
    return known + unknown


async def units(db: AsyncSession, type_: str, start: date_type, end: date_type, kind: str) -> list[dict]:
    resolve = await unit_resolver(db, type_)
    prev_start, prev_end = previous_period(start, end)
    current = await person_aggs(db, type_, start, end)
    previous = await person_aggs(db, type_, prev_start, prev_end)

    refs: dict[str, UnitRef] = {}
    head: Counter = Counter()
    enrolled: Counter = Counter()
    cur: dict[str, PersonAgg] = defaultdict(PersonAgg)
    prev: dict[str, PersonAgg] = defaultdict(PersonAgg)
    if type_ == "xodim":
        # Ro'yxatda xodimi bo'lmagan Department ham ko'rinsin.
        for info in (await svc.unit_catalog(db)).units.values():
            if not info.unassigned:
                refs[info.id] = UnitRef(info.id, info.name, info.kind)
    for pid, _name, raw, _key, is_enrolled in await people_info(db, type_):
        ref = resolve(raw)
        refs.setdefault(ref.id, ref)
        head[ref.id] += 1
        enrolled[ref.id] += bool(is_enrolled)
        if pid in current:
            cur[ref.id].merge(current[pid])
        if pid in previous:
            prev[ref.id].merge(previous[pid])

    out = []
    for ref in refs.values():
        if kind != "all" and ref.kind != kind:
            continue
        c, p = cur.get(ref.id, PersonAgg()), prev.get(ref.id, PersonAgg())
        out.append({
            "id": ref.id, "name": ref.name, "kind": ref.kind, "headcount": head[ref.id], "enrolled": enrolled[ref.id],
            "present_days": c.present, "late_days": c.late, "absent_days": c.absent, "rate": c.rate,
            "avg_arrival": minutes_hm(c.avg_minutes),
            "avg_arrival_minutes": round(c.avg_minutes) if c.avg_minutes is not None else None,
            "punctual_pct": svc.pct(c.present - c.late, c.present), "previous_rate": p.rate,
            "trend": _diff(c.rate, p.rate),
        })
    return out


# ─────────────────────────────────────────── 5. shaxslar reytingi va seriya

def current_streak(statuses_newest_first: Iterable[str]) -> tuple[int, str | None]:
    """Eng oxirgi kunlardan boshlab uzluksiz "kelmadi"/"kech_keldi" kunlar.

    dam_olish seriyani uzmaydi (o'tkazib yuboriladi), "keldi" uzadi.
    Tur: hammasi kelmadi -> "kelmadi", hammasi kech -> "kech_keldi",
    aralash -> "aralash"; seriya yo'q -> (0, None)."""
    n = 0
    kinds = set()
    for record_status in statuses_newest_first:
        if record_status == "dam_olish":
            continue
        if record_status not in ("kelmadi", "kech_keldi"):
            break
        n += 1
        kinds.add(record_status)
    if not n:
        return 0, None
    return n, kinds.pop() if len(kinds) == 1 else "aralash"


async def streaks(db: AsyncSession, ids: list[uuid.UUID], end: date_type, lookback_days: int = 90
                  ) -> dict[uuid.UUID, tuple[int, str | None]]:
    if not ids:
        return {}
    rows = await db.execute(
        select(AttendanceRecord.student_staff_id, AttendanceRecord.status)
        .where(AttendanceRecord.student_staff_id.in_(ids))
        .where(AttendanceRecord.date.between(end - timedelta(days=lookback_days), end))
        .order_by(AttendanceRecord.student_staff_id, AttendanceRecord.date.desc())
    )
    per: dict[uuid.UUID, list[str]] = defaultdict(list)
    for pid, record_status in rows.all():
        per[pid].append(record_status)
    return {pid: current_streak(items) for pid, items in per.items()}


async def last_seen(db: AsyncSession, ids: list[uuid.UUID], end: date_type) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await db.execute(
        select(AttendanceRecord.student_staff_id, func.max(AttendanceRecord.date))
        .where(AttendanceRecord.student_staff_id.in_(ids))
        .where(AttendanceRecord.status.in_(PRESENT))
        .where(AttendanceRecord.date <= end)
        .group_by(AttendanceRecord.student_staff_id)
    )
    return {pid: d.isoformat() for pid, d in rows.all()}


async def unit_member_ids(db: AsyncSession, type_: str, unit_id: str) -> list[uuid.UUID]:
    if type_ == "xodim":
        _info, ids = await svc.department_staff_ids(db, unit_id)
        return ids
    rows = await db.execute(
        select(StudentStaff.id, StudentStaff.group_or_position).where(population("talaba"))
        .where(svc.member_prefilter(unit_id))
    )
    return [pid for pid, raw in rows.all() if svc.is_member(raw, unit_id)]


PEOPLE_SORTS = {
    # (kalit, kamayish bo'yichami) — "eng muammoli" birinchi
    "late": (lambda r: (r["late_days"], r["absent_days"]), True),
    "absent": (lambda r: (r["absent_days"], r["late_days"]), True),
    "arrival": (lambda r: r["avg_arrival_minutes"], True),
    "rate": (lambda r: r["rate"], False),
}


async def people(db: AsyncSession, type_: str, start: date_type, end: date_type, sort: str,
                 unit_id: str | None, limit: int, order: str | None = None) -> list[dict]:
    """`order` — tartib yo'nalishi (asc | desc). Berilmasa har bir `sort`
    uchun tabiiy yo'nalish (PEOPLE_SORTS) ishlatiladi.

    Bu MUHIM: ro'yxat avval tartiblanadi, keyin `limit` bilan kesiladi.
    "Eng erta keladiganlar"ni olish uchun mijoz javobni teskari qilsa,
    kerakli odamlar allaqachon kesib tashlangan bo'ladi — shuning uchun
    yo'nalish serverga beriladi."""
    ids = await unit_member_ids(db, type_, unit_id) if unit_id else None
    if ids == []:
        return []
    aggs = {pid: a for pid, a in (await person_aggs(db, type_, start, end, ids)).items() if a.present + a.absent}
    if not aggs:
        return []
    resolve = await unit_resolver(db, type_)
    info = {row[0]: row for row in await people_info(db, type_, aggs)}
    rows = []
    for pid, agg in aggs.items():
        if pid not in info:
            continue
        _pid, name, raw, key, _enrolled = info[pid]
        ref = resolve(raw)
        rows.append({
            "id": str(pid), "full_name": name, "photo_key": key, "initials": svc.initials(name),
            "unit_id": ref.id, "unit": ref.name, "present_days": agg.present, "late_days": agg.late,
            "absent_days": agg.absent, "rate": agg.rate, "avg_arrival": minutes_hm(agg.avg_minutes),
            "avg_arrival_minutes": round(agg.avg_minutes) if agg.avg_minutes is not None else None,
        })
    key_fn, descending = PEOPLE_SORTS[sort]
    if order is not None:
        descending = order == "desc"
    rows = sort_rows(sorted(rows, key=lambda r: r["full_name"]), key_fn, descending)[:limit]

    picked = [uuid.UUID(r["id"]) for r in rows]
    seen = await last_seen(db, picked, end)
    runs = await streaks(db, picked, min(end, svc.today()))
    for r in rows:
        pid = uuid.UUID(r["id"])
        r["photo_url"] = svc.photo_url(r.pop("photo_key"))
        r["last_seen"] = seen.get(pid)
        r["streak"], r["streak_kind"] = runs.get(pid, (0, None))
    return rows


# ─────────────────────────────────────────── 6. surunkali ro'yxat

async def chronic(db: AsyncSession, type_: str, start: date_type, end: date_type, min_absent: int, min_late: int,
                  limit: int = 500) -> list[dict]:
    absent_n = func.count().filter(AttendanceRecord.status == "kelmadi")
    late_n = func.count().filter(AttendanceRecord.status == "kech_keldi")
    rows = (
        await db.execute(
            select(
                AttendanceRecord.student_staff_id, absent_n, late_n,
                func.array_agg(AttendanceRecord.date).filter(AttendanceRecord.status == "kelmadi"),
                func.array_agg(AttendanceRecord.date).filter(AttendanceRecord.status == "kech_keldi"),
            )
            .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
            .where(population(type_))
            .where(AttendanceRecord.date.between(start, min(end, svc.today())))
            .group_by(AttendanceRecord.student_staff_id)
            .having((absent_n >= min_absent) | (late_n >= min_late))
            .order_by((absent_n + late_n).desc())
            .limit(limit)
        )
    ).all()
    if not rows:
        return []
    resolve = await unit_resolver(db, type_)
    info = {r[0]: r for r in await people_info(db, type_, [r[0] for r in rows])}
    out = []
    for pid, absent, late, absent_dates, late_dates in rows:
        _pid, name, raw, key, _enrolled = info[pid]
        ref = resolve(raw)
        out.append({
            "id": str(pid), "full_name": name, "photo_url": svc.photo_url(key), "initials": svc.initials(name),
            "unit_id": ref.id, "unit": ref.name, "absent_days": absent, "late_days": late,
            "absent_dates": sorted(d.isoformat() for d in (absent_dates or [])),
            "late_dates": sorted(d.isoformat() for d in (late_dates or [])),
            "reasons": [r for r, hit in (("kelmadi", absent >= min_absent), ("kech_keldi", late >= min_late)) if hit],
        })
    out.sort(key=lambda r: (-(r["absent_days"] + r["late_days"]), r["full_name"]))
    return out


# ─────────────────────────────────────────── 7. biometrik ro'yxatga olish

@dataclass
class Enroll:
    total: int = 0
    confirmed: int = 0
    pending: int = 0
    none: int = 0

    def add(self, bio: str, n: int) -> None:
        self.total += n
        if bio == "tasdiqlangan":
            self.confirmed += n
        elif bio == "kutilmoqda":
            self.pending += n
        else:
            self.none += n

    def fields(self) -> dict:
        return {"total": self.total, "confirmed": self.confirmed, "pending": self.pending, "none": self.none,
                "pct": svc.pct(self.confirmed, self.total)}


async def enrollment(db: AsyncSession) -> dict:
    rows = await db.execute(
        select(StudentStaff.type, StudentStaff.faculty_id, StudentStaff.biometrics_status, func.count())
        .where(StudentStaff.active.is_(True))
        .group_by(StudentStaff.type, StudentStaff.faculty_id, StudentStaff.biometrics_status)
    )
    students, staff = Enroll(), Enroll()
    names = await svc.faculty_names(db)
    per: dict[uuid.UUID | None, Enroll] = {fid: Enroll() for fid in names}
    for type_, faculty_id, bio, n in rows.all():
        if type_ == "talaba":
            students.add(bio, n)
            per.setdefault(faculty_id, Enroll()).add(bio, n)
        else:
            staff.add(bio, n)
    by_faculty = [
        {"id": str(fid) if fid else None, "name": names.get(fid, svc.NO_FACULTY_LABEL) if fid else svc.NO_FACULTY_LABEL,
         **e.fields()}
        for fid, e in per.items() if fid is not None or e.total
    ]
    by_faculty.sort(key=lambda r: (r["id"] is None, r["name"]))
    return {"students": students.fields(), "staff": staff.fields(), "by_faculty": by_faculty,
            "students_data_available": bool(students.total)
            and students.confirmed / students.total >= svc.STUDENTS_DATA_MIN_SHARE}


async def enrollment_groups(db: AsyncSession, faculty_id: uuid.UUID | None, course: int | None) -> list[dict]:
    rows = await db.execute(
        select(StudentStaff.group_or_position, StudentStaff.faculty_id, StudentStaff.biometrics_status, func.count())
        .where(population("talaba"))
        .group_by(StudentStaff.group_or_position, StudentStaff.faculty_id, StudentStaff.biometrics_status)
    )
    groups: dict[str, dict] = {}

    def slot(name: str) -> dict:
        return groups.setdefault(name, {"enroll": Enroll(), "faculty": Counter(), "course": Counter()})

    for raw, fid, bio, n in rows.all():
        course_no, name = svc.student_group(raw)
        if not name:
            continue
        g = slot(name)
        g["enroll"].add(bio, n)
        g["faculty"][fid] += n
        g["course"][course_no] += n
    for name, fid, course_no in await svc.student_group_rows(db):
        g = slot(name)
        g["faculty"][fid] += 0
        g["course"][course_no] += 0

    names = await svc.faculty_names(db)
    out = []
    for name, g in groups.items():
        fid = next((f for f, _n in g["faculty"].most_common() if f), None)
        course_no = next((c for c, _n in g["course"].most_common() if c is not None), None)
        if faculty_id and fid != faculty_id:
            continue
        if course and course_no != course:
            continue
        e = g["enroll"]
        out.append({"name": name, "faculty_id": str(fid) if fid else None, "faculty": names.get(fid) if fid else None,
                    "course": course_no, "total": e.total, "confirmed": e.confirmed, "pending": e.pending,
                    "pct": e.fields()["pct"]})
    # Eng orqada qolgan guruhlar birinchi; talabasi yo'q guruhlar (pct null) oxirida.
    return sort_rows(sorted(out, key=lambda r: r["name"]), lambda r: r["pct"], False)


async def enrollment_missing(db: AsyncSession, group_name: str) -> tuple[list[dict], int]:
    rows = await db.execute(
        select(StudentStaff.id, StudentStaff.full_name, StudentStaff.group_or_position, StudentStaff.biometrics_status)
        .where(population("talaba"))
        .where(svc.member_prefilter(group_name))
        .order_by(StudentStaff.full_name)
    )
    members = [r for r in rows.all() if svc.is_member(r[2], group_name)]
    return [
        {"id": str(pid), "full_name": name, "initials": svc.initials(name), "biometrics_status": bio}
        for pid, name, _raw, bio in members if bio != "tasdiqlangan"
    ], len(members)


# ─────────────────────────────────────────── 8. devor ekrani

@dataclass
class UnitToday:
    ref: UnitRef
    counts: svc.Counts = field(default_factory=svc.Counts)


async def staff_units_today(db: AsyncSession, day: date_type) -> list[UnitToday]:
    catalog = await svc.unit_catalog(db)
    pending = svc.pending_state(day)
    per: dict[str, UnitToday] = {}
    for row in await svc.unit_rows(db, day):
        if row.type != "xodim":
            continue
        info = catalog.units[catalog.unit_id(row.unit)]
        per.setdefault(info.id, UnitToday(UnitRef(info.id, info.name, info.kind))).counts.add(
            row.enrolled, row.status, row.n, pending
        )
    return list(per.values())
