"""Situatsion markaz ko'rinishlari uchun hisob-kitob (app/routers/situation.py).

Institut -> fakultet -> kurs -> guruh -> talaba va institut -> kafedra ->
o'qituvchi kesimlari bir xil xom ma'lumotdan yig'iladi:

1. "Birliklar" so'rovi — bitta GROUP BY: (tur, fakultet, group_or_position,
   yuzi tasdiqlanganmi, shu kungi davomat holati) -> son. 10 000 talaba
   bir necha ming qatorga qisqaradi; guruh/kurs esa Python'da
   staff_export.split_course bilan AYNAN bir qoidada ajratiladi (SQL'da
   matnni kesish bu qoidadan ajralib ketardi).
2. Kunning darslari — bitta so'rov, o'qituvchining dars xonasiga birinchi
   kirgan payti korrelyatsiyalangan subquery bilan (N+1 yo'q).

Ikkalasi ham qisqa muddat (SITUATION_CACHE_SECONDS) jarayon ichida
keshlanadi: devor ekrani va bir nechta operator bir sahifani har necha
soniyada yangilaydi, ma'lumot esa shunchalik tez o'zgarmaydi.

Halollik qoidasi (app/jobs/absence_marker.py bilan bir xil): yuzi
tasdiqlanmagan odamni kamera taniy olmaydi, shuning uchun uning yozuvi
bo'lmasa bu "kelmadi" emas, "ma'lumot yo'q". Foiz (rate) faqat holati
ma'lum bo'lganlar ustidan hisoblanadi.
"""

import hashlib
import time as monotonic_time
import uuid
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import date as date_type, datetime, time as time_type, timedelta, timezone
from typing import Any, NamedTuple

from fastapi import HTTPException, status
from sqlalchemy import String, and_, case, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.jobs.camera_health import is_reachable, is_video_flowing
from app.models import (
    AttendanceRecord,
    Building,
    Camera,
    Department,
    Event,
    Faculty,
    LessonAttendance,
    LessonSession,
    OrgUnit,
    PresenceVisit,
    StudentGroup,
    StudentStaff,
)
from app.schemas.situation import CountsOut, LessonOut
from app.services.attendance_policy import current_policy
from app.services.event_scope import OPERATOR_EVENTS
from app.services.event_status import OPEN_STATUSES
from app.services.staff_export import NO_FACULTY_LABEL, split_course
from app.services.unit_names import canonical_map, is_position, unit_key
from app.storage import presigned_url
from app.timezone import INSTITUTE_TZ, local_now, to_local
from app.timezone import business_date, business_today, day_start

SITUATION_CACHE_SECONDS = 15
MAX_RANGE_DAYS = 366
UNASSIGNED_KAFEDRA_ID = "unassigned"
UNASSIGNED_KAFEDRA_NAME = "Lavozim bo'yicha (bo'linmasi ko'rsatilmagan)"
PRESENT_STATUSES = ("keldi", "kech_keldi")
_APOSTROPHES = "‘’`ʻʼ´"


# ─────────────────────────────────────────── qisqa muddatli kesh

class _TtlCache:
    """Oddiy jarayon ichidagi kesh: kalit -> (muddati, qiymat).

    Chegara oshsa butunlay tozalanadi — kalitlar sana va filtrlardan
    iborat, bir necha o'ntadan oshmaydi, LRU murakkabligi keraksiz."""

    def __init__(self, ttl_seconds: float, limit: int = 512) -> None:
        self.ttl = ttl_seconds
        self.limit = limit
        self._data: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any) -> tuple[bool, Any]:
        hit = self._data.get(key)
        if hit is None or hit[0] <= monotonic_time.monotonic():
            return False, None
        return True, hit[1]

    def put(self, key: Any, value: Any) -> None:
        if len(self._data) >= self.limit:
            self._data.clear()
        self._data[key] = (monotonic_time.monotonic() + self.ttl, value)

    def clear(self) -> None:
        self._data.clear()


_cache = _TtlCache(SITUATION_CACHE_SECONDS)
# clear_cache() hammasini tozalaydi (tahlil moduli o'z keshini shu yerga qo'shadi).
_all_caches: list[_TtlCache] = [_cache]


async def cached(key: Any, loader: Callable[[], Awaitable[Any]]) -> Any:
    found, value = _cache.get(key)
    if found:
        return value
    value = await loader()
    _cache.put(key, value)
    return value


def clear_cache() -> None:
    """Testlar va ma'lumot qo'lda o'zgartirilgandan keyin."""
    for item in _all_caches:
        item.clear()


# ─────────────────────────────────────────── sana va vaqt

def today() -> date_type:
    return business_today()


def parse_day(value: str | None, *, name: str = "date") -> date_type | None:
    if not value:
        return None
    try:
        return date_type.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"{name} 'YYYY-MM-DD' formatida bo'lishi kerak"
        ) from exc


def resolve_day(value: str | None) -> date_type:
    return parse_day(value) or today()


def resolve_range(
    date_from: str | None, date_to: str | None, *, default_end: date_type | None = None, default_days: int = 30
) -> tuple[date_type, date_type]:
    end = parse_day(date_to, name="to") or default_end or today()
    start = parse_day(date_from, name="from") or end - timedelta(days=default_days - 1)
    if start > end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "'from' sanasi 'to' dan keyin bo'lmasligi kerak")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Davr {MAX_RANGE_DAYS} kundan oshmasligi kerak")
    return start, end


def day_bounds(day: date_type) -> tuple[datetime, datetime]:
    start = day_start(day)
    return start, start + timedelta(days=1)


def hm(moment: datetime | time_type | None) -> str | None:
    if moment is None:
        return None
    if isinstance(moment, datetime):
        return to_local(moment).strftime("%H:%M")
    return moment.strftime("%H:%M")


