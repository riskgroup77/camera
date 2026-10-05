"""Kelib-ketish qoidalari: kim kech keldi, necha daqiqa, qaysi kun ish kuni.

Qoida sodda va tushunarli (institut talabi, 2026-09-19):
  * kelish vaqti — kunning BIRINCHI ko'rinishi, istalgan kamerada yoki
    turniketda (faqat kirish eshigida emas);
  * ish boshlanishi + grace_minutes gacha (08:00 + 10 = 08:10) — "keldi",
    undan keyin — "kech_keldi" (kechikish daqiqasi hisoblanadi);
  * dam olish kunlari kechikish hisoblanmaydi;
  * track_last_seen — kunning oxirgi ko'rinishi check_out ga yoziladi
    ("oxirgi ko'rilgan"); "erta ketdi" degan xulosa esa faqat dalil
    yetarli bo'lganda chiqariladi — early_leave_verdict() ga qarang.

Jadval bitta qatorli (app/models/attendance_policy.py). Yuz tanish har
soniyada chaqiriladi, shuning uchun qoida xotirada keshlanadi (30 s)."""

from __future__ import annotations

import time as _clock
from dataclasses import asdict, dataclass, replace
from datetime import date as date_type, datetime, time as time_type, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.attendance_policy import AttendancePolicy, Holiday
from app.timezone import business_date, business_seconds, local_now

CACHE_SECONDS = 30.0


@dataclass(frozen=True)
class Policy:
    staff_start: time_type = time_type(8, 0)
    student_start: time_type = time_type(8, 0)
    grace_minutes: int = 10
    work_end: time_type = time_type(17, 0)
    work_days: tuple[int, ...] = (1, 2, 3, 4, 5, 6)
    track_last_seen: bool = True
    # Bayram / qo'shimcha dam olish sanalari (holidays jadvali).
    holidays: frozenset = frozenset()

    def start_for(self, person_type: str | None) -> time_type:
        return self.student_start if person_type == "talaba" else self.staff_start

    def late_after(self, person_type: str | None) -> time_type:
        start = datetime.combine(date_type(2000, 1, 1), self.start_for(person_type))
        return (start + timedelta(minutes=self.grace_minutes)).time()

    def is_work_day(self, day: date_type | None) -> bool:
        return day is None or (day.isoweekday() in self.work_days and day not in self.holidays)

    def late_minutes(self, arrived: time_type | None, person_type: str | None, day: date_type | None = None) -> int:
        """Ish boshlanishidan necha daqiqa kech (grace ichida bo'lsa 0).

        Soniya hisobga olinmaydi — chegara DAQIQA aniqligida. Kelish vaqti
        soniyasi bilan yoziladi (attendance_ai: .replace(microsecond=0)),
        shuning uchun taqqoslashdan oldin soniya kesiladi: 08:10:30 da
        kelgan odam "08:10 da keldi" deb ko'rsatiladi, lekin kesilmasa
        08:10:00 < 08:10:30 bo'lib "10 daqiqa kech keldi" deb yozilardi —
        ya'ni 08:10 daqiqasida kelgan hamma noto'g'ri kech hisoblanardi."""
        if arrived is None or not self.is_work_day(day):
            return 0
        arrived = arrived.replace(second=0, microsecond=0)
        # Ish kuni 06:00 da boshlanadi: 01:00 dagi kelish — kunning oxiri
        # (juda kech), "erta tong" emas (business_seconds).
        if business_seconds(arrived) <= business_seconds(self.late_after(person_type)):
            return 0
        start = self.start_for(person_type)
        return (business_seconds(arrived) - business_seconds(start)) // 60

    def arrival_status(self, arrived: time_type, person_type: str | None, day: date_type | None = None) -> str:
        return "kech_keldi" if self.late_minutes(arrived, person_type, day) > 0 else "keldi"

    def to_dict(self) -> dict:
        data = asdict(self)
        for key in ("staff_start", "student_start", "work_end"):
            data[key] = data[key].strftime("%H:%M")
        data["work_days"] = list(self.work_days)
        data["holidays"] = sorted(d.isoformat() for d in self.holidays)
        return data


# ─────────────────────────────────────────── erta ketish (TT kriteriya 9)

PRESENT_STATUSES = ("keldi", "kech_keldi")

# Qaror turlari. "aniqlanmadi" — eng muhimi: ma'lumot yetarli emas.
EARLY_YES = "erta_ketdi"
EARLY_NO = "vaqtida"
EARLY_UNKNOWN = "aniqlanmadi"
EARLY_NA = "tegishli_emas"  # kelmagan kun, dam olish, hali tugamagan kun

# Chiqishdan keyingi shu oraliqdagi ko'rinish "keyin ham binoda edi"
# hisoblanmaydi: odam eshikdan chiqayotganda uni yonidagi koridor kamerasi
# ham bir lahza ko'radi.
EXIT_SIGHTING_TOLERANCE = timedelta(minutes=2)

# Kun davomida shundan kam ko'rinish bo'lsa, "oxirgi ko'rinish = ketish
# payti" degan xulosaga asos yo'q: bitta ko'rinish faqat "bir marta
# ko'rindi" deganidir.
MIN_SIGHTINGS_TO_JUDGE = 2