def lesson_duration() -> timedelta:
    return timedelta(minutes=settings.lesson_duration_minutes)


def lesson_grace() -> timedelta:
    return timedelta(minutes=settings.attendance_late_to_lesson_grace_minutes)


# ─────────────────────────────────────────── odam ko'rinishi

def initials(full_name: str) -> str:
    letters = [part[0] for part in full_name.split() if part and part[0].isalpha()][:2]
    return "".join(letters).upper() or "?"


def photo_url(key: str | None) -> str | None:
    """Rasm havolasi — ombor ishlamasa ham sahifa ochilaverishi kerak."""
    if not key:
        return None
    try:
        return presigned_url(key)
    except Exception:  # noqa: BLE001 — rasm bo'lmasa bosh harflar ko'rsatiladi
        return None


def norm_name(text: str | None) -> str:
    """Kafedra nomini solishtirish uchun: katta-kichik harf, ortiqcha
    bo'shliq va apostrof turlari farq qilmaydi."""
    value = text or ""
    for ch in _APOSTROPHES:
        value = value.replace(ch, "'")
    return " ".join(value.lower().split())


def student_group(unit: str | None) -> tuple[int | None, str]:
    """(kurs, guruh) — split_course bilan bir xil qoida."""
    return split_course(unit)


#: pending_state(): ish kuni emas (dam olish / bayram) — yozuvsiz odam "dam olish".
OFF_DAY = "off"


def pending_state(day: date_type) -> bool | str:
    """True — kun hali tugamagan ish kuni; OFF_DAY — dam olish/bayram; False — o'tgan ish kuni."""
    if not current_policy().is_work_day(day):
        return OFF_DAY
    return day >= today()


def person_status(record_status: str | None, enrolled: bool, day: date_type) -> str:
    if record_status:
        return record_status
    if not current_policy().is_work_day(day):
        return "dam_olish"
    if enrolled and day >= today():
        return "kutilmoqda"
    return "malumot_yoq"


# ─────────────────────────────────────────── sanoq

@dataclass
class Counts:
    total: int = 0
    enrolled: int = 0
    present: int = 0
    late: int = 0
    absent: int = 0
    day_off: int = 0
    not_yet: int = 0
    no_data: int = 0

    def add(self, enrolled: bool, record_status: str | None, n: int, pending: bool) -> None:
        """pending — kun hali tugamagan (bugun): yuzi tasdiqlangan, lekin
        ko'rinmagan odam "hali kelmagan", o'tgan kunda esa "ma'lumot yo'q"."""
        self.total += n
        if enrolled:
            self.enrolled += n
        if record_status in PRESENT_STATUSES:
            self.present += n
            if record_status == "kech_keldi":
                self.late += n
        elif record_status == "kelmadi":
            self.absent += n
        elif record_status == "dam_olish" or pending == OFF_DAY:
            self.day_off += n
        elif enrolled and pending:
            self.not_yet += n
        else:
            self.no_data += n

    def merge(self, other: "Counts") -> "Counts":
        for name in ("total", "enrolled", "present", "late", "absent", "day_off", "not_yet", "no_data"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        return self

    @property
    def rate(self) -> float | None:
        base = self.present + self.absent + self.not_yet
        return round(self.present * 100 / base, 1) if base else None

    def fields(self) -> dict:
        return {
            "total": self.total, "enrolled": self.enrolled, "present": self.present, "late": self.late,
            "absent": self.absent, "day_off": self.day_off, "not_yet": self.not_yet, "no_data": self.no_data,
            "rate": self.rate,
        }

    def out(self) -> CountsOut:
        return CountsOut(**self.fields())


def pct(part: int, whole: int) -> float | None:
    return round(part * 100 / whole, 1) if whole else None


# Talabalarning shu ulushidan kami yuzini tasdiqlatgan bo'lsa, ularning
# "davomat foizi" bir-ikki odamdan chiqadi va institutni ifodalamaydi.
STUDENTS_DATA_MIN_SHARE = 0.05


def students_data_available(students: Counts) -> bool:
    return students.total > 0 and students.enrolled / students.total >= STUDENTS_DATA_MIN_SHARE


# ─────────────────────────────────────────── birliklar (asosiy agregat)

#: HEMIS tuzilmasiga bog'langan xodimning bo'linma kaliti ("org:<uuid>").
ORG_PREFIX = "org:"


def unit_source():
    """Bo'linma/guruh manbai ustuni: talaba — group_or_position (kurs, guruh);
    xodim — HEMIS bo'linmasi bo'lsa "org:<uuid>", bo'lmasa eski matn."""
    return case(
        (
            and_(StudentStaff.type == "xodim", StudentStaff.org_unit_id.is_not(None)),
            literal(ORG_PREFIX) + cast(StudentStaff.org_unit_id, String),
        ),
        else_=StudentStaff.group_or_position,
    )


class UnitRow(NamedTuple):
    type: str
    faculty_id: uuid.UUID | None
    unit: str
    enrolled: bool
    status: str | None
    n: int


async def unit_rows(db: AsyncSession, day: date_type) -> list[UnitRow]:
    async def load() -> list[UnitRow]:
        enrolled = (StudentStaff.biometrics_status == "tasdiqlangan").label("enrolled")
        stmt = (
            select(
                StudentStaff.type, StudentStaff.faculty_id, unit_source().label("unit"), enrolled,
                AttendanceRecord.status, func.count(),
            )
            .select_from(StudentStaff)
            .outerjoin(
                AttendanceRecord,
                and_(AttendanceRecord.student_staff_id == StudentStaff.id, AttendanceRecord.date == day),
            )
            .where(StudentStaff.active.is_(True))
            .group_by(StudentStaff.type, StudentStaff.faculty_id, "unit", enrolled, AttendanceRecord.status)
        )
        return [UnitRow(*row) for row in (await db.execute(stmt)).all()]

    return await cached(("units", day), load)


def type_counts(rows: Iterable[UnitRow], type_: str, pending: bool) -> Counts:
    counts = Counts()
    for row in rows:
        if row.type == type_:
            counts.add(row.enrolled, row.status, row.n, pending)
    return counts


@dataclass
class GroupAgg:
    name: str
    counts: Counts = field(default_factory=Counts)
    faculty_votes: Counter = field(default_factory=Counter)
    course_votes: Counter = field(default_factory=Counter)

    @property
    def faculty_id(self) -> uuid.UUID | None:
        for faculty_id, _n in self.faculty_votes.most_common():
            if faculty_id is not None:
                return faculty_id
        return None

    @property
    def course(self) -> int | None:
        for course, _n in self.course_votes.most_common():
            if course is not None:
                return course
        return None


def aggregate_groups(rows: Iterable[UnitRow], pending: bool) -> dict[str, GroupAgg]:
    """Talabalar guruh bo'yicha. Kalit — split_course dagi guruh nomi;
    guruhi yozilmagan talaba ("4-kurs") "" kalitiga tushadi."""
    groups: dict[str, GroupAgg] = {}
    for row in rows:
        if row.type != "talaba":
            continue
        course, name = student_group(row.unit)
        agg = groups.setdefault(name, GroupAgg(name))
        agg.counts.add(row.enrolled, row.status, row.n, pending)
        agg.faculty_votes[row.faculty_id] += row.n
        agg.course_votes[course] += row.n
    return groups


async def roster_sizes(db: AsyncSession) -> dict[str, int]:
    """Guruh -> yuzi tasdiqlangan faol talabalar soni (dars "expected")."""

    async def load() -> dict[str, int]:
        rows = await db.execute(
            select(StudentStaff.group_or_position, func.count())
            .where(StudentStaff.type == "talaba")
            .where(StudentStaff.active.is_(True))
            .where(StudentStaff.biometrics_status == "tasdiqlangan")
            .group_by(StudentStaff.group_or_position)
        )
        sizes: dict[str, int] = defaultdict(int)
        for unit, n in rows.all():
            _course, name = student_group(unit)
            sizes[name] += n
        return dict(sizes)

    return await cached(("roster",), load)


async def faculty_names(db: AsyncSession) -> dict[uuid.UUID, str]:
    return dict((await db.execute(select(Faculty.id, Faculty.name))).all())


async def student_group_rows(db: AsyncSession) -> list[tuple[str, uuid.UUID, int]]:
    return [tuple(r) for r in (await db.execute(select(StudentGroup.name, StudentGroup.faculty_id, StudentGroup.course))).all()]


# ─────────────────────────────────────────── bo'linmalar (kafedra, dekanat, bo'lim)

# Ishlab chiqarishda `departments` jadvali bo'sh, xodimning bo'linmasi esa
# faqat group_or_position matnida ("Normal anatomiya", "Rektorat",
# "Farrosh"...). Shuning uchun bo'linmalar shu matnlardan (norm_name bilan)
# yig'iladi va Department yozuvlari bilan nom bo'yicha birlashtiriladi —
# mos kelsa Department.id ishlatiladi, aks holda barqaror "u-<sha1[:10]>".

KIND_ORDER = {"kafedra": 0, "dekanat": 1, "bolim": 2, "lavozim": 3}

# Dekanat: fakultet boshqaruvi ("Davolash ishi fakulteti", "... dekanati").
DEKANAT_KEYWORDS = ("fakultet", "dekanat")
# Ma'muriy-xo'jalik bo'linmalari. norm_name dan keyin (kichik harf, apostrof
# "'") qism-matn sifatida solishtiriladi. Yangi turdagi bo'lim chiqsa SHU
# ro'yxatga qo'shing; hech biriga tushmagan nom kafedra hisoblanadi (fan
# nomlari: "Normal anatomiya", "Fiziologiya").
BOLIM_KEYWORDS = (
    "bo'lim", "bolim", "rektorat", "prorektor", "hisobxona", "xisobxona", "buxgalteriya", "turar joy",
    "yotoqxona", "kutubxona", "markaz", "office", "ofis", "xo'jalik", "xojalik", "devonxona", "arxiv",
    "kadrlar", "sektor", "xizmati", "boshqarma", "muzey", "oshxona", "garaj", "qo'riqlash", "kengash",
    "kotibiyat", "moliya",
)
# Bo'linma emas, LAVOZIM so'zlari: group_or_position FAQAT shu so'zlardan
# (va "bosh", "katta" kabi sifatlardan) iborat bo'lsa, odamning bo'linmasi
# noma'lum — u bitta "Lavozim bo'yicha" soxta bo'linmasiga tushadi.
POSITION_WORDS = frozenset({
    "farrosh", "assistent", "qorovul", "haydovchi", "oshpaz", "o'qituvchi", "oqituvchi", "dotsent",
    "professor", "mudir", "mudiri", "hisobchi", "xisobchi", "buxgalter", "kassir", "elektrik", "santexnik",
    "duradgor", "bog'bon", "bogbon", "kotiba", "kotib", "laborant", "operator", "dispetcher", "hamshira",
    "inspektor", "metodist", "muhandis", "dasturchi", "tozalovchi", "ishchi", "yordamchi", "qo'riqchi",
    "soqchi", "vahtyor", "vaxtyor", "vaxtyorlik", "kutubxonachi", "omborchi", "mexanik", "stajyor",
    "tarbiyachi", "psixolog", "yurist", "maslahatchi", "mutaxassis", "rahbar", "direktor", "rektor",
    "dekan", "o'rinbosari", "texnik", "xodim", "stajyor-tadqiqotchi", "tadqiqotchi", "tarjimon",
})
POSITION_MODIFIERS = frozenset({"bosh", "katta", "kichik", "yetakchi", "oliy", "toifali", "1-toifali",
                                "2-toifali", "v.b.", "v.v.b.", "vaqtincha", "va", "-", "ilmiy"})
LAVOZIM_KIND = "lavozim"


def classify_unit(name: str | None) -> str:
    """Bo'linma turi: kafedra | dekanat | bolim | lavozim.

    Tartib muhim: avval "sof lavozim" (masalan "Katta o'qituvchi"), keyin
    "kafedra" so'zi, keyin dekanat va bo'lim kalit so'zlari; qolgani —
    kafedra."""
    key = norm_name(name)
    tokens = key.replace(",", " ").split()
    if not tokens:
        return LAVOZIM_KIND
    if any(t in POSITION_WORDS for t in tokens) and all(t in POSITION_WORDS or t in POSITION_MODIFIERS for t in tokens):
        return LAVOZIM_KIND
    # Imlo xatoli va kirilcha lavozimlar ("Asisent", "Коровул", "Stajor-o'qituvchi")
    # — app/services/unit_names.py.
    if is_position(name):
        return LAVOZIM_KIND
    if "kafedra" in key:
        return "kafedra"
    if any(word in key for word in DEKANAT_KEYWORDS):
        return "dekanat"
    if any(word in key for word in BOLIM_KEYWORDS):
        return "bolim"
    return "kafedra"


def derived_unit_id(key: str) -> str:
    """Matndan olingan bo'linmaning barqaror id si (norm_name kalitidan)."""
    return "u-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


@dataclass
class DepartmentInfo:
    id: uuid.UUID
    name: str
    building: str | None


@dataclass
class UnitInfo:
    id: str  # str(Department.id), "u-..." yoki UNASSIGNED_KAFEDRA_ID
    name: str
    kind: str
    building: str | None = None
    unassigned: bool = False  # "Lavozim bo'yicha" soxta bo'linmasi


@dataclass
class UnitCatalog:
    units: dict[str, UnitInfo]  # id -> bo'linma, tartiblangan (kafedra birinchi)
    by_key: dict[str, str]  # norm_name(group_or_position) -> id
    staff: list[tuple[uuid.UUID, str | None]]  # faol xodimlar (id, group_or_position)

    # unit_key -> kanonik unit_key (imlo xatoli variantlar birlashtirilgan).
    aliases: dict[str, str] = field(default_factory=dict)

    def unit_id(self, raw: str | None) -> str:
        if raw and raw.startswith(ORG_PREFIX):
            unit = raw[len(ORG_PREFIX):]
            return unit if unit in self.units else UNASSIGNED_KAFEDRA_ID
        key = unit_key(raw)
        return self.by_key.get(self.aliases.get(key, key), UNASSIGNED_KAFEDRA_ID)

    def staff_ids(self, unit_id: str) -> list[uuid.UUID]:
        return [pid for pid, unit in self.staff if self.unit_id(unit) == unit_id]


async def departments(db: AsyncSession) -> list[DepartmentInfo]:
    rows = await db.execute(
        select(Department.id, Department.name, Building.name)
        .outerjoin(Building, Building.id == Department.building_id)
        .order_by(Department.name)
    )
    return [DepartmentInfo(*row) for row in rows.all()]


async def staff_units(db: AsyncSession) -> list[tuple[uuid.UUID, str | None]]:
    """Faol xodimlar (id, bo'linma kaliti — unit_source) — ~900 qator."""
    rows = await db.execute(
        select(StudentStaff.id, unit_source())
        .where(StudentStaff.type == "xodim")
        .where(StudentStaff.active.is_(True))
    )
    return [tuple(r) for r in rows.all()]


#: HEMIS bo'linma turi (org_units.kind) -> sahifadagi guruh.
ORG_KIND_TO_UNIT = {"kafedra": "kafedra", "fakultet": "dekanat"}


@dataclass
class OrgUnitInfo:
    id: uuid.UUID
    name: str
    kind: str


def build_catalog(deps: list[DepartmentInfo], staff: list[tuple[uuid.UUID, str | None]],
                  org_units: list[OrgUnitInfo] | None = None) -> UnitCatalog:
    """HEMIS bo'linmalari + Department yozuvlari + xodimlar matni -> bo'linmalar (sof funksiya).

    Asosiy manba — HEMIS tuzilmasi (org_units): xodim unga org_unit_id
    orqali bog'langan (kalit "org:<uuid>"). Bog'lanmagan xodimlar uchun
    eski yo'l: Department bilan nomi mos matn Department.id ni oladi; qolgan
    har xil matn (norm_name bo'yicha) — alohida bo'linma. HEMIS bo'linmasi
    bilan bir xil nomli Department/matn o'sha HEMIS bo'linmasiga qo'shiladi.
    Sof lavozim matnlari bo'linma bo'lmaydi."""
    units: dict[str, UnitInfo] = {}
    by_key: dict[str, str] = {}
    aliases = canonical_map([raw for _pid, raw in staff if not (raw or "").startswith(ORG_PREFIX)])
    dep_building = {unit_key(dep.name): dep.building for dep in deps}
    linked = Counter(raw[len(ORG_PREFIX):] for _pid, raw in staff if (raw or "").startswith(ORG_PREFIX))
    for org in org_units or []:
        oid = str(org.id)
        kind = ORG_KIND_TO_UNIT.get(org.kind, "bolim")
        # Xodimi yo'q bo'lim/markaz ro'yxatni to'ldirmasin; kafedra va dekanat doim ko'rinadi.
        if not linked.get(oid) and kind == "bolim":
            continue
        key = unit_key(org.name)
        units[oid] = UnitInfo(oid, org.name, kind, dep_building.get(key))
        by_key.setdefault(key, oid)
    for dep in deps:
        key = unit_key(dep.name)
        if key in by_key:  # bir xil nomli ikkinchi Department — birinchisi yutadi
            continue
        kind = classify_unit(dep.name)
        units[str(dep.id)] = UnitInfo(str(dep.id), dep.name, "kafedra" if kind == LAVOZIM_KIND else kind,
                                      dep.building)
        by_key[key] = str(dep.id)

    variants: dict[str, Counter] = defaultdict(Counter)
    for _pid, raw in staff:
        # HEMIS bo'linmasiga bog'langan xodim (kalit "org:<uuid>") — yuqorida
        # hal qilingan; matnli bo'linma sifatida ham qo'shilsa, har haqiqiy
        # bo'linma yonida "org:…" nomli 0 kishilik nusxa paydo bo'lardi.
        if (raw or "").startswith(ORG_PREFIX) or is_position(raw):
            continue
        key = unit_key(raw)
        key = aliases.get(key, key)
        if key and key not in by_key:
            variants[key][" ".join((raw or "").split())] += 1
    for key, names in variants.items():
        name = sorted(names.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        kind = classify_unit(name)
        if kind == LAVOZIM_KIND:
            continue  # unit_id() -> UNASSIGNED_KAFEDRA_ID
        unit_id = derived_unit_id(key)
        units[unit_id] = UnitInfo(unit_id, name, kind)
        by_key[key] = unit_id

    ordered = sorted(units.values(), key=lambda u: (KIND_ORDER[u.kind], norm_name(u.name)))
    catalog = {u.id: u for u in ordered}
    catalog[UNASSIGNED_KAFEDRA_ID] = UnitInfo(UNASSIGNED_KAFEDRA_ID, UNASSIGNED_KAFEDRA_NAME, LAVOZIM_KIND,
                                              unassigned=True)
    return UnitCatalog(catalog, by_key, staff, aliases)


async def org_units_info(db: AsyncSession) -> list[OrgUnitInfo]:
    rows = await db.execute(
        select(OrgUnit.id, OrgUnit.name, OrgUnit.kind).where(OrgUnit.active.is_(True)).order_by(OrgUnit.name)
    )
    return [OrgUnitInfo(*row) for row in rows.all()]


async def unit_catalog(db: AsyncSession) -> UnitCatalog:
    async def load() -> UnitCatalog:
        return build_catalog(await departments(db), await staff_units(db), await org_units_info(db))

    return await cached(("unit_catalog",), load)


async def department_staff_ids(db: AsyncSession, department_id: str) -> tuple[UnitInfo, list[uuid.UUID]]:
    """Bo'linma va uning faol xodimlari. id — Department uuid, "u-..."
    (matndan olingan) yoki "unassigned" (sof lavozim / bo'sh matn)."""
    catalog = await unit_catalog(db)
    info = catalog.units.get(department_id)
    if info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kafedra topilmadi")
    return info, catalog.staff_ids(department_id)


# ─────────────────────────────────────────── darslar

@dataclass
class LessonRow:
    id: uuid.UUID
    date: date_type
    subject: str
    group_name: str
    faculty: str
    teacher: str
    teacher_id: uuid.UUID | None
    camera_id: uuid.UUID | None
    start: datetime | None
    attention_score: int
    attention_samples: int
    activity_score: int
    activity_samples: int
    sleep_incidents: int
    teacher_on_time: bool | None
    room: str | None
    building: str | None
    teacher_photo_key: str | None
    teacher_arrived: datetime | None


def lesson_select():
    """Dars qatorlari + o'qituvchining shu dars xonasiga (dars kamerasi)
    dars vaqti ichida birinchi ko'ringan payti — bitta so'rovda.

    PresenceVisit (student_staff_id, last_seen_at) indeksi bilan
    korrelyatsiyalangan subquery har dars uchun arzon."""
    start = LessonSession.scheduled_start_time
    end = start + lesson_duration()
    arrived = (
        select(func.min(PresenceVisit.first_seen_at))
        .where(PresenceVisit.student_staff_id == LessonSession.teacher_id)
        .where(PresenceVisit.camera_id == LessonSession.camera_id)
        .where(PresenceVisit.first_seen_at < end)
        .where(PresenceVisit.last_seen_at >= start)
        .correlate(LessonSession)
        .scalar_subquery()
    )
    return (
        select(
            LessonSession.id, LessonSession.date, LessonSession.subject, LessonSession.group_name,
            LessonSession.faculty, LessonSession.teacher, LessonSession.teacher_id, LessonSession.camera_id,
            start, LessonSession.attention_score, LessonSession.attention_samples,
            LessonSession.teacher_activity_score, LessonSession.activity_samples, LessonSession.sleep_incidents,
            # Xona va bino: HEMIS jadvalidagi (kamerasi bo'lmasa ham), bo'lmasa kameraniki.
            LessonSession.teacher_on_time,
            func.coalesce(LessonSession.auditorium, Camera.name),
            func.coalesce(LessonSession.building, Building.name),
            StudentStaff.biometric_photo_key,
            arrived,
        )
        .select_from(LessonSession)
        .outerjoin(Camera, Camera.id == LessonSession.camera_id)
        .outerjoin(Building, Building.id == Camera.building_id)
        .outerjoin(StudentStaff, StudentStaff.id == LessonSession.teacher_id)
    )


async def fetch_lessons(db: AsyncSession, *conditions, limit: int | None = None, newest_first: bool = False) -> list[LessonRow]:
    stmt = lesson_select().where(*conditions)
    if newest_first:
        stmt = stmt.order_by(LessonSession.date.desc(), LessonSession.scheduled_start_time.desc().nulls_last(),
                             LessonSession.group_name)
    else:
        stmt = stmt.order_by(LessonSession.date, LessonSession.scheduled_start_time.asc().nulls_last(),
                             LessonSession.group_name)
    if limit:
        stmt = stmt.limit(limit)
    return [LessonRow(*row) for row in (await db.execute(stmt)).all()]


async def day_lessons(db: AsyncSession, day: date_type) -> list[LessonRow]:
    return await cached(("lessons", day), lambda: fetch_lessons(db, LessonSession.date == day))


def lesson_state(start: datetime | None, day: date_type, now: datetime) -> str:
    if start is None:
        # Vaqti kiritilmagan dars: faqat sanasi bo'yicha.
        return "finished" if day < business_date(now) else "upcoming"
    if now < start:
        return "upcoming"
    if now < start + lesson_duration():
        return "ongoing"
    return "finished"


def state_clause(state: str, now: datetime):
    """lesson_state() ning SQL shakli — sahifalash filtrdan keyin to'g'ri sanashi uchun."""
    start = LessonSession.scheduled_start_time
    local_today = business_date(now)
    if state == "upcoming":
        return or_(and_(start.is_not(None), start > now), and_(start.is_(None), LessonSession.date >= local_today))
    if state == "ongoing":
        return and_(start.is_not(None), start <= now, start > now - lesson_duration())
    return or_(
        and_(start.is_not(None), start <= now - lesson_duration()),
        and_(start.is_(None), LessonSession.date < local_today),
    )


def teacher_status(row: LessonRow, now: datetime) -> str:
    """O'qituvchi darsga keldimi.

    Manbalar: teacher_punctuality_ai ning tekshiruvi (teacher_on_time) va
    dars xonasi kamerasidagi tashriflar (teacher_arrived). Tashrif aniqroq
    (kechikib kelganini ham ko'rsatadi), AI tekshiruvi esa "kelmadi" ni
    tasdiqlaydi. Hech narsa bo'lmasa — ayblamaymiz: "nomalum"."""
    if row.teacher_on_time is True:
        return "oz_vaqtida"
    start = row.start
    if row.teacher_arrived is not None:
        if start is None or row.teacher_arrived <= start + lesson_grace():
            return "oz_vaqtida"
        return "kechikdi"
    if start is None:
        return "kelmadi" if row.teacher_on_time is False else "nomalum"
    if now < start:
        return "kutilmoqda"
    if row.teacher_on_time is False:
        return "kelmadi" if now >= start + lesson_duration() else "kechikdi"
    if now < start + lesson_grace():
        return "kutilmoqda"
    return "nomalum"


@dataclass
class LessonCounts:
    finalized: bool = False
    keldi: int = 0
    kech_keldi: int = 0
    kelmadi: int = 0
    seen: int = 0
    seen_late: int = 0


async def lesson_counts(db: AsyncSession, lesson_ids: list[uuid.UUID]) -> dict[uuid.UUID, LessonCounts]:
    if not lesson_ids:
        return {}
    confirmed = LessonAttendance.sightings >= settings.lesson_attendance_min_sightings
    late_cut = LessonSession.scheduled_start_time + lesson_grace()
    rows = await db.execute(
        select(
            LessonAttendance.lesson_session_id,
            func.count().filter(LessonAttendance.status.is_not(None)),
            func.count().filter(LessonAttendance.status == "keldi"),
            func.count().filter(LessonAttendance.status == "kech_keldi"),
            func.count().filter(LessonAttendance.status == "kelmadi"),
            func.count().filter(confirmed),
            func.count().filter(confirmed, LessonAttendance.first_seen_at > late_cut),
        )
        .join(LessonSession, LessonSession.id == LessonAttendance.lesson_session_id)
        .where(LessonAttendance.lesson_session_id.in_(lesson_ids))
        .group_by(LessonAttendance.lesson_session_id)
    )
    return {
        lesson_id: LessonCounts(bool(done), keldi, kech, kelmadi, seen, seen_late)
        for lesson_id, done, keldi, kech, kelmadi, seen, seen_late in rows.all()
    }


def lesson_fields(row: LessonRow, counts: LessonCounts | None, roster: dict[str, int], now: datetime) -> dict:
    counts = counts or LessonCounts()
    if counts.finalized:
        present, late, absent = counts.keldi + counts.kech_keldi, counts.kech_keldi, counts.kelmadi
    else:
        present, late, absent = counts.seen, counts.seen_late, None
    return {
        "id": str(row.id),
        "date": row.date.isoformat(),
        "subject": row.subject,
        "group_name": row.group_name,
        "faculty": row.faculty,
        "teacher": row.teacher,
        "teacher_id": str(row.teacher_id) if row.teacher_id else None,
        "teacher_photo_url": photo_url(row.teacher_photo_key),
        "starts_at": hm(row.start),
        "ends_at": hm(row.start + lesson_duration()) if row.start else None,
        "room": row.room,
        "building": row.building,
        "state": lesson_state(row.start, row.date, now),
        "teacher_status": teacher_status(row, now),
        "teacher_arrived_at": hm(row.teacher_arrived),
        "teacher_on_time": row.teacher_on_time,
        "expected": roster.get(row.group_name, 0),
        "present": present,
        "late": late,
        "absent": absent,
        "seen": counts.seen,
        "finalized": counts.finalized,
        "attention_score": row.attention_score if row.attention_samples else None,
        "activity_score": row.activity_score if row.activity_samples else None,
        "sleep_incidents": row.sleep_incidents,
    }


async def lessons_out(db: AsyncSession, rows: list[LessonRow], now: datetime | None = None) -> list[LessonOut]:
    now = now or datetime.now(timezone.utc)
    counts = await lesson_counts(db, [r.id for r in rows])
    roster = await roster_sizes(db)
    return [LessonOut(**lesson_fields(r, counts.get(r.id), roster, now)) for r in rows]


@dataclass
class Punctuality:
    lessons: int = 0
    on_time: int = 0
    late: int = 0
    missed: int = 0
    unknown: int = 0
    activity_sum: int = 0
    activity_n: int = 0

    def add(self, row: LessonRow, now: datetime) -> str:
        verdict = teacher_status(row, now)
        self.lessons += 1
        if verdict == "oz_vaqtida":
            self.on_time += 1
        elif verdict == "kechikdi":
            self.late += 1
        elif verdict == "kelmadi":
            self.missed += 1
        else:
            self.unknown += 1
        if row.activity_samples:
            self.activity_sum += row.activity_score
            self.activity_n += 1
        return verdict

    @property
    def on_time_rate(self) -> float | None:
        return pct(self.on_time, self.on_time + self.late + self.missed)

    @property
    def avg_activity(self) -> float | None:
        return round(self.activity_sum / self.activity_n, 1) if self.activity_n else None


# ─────────────────────────────────────────── umumiy holat qismlari

async def camera_summary(db: AsyncSession) -> dict:
    total = active = online = flowing = 0
    rows = await db.execute(select(Camera.status, Camera.last_seen_at, Camera.last_frame_at))
    for camera_status, last_seen_at, last_frame_at in rows.all():
        total += 1
        if camera_status != "faol":
            continue
        active += 1
        # app/routers/metrics.py bilan bir xil qoida: tasvir faqat
        # tarmoqda javob berayotgan kamerada hisoblanadi.
        if is_reachable(last_seen_at):
            online += 1
            if is_video_flowing(last_frame_at):
                flowing += 1
    return {"total": total, "active": active, "online": online, "video_flowing": flowing}


async def event_summary(db: AsyncSession, day: date_type) -> dict:
    start, end = day_bounds(day)
    now = datetime.now(timezone.utc)
    # Ikki kichik so'rov: ochiq hodisalar (qisman indeks ix_events_open) va
    # bugungilar (occurred_at indeksi). Ilgari bitta COUNT ... FILTER butun
    # jadvalni (~180 kun) har 15 soniyada aylanib chiqardi.
    open_row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Event.severity == "yuqori"),
                func.count().filter(Event.due_at < now),
            ).where(OPERATOR_EVENTS, Event.status.in_(OPEN_STATUSES))
        )
    ).one()
    today_count = await db.scalar(
        select(func.count()).where(OPERATOR_EVENTS, Event.occurred_at >= start, Event.occurred_at < end)
    )
    return {"open": open_row[0], "today": today_count or 0, "high_open": open_row[1], "overdue": open_row[2]}