def early_leave_verdict(
    *,
    status: str | None,
    day: date_type | None,
    check_in: time_type | None,
    check_out: time_type | None,
    last_seen: time_type | None = None,
    sightings: int | None = None,
    source: str | None = None,
    policy: "Policy | None" = None,
    now: datetime | None = None,
) -> str:
    """"Erta ketdi" / "vaqtida" / "aniqlanmadi" — BITTA umumiy qoida.

    Ilgari bu savolga uch joyda uch xil javob berilardi (hisobot SQL'i,
    bitta kunlik jadval va odam kartasi), va eng yumshog'i — "check_out ish
    tugashidan oldin" — productionda 64 qatordan 54 tasini (84%) "erta
    ketdi" deb belgilab qo'ygan edi. Sabab: check_out endi ISTALGAN
    kameradagi oxirgi ko'rinish, kamera qoplamasi esa siyrak — odam soat
    10:12 da koridorda ko'ringan bo'lsa, u "10:12 da ketgan" degani emas,
    "10:12 dan keyin hech bir kamera ko'rmagan" degani.

    Shuning uchun qoida ikki tomonlama qattiq:

      * "erta ketdi" deyish uchun DALIL kerak — odam kun davomida yetarlicha
        kuzatilgan (kamida MIN_SIGHTINGS_TO_JUDGE ko'rinish), binoda kamida
        attendance_early_leave_min_presence_minutes bo'lgan, va kunning
        OXIRGI ko'rinishi aynan o'sha chiqish payti;
      * dalil yetmasa javob "aniqlanmadi" — 0 emas, "yo'q" ham emas.
        Direktor o'qiydigan hisobotda o'ylab topilgan muammodan ko'ra
        "o'lchanmadi" halolroq.

    `sightings` — o'sha kuni odam necha marta ko'rilgani (presence_visits),
    `last_seen` — oxirgi ko'rinish payti, `sightings` — necha marta
    ko'rilgani. Ikkovi None bo'lsa — ko'rinish tarixi yuritilmagan va
    javob "aniqlanmadi" bo'ladi.

    `source="qolda"` — istisno: vaqtni kamera emas, ODAM yozgan. Operator
    "14:30 da ketdi" deb yozgan bo'lsa, bu taxmin emas, dalil; kamera
    ko'rinishlari bo'yicha "dalil yetarli emas" deyish uning yozganini
    bekor qilish bo'lardi."""
    rule = policy or current_policy()
    if status not in PRESENT_STATUSES:
        return EARLY_NA
    if not rule.is_work_day(day):
        return EARLY_NA
    moment = now or local_now()
    work_end = business_seconds(rule.work_end)
    if day is not None and day >= business_date(moment) and business_seconds(moment.time()) < work_end:
        # Kun hali tugamagan — odam binoda bo'lishi mumkin.
        return EARLY_NA
    if check_out is None or check_in is None:
        return EARLY_UNKNOWN
    # Yarim tundan keyingi chiqish (01:30) ham shu ish kuniga tegishli —
    # soatlar ish kuni boshidan (06:00) o'lchanadi.
    if business_seconds(check_out) >= work_end:
        return EARLY_NO
    if last_seen is not None and day is not None:
        if business_seconds(last_seen) - business_seconds(check_out) > EXIT_SIGHTING_TOLERANCE.total_seconds():
            # Chiqishdan keyin ham ko'rilgan — ketmagan.
            return EARLY_NO
    # Qo'lda kiritilgan yozuvda kamera ko'rinishlari talab qilinmaydi:
    # vaqtni odam yozgan (docstringga qarang). Qisqa qolish qoidasi esa
    # unga ham tegishli — 12:37-12:42 "erta ketdi" emas.
    if source != "qolda" and (sightings is None or sightings < MIN_SIGHTINGS_TO_JUDGE):
        return EARLY_UNKNOWN
    presence_minutes = (business_seconds(check_out) - business_seconds(check_in)) / 60
    if presence_minutes < settings.attendance_early_leave_min_presence_minutes:
        # Bir marta ko'rinib, qaytib ko'rinmagan odam — bu "erta ketdi"
        # emas, "kamera uni yo'qotdi".
        return EARLY_UNKNOWN
    return EARLY_YES


def parse_days(raw: str) -> tuple[int, ...]:
    return tuple(sorted({int(p) for p in raw.split(",") if p.strip().isdigit() and 1 <= int(p) <= 7}))


def from_row(row: AttendancePolicy) -> Policy:
    return Policy(
        staff_start=row.staff_start,
        student_start=row.student_start,
        grace_minutes=row.grace_minutes,
        work_end=row.work_end,
        work_days=parse_days(row.work_days),
        track_last_seen=row.track_last_seen,
    )


_cached: Policy = Policy()
_loaded_at: float = 0.0


def current_policy() -> Policy:
    """Oxirgi yuklangan qoida (sinxron joylar uchun). Hali yuklanmagan bo'lsa — standart."""
    return _cached


def set_cached(policy: Policy) -> None:
    global _cached, _loaded_at
    _cached, _loaded_at = policy, _clock.monotonic()


async def load_policy(db: AsyncSession, force: bool = False) -> Policy:
    if not force and _loaded_at and _clock.monotonic() - _loaded_at < CACHE_SECONDS:
        return _cached
    row = await db.get(AttendancePolicy, 1)
    policy = from_row(row) if row is not None else Policy()
    # O'tgan va kelasi bir yil — qolgani hisob-kitobga ta'sir qilmaydi.
    today = business_date(local_now())
    days = (
        await db.execute(
            select(Holiday.date).where(Holiday.date.between(today - timedelta(days=400), today + timedelta(days=400)))
        )
    ).scalars().all()
    set_cached(replace(policy, holidays=frozenset(days)))
    return _cached