EMPTY_HOUR = {"students": 0, "staff": 0, "students_late": 0, "staff_late": 0}


async def arrivals_by_hour(db: AsyncSession, day: date_type) -> list[dict]:
    """Soat bo'yicha kelganlar (kunning birinchi ko'rinishi) va shundan kech
    kelganlar. "Kech" — yozuvning o'z holati (kech_keldi), ya'ni hisobot va
    kartochkalardagi bilan bitta qoida: 08:00-09:00 soatida 08:10 gacha
    kelganlar o'z vaqtida, keyingilari kech."""
    hour = func.extract("hour", AttendanceRecord.check_in)
    rows = await db.execute(
        select(hour, StudentStaff.type, func.count(), func.count().filter(AttendanceRecord.status == "kech_keldi"))
        .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
        .where(AttendanceRecord.date == day)
        .where(AttendanceRecord.check_in.is_not(None))
        .where(StudentStaff.active.is_(True))
        .group_by(hour, StudentStaff.type)
    )
    buckets: dict[int, dict] = {}
    for h, type_, n, late in rows.all():
        bucket = buckets.setdefault(int(h), dict(EMPTY_HOUR))
        key = "students" if type_ == "talaba" else "staff"
        bucket[key] += n
        bucket[f"{key}_late"] += late
    # Ish kuni oralig'i har doim to'liq chiziladi (bo'sh soatlar 0),
    # undan tashqaridagi soatlar faqat ma'lumot bo'lsa qo'shiladi.
    first = min([7, *buckets])
    last = max([19, *buckets])
    return [{"hour": h, **buckets.get(h, EMPTY_HOUR)} for h in range(first, last + 1)]


async def arrivals_without_time(db: AsyncSession, day: date_type) -> dict[str, int]:
    """Kelgan, lekin kelish vaqti yo'q yozuvlar (HEMIS davomati —
    scripts/hemis_davomat.py, qo'lda kiritilgan) — soatlik grafikka
    tushmaydi; grafik ular sonini alohida aytadi, aks holda ustunlar
    yig'indisi "Keldi" bilan mos kelmasdi."""
    rows = await db.execute(
        select(StudentStaff.type, func.count())
        .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
        .where(AttendanceRecord.date == day)
        .where(AttendanceRecord.check_in.is_(None))
        .where(AttendanceRecord.status.in_(("keldi", "kech_keldi")))
        .where(StudentStaff.active.is_(True))
        .group_by(StudentStaff.type)
    )
    counts = {"students": 0, "staff": 0}
    for type_, n in rows.all():
        counts["students" if type_ == "talaba" else "staff"] += n
    return counts


async def last_arrivals(db: AsyncSession, day: date_type, limit: int = 10) -> list[dict]:
    rows = await db.execute(
        select(
            StudentStaff.id, StudentStaff.full_name, StudentStaff.type, StudentStaff.group_or_position,
            StudentStaff.biometric_photo_key, Faculty.name, AttendanceRecord.check_in, AttendanceRecord.status,
        )
        .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
        .outerjoin(Faculty, Faculty.id == StudentStaff.faculty_id)
        .where(AttendanceRecord.date == day)
        .where(AttendanceRecord.check_in.is_not(None))
        .where(StudentStaff.active.is_(True))
        .order_by(AttendanceRecord.check_in.desc(), StudentStaff.full_name)
        .limit(limit)
    )
    out = []
    for pid, name, type_, unit, key, faculty, check_in, record_status in rows.all():
        if type_ == "talaba":
            _course, group = student_group(unit)
            unit = group or unit
        out.append({
            "id": str(pid), "full_name": name, "photo_url": photo_url(key), "initials": initials(name),
            "type": type_, "unit": unit, "faculty": faculty, "time": hm(check_in), "status": record_status,
        })
    return out


def faculty_rows(rows: list[UnitRow], names: dict[uuid.UUID, str], pending: bool) -> list[dict]:
    per: dict[uuid.UUID | None, Counts] = defaultdict(Counts)
    for faculty_id in names:
        per[faculty_id] = Counts()  # talabasi yo'q fakultet ham ro'yxatda ko'rinadi
    for row in rows:
        if row.type == "talaba":
            per[row.faculty_id].add(row.enrolled, row.status, row.n, pending)
    out = []
    for faculty_id, counts in per.items():
        if faculty_id is None and counts.total == 0:
            continue
        out.append({
            "id": str(faculty_id) if faculty_id else None,
            "name": names.get(faculty_id, NO_FACULTY_LABEL) if faculty_id else NO_FACULTY_LABEL,
            **counts.fields(),
        })
    out.sort(key=lambda r: (r["id"] is None, r["name"]))
    return out


def teachers_today(lessons: list[LessonRow], now: datetime) -> dict:
    verdicts: dict[str, list[str]] = defaultdict(list)
    for row in lessons:
        key = str(row.teacher_id) if row.teacher_id else f"name:{norm_name(row.teacher)}"
        verdicts[key].append(teacher_status(row, now))
    out = {"scheduled": len(verdicts), "on_time": 0, "late": 0, "absent": 0, "unknown": 0}
    for items in verdicts.values():
        if "kelmadi" in items:
            out["absent"] += 1
        elif "kechikdi" in items:
            out["late"] += 1
        elif "oz_vaqtida" in items:
            out["on_time"] += 1
        else:
            out["unknown"] += 1
    return out


def lessons_summary(lessons: list[LessonRow], now: datetime) -> dict:
    states = Counter(lesson_state(r.start, r.date, now) for r in lessons)
    scored = [r.attention_score for r in lessons if r.attention_samples]
    return {
        "total": len(lessons),
        "finished": states["finished"],
        "ongoing": states["ongoing"],
        "upcoming": states["upcoming"],
        "avg_attention": round(sum(scored) / len(scored), 1) if scored else None,
    }


# ─────────────────────────────────────────── guruh

def like_suffix(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}"


def member_prefilter(group_name: str):
    """Guruh a'zolarini SQL'da taxminan tanlaydi (indeks bo'yicha arzon),
    aniq tekshiruv esa Python'da is_member() bilan — split_course qoidasi."""
    return StudentStaff.group_or_position.like(like_suffix(group_name), escape="\\")


def is_member(unit: str | None, group_name: str) -> bool:
    return student_group(unit)[1] == group_name


async def group_trend(db: AsyncSession, group_name: str, day: date_type, enrolled_ids: set[uuid.UUID],
                      days: int = 14) -> list[dict]:
    """Oxirgi `days` kunning davomat foizi. Yozuvi umuman yo'q kun (dam
    olish, tizim ishlamagan) — rate None, 0 emas."""
    start = day - timedelta(days=days - 1)
    enrolled = (StudentStaff.biometrics_status == "tasdiqlangan").label("enrolled")
    rows = await db.execute(
        select(AttendanceRecord.date, StudentStaff.group_or_position, enrolled, AttendanceRecord.status, func.count())
        .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
        .where(AttendanceRecord.date.between(start, day))
        .where(StudentStaff.type == "talaba")
        .where(StudentStaff.active.is_(True))
        .where(member_prefilter(group_name))
        .group_by(AttendanceRecord.date, StudentStaff.group_or_position, enrolled, AttendanceRecord.status)
    )
    per_day: dict[date_type, Counts] = defaultdict(Counts)
    enrolled_with_record: Counter = Counter()
    for d, unit, is_enrolled, record_status, n in rows.all():
        if not is_member(unit, group_name):
            continue
        per_day[d].add(is_enrolled, record_status, n, pending=False)
        if is_enrolled:
            enrolled_with_record[d] += n
    current = today()
    out = []
    for i in range(days):
        d = start + timedelta(days=i)
        counts = per_day.get(d)
        if counts is None:
            out.append({"date": d.isoformat(), "rate": None, "present": 0, "late": 0, "absent": 0})
            continue
        if d >= current:
            missing = max(0, len(enrolled_ids) - enrolled_with_record[d])
            counts.add(True, None, missing, pending=True)
        out.append({"date": d.isoformat(), "rate": counts.rate, "present": counts.present,
                    "late": counts.late, "absent": counts.absent})
    return out
