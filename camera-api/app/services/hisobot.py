"""Hisobotlar (`/api/hisobot`): xodimlar va talabalar — alohida.

Bitta so'rov bitta hisobotni to'liq qaytaradi: yon paneldagi mezonlar
(har biri qisqa ko'rsatkich bilan), tanlangan mezon bo'yicha plitkalar,
kunlik trend, bo'linma/guruh kesimi va "eng muammoli birinchi" odamlar.

Aholi (population) har doim bir tur: `talaba` yoki `xodim` — sonlar,
filtrlar va mezonlar hech qachon aralashmaydi.

Filtrlar:
  talaba — fakultet -> kurs -> guruh (kurs va guruh group_or_position
           matnidan: "2-kurs, DI-2301"); yo'nalish ma'lumoti bazada yo'q.
  xodim  — bo'linma turi (kafedra / dekanat / bo'lim / lavozim) -> bo'linma
           (app/services/situation.build_catalog bilan bir xil).

HALOLLIK: faqat tizim haqiqatan o'lchaydigan mezonlar. Odamga bog'lanmagan
signal (masalan oq xalat — hodisada odam ismi yozilmaydi) odamlar
jadvalisiz, faqat umumiy son va bino kesimi bilan ko'rsatiladi.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import date as date_type, datetime, time as time_type, timedelta
from typing import Any, Callable, Iterable

from sqlalchemy import and_, false, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.batch import holatlar
from app.config import settings
from app.models import (AIModuleConfig, AttendanceRecord, DailyPersonCriteria, LessonAttendance, LessonSession,
                        PresenceVisit, StudentStaff)
from app.services import situation as svc
from app.services.attendance_policy import (EARLY_NA, EARLY_UNKNOWN, EARLY_YES, Policy, early_leave_verdict,
                                            load_policy)
from app.services.staff_export import split_course
from app.timezone import local_date, INSTITUTE_TZ, INSTITUTE_TZ_NAME
from app.timezone import day_start

KINDS = ("talaba", "xodim")
PRESENT = ("keldi", "kech_keldi")
PEOPLE_LIMIT = 300
NO_FACULTY = "none"
NO_FACULTY_LABEL = "Fakultetsiz"
NO_GROUP_LABEL = "Guruh ko'rsatilmagan"
UNIT_KIND_LABELS = {"kafedra": "Kafedralar", "dekanat": "Dekanatlar", "bolim": "Bo'limlar", "lavozim": "Lavozim bo'yicha"}

STAFF_ATTENDANCE_CODE = 6
STUDENT_ATTENDANCE_CODE = 7
COAT_CODE = 10
SMOKING_CODE = 15
ATTENTION_CODE = 19
EARLY_LEAVE_CODE = 9
PUNCTUALITY_CODE = 22

ACTIVITY_CODE = 21
LESSON_LATE_CODE = 8

# Kunlik video tahlil natijalaridan (daily_person_criteria, lesson_attendance,
# lesson_sessions) har odamga bog'langan "holatlar soni" mezonlari —
# 2026-10-04 dan. Ilgari "uxlash" (#20) va "tashqari_kirish" (#3) shu yerda
# edi; ular buyurtmachi ro'yxatidan olib tashlangan.
COUNT_KEYS = ("darsga_kech", "darsdan_erta", "forma", "chekish", "diqqat", "faollik")
COUNT_WHAT = {
    "darsga_kech": "darsga kech kirish",
    "darsdan_erta": "darsdan erta chiqish",
    "forma": "oq xalatsiz kun",
    "chekish": "chekish holati",
    "diqqat": "diqqati past dars",
    "faollik": "faolligi past dars",
}
COUNT_COLUMN = {
    "darsga_kech": "Kech kirgan darslar",
    "darsdan_erta": "Erta chiqqan darslar",
    "forma": "Oq xalatsiz kunlar",
    "chekish": "Chekish holatlari",
    "diqqat": "Diqqati past darslar",
    "faollik": "Faolligi past darslar",
}


def low_attention() -> int:
    """Diqqat balli shundan past dars "diqqati past" — kunlik tahlil holati
    (app/batch/aggregate.py) bilan bitta sozlama."""
    return settings.video_attention_low_score


def low_activity() -> int:
    return settings.video_teacher_activity_low_score


# ─────────────────────────────────────────── aholi va filtrlar

@dataclass(frozen=True)
class Member:
    id: uuid.UUID
    name: str
    raw: str | None  # group_or_position
    faculty_id: uuid.UUID | None
    photo_key: str | None
    enrolled: bool


@dataclass
class Filters:
    faculty: str | None = None  # uuid yoki "none"
    course: int | None = None
    group: str | None = None
    unit_kind: str | None = None
    unit: str | None = None
    q: str | None = None

    def sql_faculty(self):
        if not self.faculty:
            return None
        if self.faculty == NO_FACULTY:
            return StudentStaff.faculty_id.is_(None)
        try:
            return StudentStaff.faculty_id == uuid.UUID(self.faculty)
        except ValueError:
            return StudentStaff.id.is_(None)  # noto'g'ri id — bo'sh natija


async def population(db: AsyncSession, kind: str) -> list[Member]:
    """Faol aholi (talabalar ~10k, xodimlar ~800) — 15 soniya keshlanadi."""

    async def load() -> list[Member]:
        rows = await db.execute(
            select(StudentStaff.id, StudentStaff.full_name, svc.unit_source(), StudentStaff.faculty_id,
                   StudentStaff.biometric_photo_key, StudentStaff.biometrics_status == "tasdiqlangan")
            .where(StudentStaff.type == kind)
            .where(StudentStaff.active.is_(True))
        )
        return [Member(*row) for row in rows.all()]

    return await svc.cached(("hisobot_population", kind), load)


def student_course_group(raw: str | None) -> tuple[int | None, str]:
    return split_course(raw)


def filter_members(members: Iterable[Member], kind: str, f: Filters,
                   unit_of: Callable[[str | None], svc.UnitInfo] | None = None) -> list[Member]:
    """Sof funksiya: fakultet/kurs/guruh (talaba) yoki bo'linma (xodim) va ism."""
    needle = svc.norm_name(f.q) if f.q else ""
    group_key = svc.norm_name(f.group) if f.group else ""
    out = []
    for m in members:
        if kind == "talaba":
            if f.faculty:
                if f.faculty == NO_FACULTY:
                    if m.faculty_id is not None:
                        continue
                elif str(m.faculty_id) != f.faculty:
                    continue
            if f.course is not None or group_key:
                course, group = student_course_group(m.raw)
                if f.course is not None and course != f.course:
                    continue
                if group_key and svc.norm_name(group) != group_key:
                    continue
        elif unit_of is not None and (f.unit_kind or f.unit):
            info = unit_of(m.raw)
            if f.unit and info.id != f.unit:
                continue
            if f.unit_kind and info.kind != f.unit_kind:
                continue
        if needle and needle not in svc.norm_name(m.name):
            continue
        out.append(m)
    return out


@dataclass(frozen=True)
class GroupKey:
    id: str
    name: str


def breakdown_level(kind: str, f: Filters, faculty_names: dict, unit_of) -> tuple[str, Callable[[Member], GroupKey]]:
    """Taqsimot darajasi: tanlangan filtrdan bir pog'ona pastroq."""
    if kind == "talaba":
        if not f.faculty:
            def by_faculty(m: Member) -> GroupKey:
                if m.faculty_id is None:
                    return GroupKey(NO_FACULTY, NO_FACULTY_LABEL)
                return GroupKey(str(m.faculty_id), faculty_names.get(m.faculty_id, NO_FACULTY_LABEL))
            return "Fakultetlar bo'yicha", by_faculty
        if f.course is None and not f.group:
            def by_course(m: Member) -> GroupKey:
                course, _ = student_course_group(m.raw)
                return GroupKey(str(course or 0), f"{course}-kurs" if course else "Kurs ko'rsatilmagan")
            return "Kurslar bo'yicha", by_course

        def by_group(m: Member) -> GroupKey:
            _, group = student_course_group(m.raw)
            return GroupKey(group or "", group or NO_GROUP_LABEL)
        return "Guruhlar bo'yicha", by_group

    def by_unit(m: Member) -> GroupKey:
        info = unit_of(m.raw)
        return GroupKey(info.id, info.name)
    return "Bo'linmalar bo'yicha", by_unit


# ─────────────────────────────────────────── o'lchovlar

@dataclass
class Att:
    present: int = 0
    late: int = 0
    absent: int = 0
    late_minutes: int = 0
    early: int = 0
    checked_out: int = 0  # erta ketish bo'yicha HUKM chiqarilgan kunlar
    unknown: int = 0      # baholab bo'lmagan kunlar ("aniqlanmadi")

    def add(self, other: "Att") -> "Att":
        for name in ("present", "late", "absent", "late_minutes", "early", "checked_out", "unknown"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        return self

    @property
    def rate(self) -> float | None:
        return svc.pct(self.present, self.present + self.absent)


@dataclass
class Tri:
    """Uch holatli sanoq: dars qatnashuvi yoki o'qituvchining darsga kelishi."""
    ok: int = 0
    late: int = 0
    miss: int = 0

    def add(self, other: "Tri") -> "Tri":
        self.ok += other.ok
        self.late += other.late
        self.miss += other.miss
        return self

    @property
    def total(self) -> int:
        return self.ok + self.late + self.miss

    @property
    def rate(self) -> float | None:
        """Kirgan ulushi (kech kirganlar ham kirgan) — talaba dars qatnashuvi."""
        return svc.pct(self.ok + self.late, self.total)

    @property
    def on_time_rate(self) -> float | None:
        """Faqat o'z vaqtida — o'qituvchining darsga kelishi (#22)."""
        return svc.pct(self.ok, self.total)

    def rate_for(self, key: str) -> float | None:
        return self.on_time_rate if key == "dars_otkazish" else self.rate


@dataclass
class Data:
    kind: str
    start: date_type
    end: date_type
    policy: Policy
    members: list[Member]
    att: dict[uuid.UUID, Att] = field(default_factory=dict)
    att_daily: dict[date_type, Att] = field(default_factory=dict)
    # Bitta kun tanlanganda: har bir odamning o'sha kungi yozuvi
    # (holat, kelgan vaqti, oxirgi ko'rilgan vaqti) — jadval uchun.
    day_rows: dict[uuid.UUID, dict] = field(default_factory=dict)
    lessons: dict[uuid.UUID, Tri] = field(default_factory=dict)
    lessons_daily: dict[date_type, Tri] = field(default_factory=dict)
    # COUNT_KEYS mezonlari: odam -> holatlar soni va kun -> holatlar soni.
    events: dict[str, dict[uuid.UUID, int]] = field(default_factory=dict)
    events_daily: dict[str, Counter] = field(default_factory=dict)
    active_modules: set[int] = field(default_factory=set)
    # Holat turi -> odam -> (holatlar soni, shundan video dalili borlari) —
    # kunlik tahlil dalillari (daily_person_criteria.details["dalillar"]).
    findings: dict[str, dict[uuid.UUID, tuple[int, int]]] = field(default_factory=dict)


def _minutes(column):
    return func.extract("hour", column) * 60 + func.extract("minute", column)


def _bounds(start: date_type, end: date_type) -> tuple[datetime, datetime]:
    return (day_start(start),
            day_start(end + timedelta(days=1)))


async def _attendance(db: AsyncSession, data: Data, cond) -> None:
    policy, kind = data.policy, data.kind
    start_t = policy.start_for(kind)
    start_min = start_t.hour * 60 + start_t.minute
    today = svc.today()
    status = AttendanceRecord.status
    present = status.in_(PRESENT)
    # Pastki chegara 0: qo'lda kiritilgan yoki boshlanish vaqti keyin
    # o'zgartirilgan "kech_keldi" yozuvi o'rtachani manfiyga tortmasin
    # (Policy.late_minutes va kunlik jadval ham 0 dan past bermaydi).
    late_min = func.coalesce(func.sum(func.greatest(_minutes(AttendanceRecord.check_in) - start_min, 0)).filter(
        and_(status == "kech_keldi", AttendanceRecord.check_in.is_not(None))), 0)
    # Erta ketish bu yerda SANALMAYDI: uning qoidasi ko'rinishlar tarixiga
    # tayanadi va SQL'da takrorlanmaydi — _early_leave() ga qarang.
    cols = (func.count().filter(present), func.count().filter(status == "kech_keldi"),
            func.count().filter(status == "kelmadi"), late_min)
    base = (
        select(*cols)
        .select_from(AttendanceRecord)
        .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
        .where(cond)
        .where(AttendanceRecord.date.between(data.start, min(data.end, today)))
    )
    per_person = base.add_columns(AttendanceRecord.student_staff_id).group_by(AttendanceRecord.student_staff_id)
    for *vals, pid in (await db.execute(per_person)).all():
        data.att[pid] = Att(*(int(v) for v in vals))
    per_day = base.add_columns(AttendanceRecord.date).group_by(AttendanceRecord.date)
    for *vals, day in (await db.execute(per_day)).all():
        data.att_daily[day] = Att(*(int(v) for v in vals))

    if data.start == data.end and data.start <= today:
        # Bitta kun — jadvalda haqiqiy vaqtlarni ko'rsatamiz.
        rows = await db.execute(
            select(AttendanceRecord.student_staff_id, AttendanceRecord.status, AttendanceRecord.check_in,
                   AttendanceRecord.check_out, AttendanceRecord.source)
            .select_from(AttendanceRecord)
            .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
            .where(cond).where(AttendanceRecord.date == data.start)
        )
        for pid, st, check_in, check_out, source in rows.all():
            # Kechikish daqiqasi — yuqoridagi `late_min` SQL yig'indisi bilan
            # bir xil: "kech_keldi" yozuvida kelish vaqti minus boshlanish.
            late = max(0, check_in.hour * 60 + check_in.minute - start_min) if (
                st == "kech_keldi" and check_in is not None) else 0
            data.day_rows[pid] = {"status": st, "check_in": check_in, "check_out": check_out, "source": source,
                                  "late": late, "early": EARLY_NA}


async def _sightings(db: AsyncSession, data: Data, cond) -> dict[tuple[uuid.UUID, date_type], tuple[time_type, int]]:
    """(odam, kun) -> (oxirgi ko'rinish payti, jami ko'rinishlar soni).

    Manba — presence_visits (app/models/presence_visit.py): bitta kameradagi
    ketma-ket ko'rinishlar bitta tashrifga birlashtirilgan, `sightings` esa
    necha marta ko'rilganini saqlaydi. Erta ketish qaroriga aynan shu son
    kerak: bir marta ko'rinish "o'sha payt ketdi" degani emas."""
    start_at, end_at = _bounds(data.start, min(data.end, svc.today()))
    local_last = func.timezone(INSTITUTE_TZ_NAME, PresenceVisit.last_seen_at)
    business_day = local_date(PresenceVisit.last_seen_at)
    rows = await db.execute(
        select(PresenceVisit.student_staff_id, business_day, func.max(local_last),
               func.sum(PresenceVisit.sightings))
        .select_from(PresenceVisit)
        .join(StudentStaff, StudentStaff.id == PresenceVisit.student_staff_id)
        .where(cond)
        .where(PresenceVisit.last_seen_at >= start_at)
        .where(PresenceVisit.last_seen_at < end_at)
        .group_by(PresenceVisit.student_staff_id, business_day)
    )
    return {
        (pid, day): (moment.time().replace(microsecond=0), int(count or 0))
        for pid, day, moment, count in rows.all()
    }


async def _early_leave(db: AsyncSession, data: Data, cond) -> None:
    """"Erta ketdi" / "aniqlanmadi" — odam va kun bo'yicha.

    Qoida bu yerda YOZILMAGAN: u app/services/attendance_policy.py dagi
    early_leave_verdict() — odam kartasi (app/routers/attendance.py) bilan
    aynan bitta. Ilgari uch xil hisob bor edi va hisobotdagi eng yumshog'i
    ("check_out ish tugashidan oldin") productionda 64 qatordan 54 tasini
    "erta ketdi" deb ko'rsatgan edi — direktor o'qiydigan hisobotda o'ylab
    topilgan ommaviy muammo.

    Baholab bo'lmagan kunlar `unknown` ga yig'iladi va hisobotda alohida
    ko'rsatiladi: "0 ta erta ketish" deb jim o'tish — yolg'on."""
    seen = await _sightings(db, data, cond)
    rows = await db.execute(
        select(AttendanceRecord.student_staff_id, AttendanceRecord.date, AttendanceRecord.status,
               AttendanceRecord.check_in, AttendanceRecord.check_out, AttendanceRecord.source)
        .select_from(AttendanceRecord)
        .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
        .where(cond)
        .where(AttendanceRecord.date.between(data.start, min(data.end, svc.today())))
        .where(AttendanceRecord.status.in_(PRESENT))
    )
    for pid, day, status, check_in, check_out, source in rows.all():
        last_seen, count = seen.get((pid, day), (None, None))
        verdict = early_leave_verdict(
            status=status, day=day, check_in=check_in, check_out=check_out,
            last_seen=last_seen, sightings=count, source=source, policy=data.policy,
        )
        if data.start == data.end and pid in data.day_rows:
            data.day_rows[pid]["early"] = verdict
        if verdict == EARLY_NA:
            continue
        for bucket in (data.att.get(pid), data.att_daily.get(day)):
            if bucket is None:
                continue
            if verdict == EARLY_UNKNOWN:
                bucket.unknown += 1
                continue
            bucket.checked_out += 1
            if verdict == EARLY_YES:
                bucket.early += 1


def _tri_cols(ok, late, miss):
    return func.count().filter(ok), func.count().filter(late), func.count().filter(miss)


async def _student_lessons(db: AsyncSession, data: Data, cond) -> None:
    st = LessonAttendance.status
    base = (
        select(*_tri_cols(st == "keldi", st == "kech_keldi", st == "kelmadi"))
        .select_from(LessonAttendance)
        .join(LessonSession, LessonSession.id == LessonAttendance.lesson_session_id)
        .join(StudentStaff, StudentStaff.id == LessonAttendance.student_staff_id)
        .where(cond)
        .where(LessonSession.date.between(data.start, data.end))
    )
    for *vals, pid in (await db.execute(base.add_columns(LessonAttendance.student_staff_id)
                                        .group_by(LessonAttendance.student_staff_id))).all():
        data.lessons[pid] = Tri(*vals)
    for *vals, day in (await db.execute(base.add_columns(LessonSession.date).group_by(LessonSession.date))).all():
        data.lessons_daily[day] = Tri(*vals)


async def _teacher_lessons(db: AsyncSession, data: Data, cond) -> None:
    """O'qituvchining darsga kelishi (#22): teacher_on_time True/False —
    tekshirilmagan (NULL) darslar hisobga kirmaydi. "Kech kirdi" (xonada
    ko'ringan, lekin kech) va "kirmadi" (umuman ko'rinmagan) alohida."""
    on_time = LessonSession.teacher_on_time
    seen = LessonSession.teacher_first_seen_at.is_not(None)
    base = (
        select(*_tri_cols(on_time.is_(True), and_(on_time.is_(False), seen), and_(on_time.is_(False), ~seen)))
        .select_from(LessonSession)
        .join(StudentStaff, StudentStaff.id == LessonSession.teacher_id)
        .where(cond)
        .where(on_time.is_not(None))
        .where(LessonSession.date.between(data.start, data.end))
    )
    for *vals, pid in (await db.execute(base.add_columns(LessonSession.teacher_id)
                                        .group_by(LessonSession.teacher_id))).all():
        data.lessons[pid] = Tri(*vals)
    for *vals, day in (await db.execute(base.add_columns(LessonSession.date).group_by(LessonSession.date))).all():
        data.lessons_daily[day] = Tri(*vals)


async def _criteria_counts(db: AsyncSession, data: Data, cond) -> None:
    """Kunlik video tahlil natijalari (app/batch/aggregate.py) — har odam va
    har kun bo'yicha holatlar soni: darsga kech kirish, darsdan erta chiqish,
    oq xalatsiz kunlar, chekish, diqqati va faolligi past darslar."""
    d = DailyPersonCriteria
    la = LessonAttendance
    ls = LessonSession
    queries = {
        "darsga_kech": select(la.student_staff_id, ls.date, func.count())
        .join(ls, ls.id == la.lesson_session_id)
        .join(StudentStaff, StudentStaff.id == la.student_staff_id)
        .where(cond, la.status == "kech_keldi", ls.date.between(data.start, data.end))
        .group_by(la.student_staff_id, ls.date),
        # Faollik o'lchangan (activity_samples > 0) darslar — o'lchanmagani
        # 0 ball bilan yozilgan, uni "past" deb sanash yolg'on bo'lardi.
        "faollik": select(ls.teacher_id, ls.date, func.count())
        .join(StudentStaff, StudentStaff.id == ls.teacher_id)
        .where(cond, ls.activity_samples > 0, ls.teacher_activity_score < low_activity(),
               ls.date.between(data.start, data.end))
        .group_by(ls.teacher_id, ls.date),
        "forma": select(d.student_staff_id, d.day, func.count())
        .join(StudentStaff, StudentStaff.id == d.student_staff_id)
        .where(cond, d.coat_status == "kiymagan", d.day.between(data.start, data.end))
        .group_by(d.student_staff_id, d.day),
        "chekish": select(d.student_staff_id, d.day, func.sum(d.smoking_events))
        .join(StudentStaff, StudentStaff.id == d.student_staff_id)
        .where(cond, d.smoking_events > 0, d.day.between(data.start, data.end))
        .group_by(d.student_staff_id, d.day),
        "diqqat": select(la.student_staff_id, LessonSession.date, func.count())
        .join(LessonSession, LessonSession.id == la.lesson_session_id)
        .join(StudentStaff, StudentStaff.id == la.student_staff_id)
        .where(cond, la.attention_score < low_attention(), LessonSession.date.between(data.start, data.end))
        .group_by(la.student_staff_id, LessonSession.date),
        "darsdan_erta": select(la.student_staff_id, LessonSession.date, func.count())
        .join(LessonSession, LessonSession.id == la.lesson_session_id)
        .join(StudentStaff, StudentStaff.id == la.student_staff_id)
        .where(cond, la.left_early.is_(True), LessonSession.date.between(data.start, data.end))
        .group_by(la.student_staff_id, LessonSession.date),
    }
    for key in (c.key for c in criteria_for(data.kind) if c.key in COUNT_KEYS):
        per_person: Counter = Counter()
        daily: Counter = Counter()
        for pid, day, count in (await db.execute(queries[key])).all():
            per_person[pid] += int(count or 0)
            daily[day] += int(count or 0)
        data.events[key] = dict(per_person)
        data.events_daily[key] = daily


async def _findings_counts(db: AsyncSession, data: Data, cond) -> None:
    """Har odam va holat turi bo'yicha: aniqlangan holatlar va shundan video
    dalili borlari (daily_person_criteria.details["dalillar"]). JSON ro'yxat
    SQL'da yoyiladi — 10 000 talaba × 30 kun Pythonga o'qilmaydi."""
    d = DailyPersonCriteria
    items = func.coalesce(d.details["dalillar"], literal_column("'[]'::jsonb"))
    item = func.jsonb_array_elements(items).table_valued("value").lateral("holat")
    kind_col = item.c.value.op("->>")("tur")
    code_col = item.c.value.op("->>")("kod")
    with_clip = func.count().filter(item.c.value.op("->>")("klip").is_not(None))
    rows = await db.execute(
        select(d.student_staff_id, kind_col, code_col, func.count(), with_clip)
        .select_from(d)
        .join(StudentStaff, StudentStaff.id == d.student_staff_id)
        .join(item, literal_column("true"))
        .where(cond, d.day.between(data.start, data.end))
        .group_by(d.student_staff_id, kind_col, code_col)
    )
    for pid, kind, code, total, clips in rows.all():
        key = holatlar.type_of({"tur": kind, "kod": code})
        if key is None:
            continue
        bucket = data.findings.setdefault(key, {})
        old_total, old_clips = bucket.get(pid, (0, 0))
        bucket[pid] = (old_total + int(total), old_clips + int(clips))


def findings_for(data: Data, key: str, pid: uuid.UUID) -> tuple[int, int]:
    """Mezon bo'yicha odamning (holatlar, video dalillar) soni."""
    total = clips = 0
    for kind in finding_types(key):
        n, c = data.findings.get(kind, {}).get(pid, (0, 0))
        total, clips = total + n, clips + c
    return total, clips


async def collect(db: AsyncSession, kind: str, start: date_type, end: date_type, f: Filters,
                  scope_members: list[Member], members: list[Member]) -> Data:
    data = Data(kind, start, end, await load_policy(db), members)
    data.active_modules = set((await db.execute(
        select(AIModuleConfig.code).where(AIModuleConfig.active.is_(True)))).scalars().all())
    # SQL doirasi: tur + faol (+ fakultet). Qolgan filtrlar Pythonda —
    # agar ular aholini toraytirgan bo'lsa, id ro'yxati qo'shiladi.
    cond = and_(StudentStaff.type == kind, StudentStaff.active.is_(True))
    faculty_cond = f.sql_faculty() if kind == "talaba" else None
    if faculty_cond is not None:
        cond = and_(cond, faculty_cond)
    if len(members) < len(scope_members):
        cond = and_(cond, StudentStaff.id.in_([m.id for m in members]) if members else StudentStaff.id.is_(None))

    await _attendance(db, data, cond)
    if kind == "xodim":
        # "Erta ketganlar" mezoni faqat xodimlar uchun (CRITERIA). Talabalar
        # uchun bu 10 000 kishi × yil bo'yi ko'rinishlarni xotiraga o'qirdi.
        await _early_leave(db, data, cond)
    if kind == "talaba":
        await _student_lessons(db, data, cond)
    else:
        await _teacher_lessons(db, data, cond)
    await _criteria_counts(db, data, cond)
    await _findings_counts(db, data, cond)
    return data


# ─────────────────────────────────────────── mezonlar

def _fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value:g}%".replace(".", ",")


def _days(start: date_type, end: date_type) -> list[date_type]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _tile(label: str, value: Any, unit: str = "", hint: str | None = None, tone: str = "neutral") -> dict:
    return {"label": label, "value": value, "unit": unit, "hint": hint, "tone": tone}


def _rate_tone(rate: float | None) -> str:
    if rate is None:
        return "neutral"
    return "success" if rate >= 90 else "warning" if rate >= 75 else "danger"


@dataclass
class Criterion:
    key: str
    label: str
    description: str
    kinds: tuple[str, ...]
    # Buyurtmachi ro'yxatidagi raqam (davomat — 6 xodim / 7 talaba).
    code: int | None = None
    # Shu mezonning dalili bo'lgan holat turlari (app/batch/holatlar.py).
    finding_types: tuple[str, ...] = ()


# Buyurtmachi ro'yxati tartibida (6, 7, 8, 9, 10, 15, 19, 21, 22).
CRITERIA = [
    Criterion("davomat", "Kelgan-kelmagani", "", KINDS, None, ()),
    Criterion("kechikish", "Kech kelganlar", "", KINDS, None, (holatlar.LATE,)),
    Criterion("dars_qatnashish", "Darsga kirgan talabalar", "", ("talaba",), STUDENT_ATTENDANCE_CODE,
              (holatlar.LESSON_ABSENT,)),
    Criterion("darsga_kech", "Darsga kech kirgan talabalar", "", ("talaba",), LESSON_LATE_CODE,
              (holatlar.LESSON_LATE,)),
    Criterion("darsdan_erta", "Darsdan erta chiqqan talabalar", "", ("talaba",), EARLY_LEAVE_CODE,
              (holatlar.LESSON_EARLY,)),
    Criterion("erta_ketish", "Ishdan erta ketganlar", "", ("xodim",), EARLY_LEAVE_CODE, (holatlar.WORK_EARLY,)),
    Criterion("forma", "Oq xalatsiz yurganlar", "", KINDS, COAT_CODE, (holatlar.NO_COAT,)),
    Criterion("chekish", "Chekkanlar", "", KINDS, SMOKING_CODE, (holatlar.SMOKING,)),
    Criterion("diqqat", "Darsda diqqati past talabalar", "", ("talaba",), ATTENTION_CODE, (holatlar.LOW_ATTENTION,)),
    Criterion("faollik", "Darsda faolligi past o'qituvchilar", "", ("xodim",), ACTIVITY_CODE,
              (holatlar.LOW_ACTIVITY,)),
    Criterion("dars_otkazish", "Darsga o'z vaqtida kirgan o'qituvchilar", "", ("xodim",), PUNCTUALITY_CODE,
              (holatlar.TEACHER_LATE, holatlar.TEACHER_ABSENT)),
]


def criterion_code(key: str, kind: str) -> int | None:
    """Mezonning buyurtmachi ro'yxatidagi raqami."""
    if key in ("davomat", "kechikish"):
        return STAFF_ATTENDANCE_CODE if kind == "xodim" else STUDENT_ATTENDANCE_CODE
    return next((c.code for c in CRITERIA if c.key == key), None)


def finding_types(key: str) -> tuple[str, ...]:
    return next((c.finding_types for c in CRITERIA if c.key == key), ())


def criteria_for(kind: str) -> list[Criterion]:
    return [c for c in CRITERIA if kind in c.kinds]


def _hhmm(value: time_type) -> str:
    return value.strftime("%H:%M")


def describe(key: str, policy: Policy, kind: str) -> str:
    """Mezon nimani o'lchashini bir qatorda, oddiy tilda — vaqtlar sozlamadan.

    Har bir jumla shu fayldagi hisobga mos: kech kelish `status == "kech_keldi"`
    (qoida: attendance_policy.late_after = boshlanish + ruxsat), erta ketish
    `check_out` ish tugashidan oldin, dars sonlari LessonAttendance'dan.
    """
    who = "Talaba" if kind == "talaba" else "Xodim"
    start, late_after = _hhmm(policy.start_for(kind)), _hhmm(policy.late_after(kind))
    if key == "davomat":
        return f"{who} kun davomida birorta kameraga tushganmi yoki yo'qmi — kunlar bo'yicha sanoq"
    if key == "kechikish":
        return f"Boshlanish {start}, {policy.grace_minutes} daqiqa ruxsat: {late_after} dan keyin birinchi marta ko'ringanlar"
    if key == "erta_ketish":
        return f"Ish {_hhmm(policy.work_end)} da tugaydi — undan oldin oxirgi marta ko'ringan kunlar"
    if key == "dars_otkazish":
        return (f"Jadvaldagi dars boshlanganda o'qituvchi xonada bo'lganmi: {settings.teacher_punctuality_grace_minutes} "
                "daqiqa ichida — o'z vaqtida, keyin — kech kirdi, umuman ko'rinmasa — kirmadi")
    if key == "dars_qatnashish":
        return "Dars jadvali bo'yicha: talaba darsda bo'lgan (kamida 2 marta ko'ringan) yoki kirmagan"
    if key == "darsga_kech":
        return (f"Dars boshlanib {settings.attendance_late_to_lesson_grace_minutes} daqiqadan keyin xonada birinchi "
                "marta ko'ringan — kamera o'sha paytda xonani ko'rgan bo'lsa")
    if key == "forma":
        return f"{who} kun bo'yi kameralarda ko'rilgan holatlarining ko'pida oq xalatsiz bo'lgan kunlar"
    if key == "chekish":
        return "Hovli va koridor kameralarida qo'lni og'izga takror ko'tarish — operator tekshiradigan holatlar"
    if key == "diqqat":
        return (f"Darsda yuzi doskaga qaramagan yoki qo'lida telefon bo'lgan — diqqat balli {low_attention()} "
                "dan past darslar")
    if key == "faollik":
        return (f"Darsda o'qituvchi harakati va xonada bo'lishi — faollik balli {low_activity()} dan past darslar")
    return "Darsning oxirgi daqiqalarida xonada ko'rinmagan — dars tugashidan oldin chiqib ketgan"


def _sum_att(data: Data, members: Iterable[Member]) -> Att:
    total = Att()
    for m in members:
        if m.id in data.att:
            total.add(data.att[m.id])
    return total


def _sum_tri(data: Data, members: Iterable[Member]) -> Tri:
    total = Tri()
    for m in members:
        if m.id in data.lessons:
            total.add(data.lessons[m.id])
    return total


def indicator(data: Data, key: str) -> tuple[str, str]:
    """Yon paneldagi qisqa ko'rsatkich va uning rangi.

    Hisoblab bo'lmasa — "—": nol ko'rsatish "hammasi joyida" degan noto'g'ri
    taassurot qoldirardi.
    """
    members = data.members
    if blocker(data, key):
        return "—", "neutral"
    if key == "davomat":
        rate = _sum_att(data, members).rate
        return _fmt_pct(rate), _rate_tone(rate)
    if key == "kechikish":
        n = _sum_att(data, members).late
        return str(n), "warning" if n else "neutral"
    if key == "erta_ketish":
        a = _sum_att(data, members)
        if a.checked_out == 0 and a.unknown:
            # Hech bir kun bo'yicha hukm chiqarib bo'lmadi — "0" emas, "—":
            # nol "hammasi joyida" degan noto'g'ri taassurot qoldirardi.
            return "—", "neutral"
        return str(a.early), "warning" if a.early else "neutral"
    if key in ("dars_otkazish", "dars_qatnashish"):
        rate = _sum_tri(data, members).rate_for(key)
        return _fmt_pct(rate), _rate_tone(rate)
    n = sum(data.events.get(key, {}).values())
    return str(n), "danger" if n else "neutral"


def blocker(data: Data, key: str) -> str | None:
    """Nima uchun bu son hozir hisoblanmayapti — 0 o'rniga sabab (oddiy tilda).

    Sabab bo'lsa, ko'rsatkich o'rnida "—" chiqadi: nol emas, "o'lchanmayapti".
    """
    att_code = STAFF_ATTENDANCE_CODE if data.kind == "xodim" else STUDENT_ATTENDANCE_CODE
    who = "talaba" if data.kind == "talaba" else "xodim"
    off = _module_off(data, key)
    # Modul o'chirilgan bo'lsa ham eski yozuvlar bo'lishi mumkin — ularni
    # yashirmaymiz, faqat izoh beramiz (note_for). To'sqinlik — ma'lumot ham
    # yo'q bo'lgandagina.
    if off and not _has_data(data, key):
        return off
    if key in ("davomat", "kechikish", "erta_ketish"):
        if not data.members:
            return f"Tanlangan filtrga mos {who} yo'q — filtrlarni kengaytiring."
        if not any(m.enrolled for m in data.members):
            return ("Bu ro'yxatdagi hech kimning yuzi tizimga kiritilmagan, shuning uchun kamera ularni tanimaydi va "
                    "davomat yozilmayapti. Yuzni kiritish: Odamlar → biometriya.")
        if key == "erta_ketish" and not data.policy.track_last_seen:
            return ("Odamning kundagi oxirgi ko'rinishi yozilmayapti (Sozlamalar → Ish vaqti), shuning uchun kim erta "
                    "ketganini aytib bo'lmaydi.")
    if key == "dars_otkazish" and not data.lessons_daily:
        return ("Bu kunlarda tekshirilgan dars yo'q: dars jadvaliga o'qituvchi yoki xona kamerasi biriktirilmagan "
                "bo'lishi mumkin.")
    if key == "dars_qatnashish" and not data.lessons_daily:
        return "Bu kunlar uchun dars jadvali kiritilmagan, shuning uchun darsga kim kirgani yozilmayapti."
    if key == "faollik" and not data.lessons_daily and not _has_data(data, key):
        return ("Bu kunlarda o'qituvchi faolligi o'lchangan dars yo'q: dars xonasi kamerasi biriktirilmagan yoki "
                "o'qituvchining yuzi tizimga kiritilmagan bo'lishi mumkin.")
    return None


# Qaysi AI moduli shu mezonni to'ldiradi va o'chirilganda nima deyiladi.
def module_off_text(kind: str, active_modules: set[int], key: str) -> str | None:
    """Mezonni to'ldiradigan modul o'chirilgan bo'lsa — bir gapli sabab.

    Alohida funksiya: oylik tabel (app/services/tabel.py) ham aynan shu
    gapni ishlatadi — bitta sabab ikki joyda ikki xil aytilmasin."""
    att_code = STAFF_ATTENDANCE_CODE if kind == "xodim" else STUDENT_ATTENDANCE_CODE
    pairs = {
        "davomat": (att_code, "Kelib-ketishni yuz orqali qayd etish"),
        "kechikish": (att_code, "Kelib-ketishni yuz orqali qayd etish"),
        "erta_ketish": (EARLY_LEAVE_CODE, "Erta ketishni aniqlash"),
        "dars_otkazish": (PUNCTUALITY_CODE, "O'qituvchining darsga kirishini tekshirish"),
        "dars_qatnashish": (STUDENT_ATTENDANCE_CODE, "Talaba davomati"),
        "darsga_kech": (LESSON_LATE_CODE, "Darsga kechikishni aniqlash"),
        "forma": (COAT_CODE, "Oq xalat tekshiruvi"),
        "chekish": (SMOKING_CODE, "Chekishni aniqlash"),
        "diqqat": (ATTENTION_CODE, "Talabaning darsga diqqati"),
        "faollik": (ACTIVITY_CODE, "O'qituvchi faolligi"),
        "darsdan_erta": (EARLY_LEAVE_CODE, "Darsdan erta ketishni aniqlash"),
    }
    pair = pairs.get(key)
    if pair is None or pair[0] in active_modules:
        return None
    return f"{pair[1]} hozir o'chirib qo'yilgan, shuning uchun yangi yozuvlar yig'ilmayapti. Sozlamalar → AI modullari."


def _module_off(data: Data, key: str) -> str | None:
    return module_off_text(data.kind, data.active_modules, key)


def not_enrolled_note(total: int, missing: int) -> str | None:
    """"N kishidan M tasining yuzi kiritilmagan" — bitta gap, ikki joyda bir xil."""
    if not missing:
        return None
    return (f"{total} kishidan {missing} tasining yuzi tizimga kiritilmagan — ular kameraga tushsa ham tanilmaydi.")


def _has_data(data: Data, key: str) -> bool:
    if key in ("davomat", "kechikish", "erta_ketish"):
        return bool(data.att_daily)
    if key in ("dars_otkazish", "dars_qatnashish"):
        return bool(data.lessons_daily)
    return bool(data.events.get(key))


def note_for(data: Data, key: str) -> str | None:
    """Sahifa tepasidagi ogohlantirish: to'sqinlik yoki qisman ma'lumot haqida."""
    stop = blocker(data, key)
    if stop:
        return stop
    parts = []
    off = _module_off(data, key)
    if off:
        parts.append(off + " Quyidagi sonlar oldin yig'ilgan yozuvlardan.")
    if key in COUNT_KEYS:
        parts.append("Ma'lumot kunlik video tahlildan (har kuni kechqurun NVR yozuvlaridan) olinadi.")
    if key in ("davomat", "kechikish", "erta_ketish"):
        missing = sum(1 for m in data.members if not m.enrolled)
        line = not_enrolled_note(len(data.members), missing)
        if line:
            parts.append(line)
    if key == "erta_ketish":
        # Halollik: baholab bo'lmagan kunlar "erta ketmadi" deb jimgina
        # o'tkazilmaydi, sahifa tepasida ochiq aytiladi.
        a = _sum_att(data, data.members)
        if a.unknown:
            parts.append(f"{a.unknown} kunni baholab bo'lmadi ({a.checked_out} kun bo'yicha hukm chiqarildi): "
                         "odam o'sha kuni kamerada bir martadan ko'p ko'rinmagan, shuning uchun oxirgi ko'rinishni "
                         "\"ketish payti\" deb hisoblash uchun asos yo'q.")
    return " ".join(parts) or None


@dataclass
class Spec:
    """Mezonning odam/guruh qiymati va ko'rinishi."""
    columns: list[dict]
    values: Callable[[uuid.UUID], dict | None]  # None — bu odam bo'yicha ma'lumot yo'q
    sort_key: str
    worst_desc: bool  # True — katta qiymat yomon
    group_value: Callable[[list[Member]], tuple[float | int | None, str]]
    group_unit: str


def _att_values(data: Data):
    def values(pid):
        a = data.att.get(pid)
        if a is None or a.present + a.absent == 0:
            return None
        return {"rate": a.rate, "present": a.present, "late": a.late, "absent": a.absent,
                "late_avg": round(a.late_minutes / a.late) if a.late else None, "early": a.early,
                "unknown": a.unknown}
    return values


STATUS_LABEL = {"keldi": "Keldi", "kech_keldi": "Kech keldi", "kelmadi": "Kelmadi", "dam_olish": "Dam olish"}
SOURCE_LABEL = {"kamera": "kamera", "turniket": "turniket", "qolda": "qo'lda kiritilgan", "dars": "dars kamerasi"}


def _day_spec(data: Data, key: str) -> Spec:
    """Bitta kun tanlanganda — direktor o'qiydigan jadval: holat, kelgan va
    ketgan vaqti, necha daqiqa kech, izoh. Sonlar `day_rows`dan, ya'ni
    AttendanceRecord qatoridan olinadi."""
    policy, kind = data.policy, data.kind
    late_after = _hhmm(policy.late_after(kind))
    enrolled = {m.id: m.enrolled for m in data.members}

    # Qaror _early_leave() da, umumiy qoida bo'yicha chiqarilgan (day_rows
    # ichida) — bu yerda faqat o'qiladi. Ilgari shu jadval o'zining alohida
    # ("check_out ish tugashidan oldin") hisobini yuritardi.
    def left_early(row: dict) -> bool:
        return row.get("early") == EARLY_YES

    def unjudged(row: dict) -> bool:
        return row.get("early") == EARLY_UNKNOWN

    def note_of(row: dict | None, pid: uuid.UUID) -> str:
        if row is None:
            return ("Yuzi tizimga kiritilmagan — kamera tanimaydi" if not enrolled.get(pid, False)
                    else "Bu kuni yozuv yo'q: kamerada ham ko'rinmadi, kelmadi deb ham belgilanmadi")
        parts = []
        if row["status"] == "kech_keldi":
            parts.append(f"{late_after} dan keyin ko'ringan, {row['late']} daqiqa kech")
        elif row["status"] == "keldi":
            parts.append(f"{late_after} gacha ko'ringan")
        elif row["status"] == "kelmadi":
            parts.append("Kun davomida hech bir kamerada ko'rinmadi")
        if left_early(row):
            parts.append(f"ish tugashidan ({_hhmm(policy.work_end)}) oldin ketgan")
        elif unjudged(row):
            parts.append("qachon ketgani aniqlanmadi — kun davomida kamerada yetarlicha ko'rinmagan")
        if row.get("source") and row["source"] != "kamera":
            parts.append(f"manba: {SOURCE_LABEL.get(row['source'], row['source'])}")
        return ", ".join(parts)

    # Saralash: avval kelmaganlar, keyin eng ko'p kechikkanlar, so'ng qolganlar.
    def order_of(row: dict | None) -> int:
        if row is None:
            return 1
        if row["status"] == "kelmadi":
            return 0
        if row["status"] == "kech_keldi":
            return 2
        return 3

    def values(pid):
        row = data.day_rows.get(pid)
        if key == "kechikish" and (row is None or row["status"] != "kech_keldi"):
            return None
        if key == "erta_ketish" and (row is None or not left_early(row)):
            return None
        if row is None and key != "davomat":
            return None
        return {
            "holat": STATUS_LABEL.get(row["status"], "Ma'lumot yo'q") if row else "Ma'lumot yo'q",
            "check_in": _hhmm(row["check_in"]) if row and row["check_in"] else None,
            "check_out": _hhmm(row["check_out"]) if row and row["check_out"] else None,
            "late_min": (row["late"] or None) if row else None,
            "note": note_of(row, pid),
            # Yashirin: jadval tartibi (frontendga ustun sifatida ketmaydi).
            "_order": order_of(row) * 100000 - (row["late"] if row else 0),
        }

    def gv(ms):
        a = _sum_att(data, ms)
        if key == "davomat":
            return a.rate, f"{a.present} keldi · {a.absent} kelmadi"
        if key == "kechikish":
            return a.late, f"kelgan {a.present} kishining {_fmt_pct(svc.pct(a.late, a.present))} i"
        tail = f", {a.unknown} tasida aniqlanmadi" if a.unknown else ""
        return a.early, f"hukm chiqarilgan {a.checked_out} yozuvning {_fmt_pct(svc.pct(a.early, a.checked_out))} i{tail}"

    cols = [
        {"key": "holat", "label": "Holati", "unit": "", "better": "none", "type": "text"},
        {"key": "check_in", "label": "Kelgan vaqti", "unit": "", "better": "none", "type": "text"},
        {"key": "check_out", "label": "Oxirgi ko'rilgan vaqti", "unit": "", "better": "none", "type": "text"},
        {"key": "late_min", "label": "Kechikish", "unit": "daqiqa", "better": "down", "type": "number"},
        {"key": "note", "label": "Izoh", "unit": "", "better": "none", "type": "text"},
    ]
    return Spec(cols, values, "_order", False, gv, "%" if key == "davomat" else "ta")


def spec_for(data: Data, key: str) -> Spec | None:
    col = lambda k, label, unit="", better="down": {  # noqa: E731
        "key": k, "label": label, "unit": unit, "better": better, "type": "number"}
    if data.start == data.end and key in ("davomat", "kechikish", "erta_ketish"):
        return _day_spec(data, key)
    if key == "davomat":
        def gv(ms):
            a = _sum_att(data, ms)
            return a.rate, f"{a.present} keldi · {a.absent} kelmadi"
        return Spec([col("rate", "Kelgan ulushi", "%", "up"), col("present", "Keldi", "kun", "up"),
                     col("late", "Kech keldi", "kun"), col("absent", "Kelmadi", "kun")],
                    _att_values(data), "rate", False, gv, "%")
    if key == "kechikish":
        base = _att_values(data)

        def values(pid):
            v = base(pid)
            return v if v and v["late"] else None

        def gv(ms):
            a = _sum_att(data, ms)
            return a.late, f"kelgan kunlarning {_fmt_pct(svc.pct(a.late, a.present))} i"
        return Spec([col("late", "Kech keldi", "kun"), col("late_avg", "O'rtacha kechikish", "daqiqa"),
                     col("present", "Kelgan kunlari", "kun", "up")], values, "late", True, gv, "ta")
    if key == "erta_ketish":
        base = _att_values(data)

        def values(pid):
            v = base(pid)
            return v if v and v["early"] else None

        def gv(ms):
            a = _sum_att(data, ms)
            tail = f", yana {a.unknown} kun aniqlanmadi" if a.unknown else ""
            return a.early, f"hukm chiqarilgan kunlarning {_fmt_pct(svc.pct(a.early, a.checked_out))} i{tail}"
        return Spec([col("early", "Erta ketdi", "kun"), col("unknown", "Aniqlanmadi", "kun", "none"),
                     col("present", "Kelgan kunlari", "kun", "up")],
                    values, "early", True, gv, "ta")
    if key in ("dars_otkazish", "dars_qatnashish"):
        teacher = key == "dars_otkazish"

        def values(pid):
            t = data.lessons.get(pid)
            if t is None or t.total == 0:
                return None
            return {"rate": t.rate_for(key), "ok": t.ok, "late": t.late, "miss": t.miss, "total": t.total}

        def gv(ms):
            t = _sum_tri(data, ms)
            return t.rate_for(key), f"{t.total} dars"
        cols = [col("rate", "O'z vaqtida kirgan darslari" if teacher else "Darsga kirgan ulushi", "%", "up"),
                col("total", "Jami darslar", "ta", "none"),
                col("late", "Kech kirdi", "ta"), col("miss", "Kirmadi", "ta")]
        return Spec(cols, values, "rate", False, gv, "%")
    if key in COUNT_KEYS:
        counts = data.events.get(key, {})

        def values(pid):
            n = counts.get(pid, 0)
            return {"events": n} if n else None

        def gv(ms):
            n = sum(counts.get(m.id, 0) for m in ms)
            return n, f"{sum(1 for m in ms if counts.get(m.id))} kishida uchragan"
        return Spec([col("events", COUNT_COLUMN[key], "ta")], values, "events", True, gv, "ta")
    return None


def _trend(data: Data, key: str) -> dict:
    days = [d for d in _days(data.start, min(data.end, svc.today()))]
    points = []
    for day in days:
        if key == "davomat":
            a = data.att_daily.get(day)
            value = a.rate if a else None
        elif key == "kechikish":
            value = data.att_daily[day].late if day in data.att_daily else 0
        elif key == "erta_ketish":
            value = data.att_daily[day].early if day in data.att_daily else 0
        elif key in ("dars_otkazish", "dars_qatnashish"):
            t = data.lessons_daily.get(day)
            value = t.rate_for(key) if t else None
        else:
            value = data.events_daily.get(key, Counter()).get(day, 0)
        points.append({"date": day.isoformat(), "value": value})
    rate = key in ("davomat", "dars_otkazish", "dars_qatnashish")
    return {"unit": "%" if rate else "ta", "points": points,
            "title": _TREND_TITLE[key], "axis": _TREND_AXIS[key], "explain": _TREND_EXPLAIN[key]}


# Grafik sarlavhasi, tik o'q yorlig'i va bir qatorli tushuntirish — har biri
# yuqoridagi _trend() qaysi sonni kunga yozishiga mos.
_TREND_TITLE = {
    "davomat": "Har kuni nechtasi kelgan",
    "kechikish": "Har kuni nechta kech kelish bo'lgan",
    "erta_ketish": "Har kuni nechta erta ketish bo'lgan",
    "dars_otkazish": "Darslar har kuni o'z vaqtida boshlanganmi",
    "dars_qatnashish": "Har kuni darsga nechtasi kirgan",
    "forma": "Har kuni nechta kishi oq xalatsiz yurgan",
    "chekish": "Har kuni nechta chekish holati qayd etilgan",
    "diqqat": "Har kuni nechta darsda diqqat past bo'lgan",
    "darsdan_erta": "Har kuni nechta darsdan erta chiqilgan",
    "darsga_kech": "Har kuni nechta darsga kech kirilgan",
    "faollik": "Har kuni nechta darsda o'qituvchi faolligi past bo'lgan",
}
_TREND_AXIS = {
    "davomat": "Kelganlar ulushi, %",
    "kechikish": "Kech kelish holatlari, ta",
    "erta_ketish": "Erta ketish holatlari, ta",
    "dars_otkazish": "O'z vaqtida boshlangan darslar ulushi, %",
    "dars_qatnashish": "Darsga kirganlar ulushi, %",
    "forma": "Kishilar soni, ta",
    "chekish": "Holatlar soni, ta",
    "diqqat": "Darslar soni, ta",
    "darsdan_erta": "Darslar soni, ta",
    "darsga_kech": "Darslar soni, ta",
    "faollik": "Darslar soni, ta",
}
_TREND_EXPLAIN = {
    "davomat": "Har bir ustun — o'sha kuni kelganlarning kelgan va kelmaganlar yig'indisiga nisbati.",
    "kechikish": "Har bir ustun — o'sha kuni belgilangan vaqtdan keyin birinchi marta ko'ringanlar soni.",
    "erta_ketish": "Har bir ustun — o'sha kuni ish tugashidan oldin oxirgi marta ko'ringanlar soni.",
    "dars_otkazish": "Har bir ustun — o'sha kuni tekshirilgan darslarning o'z vaqtida boshlangan ulushi.",
    "dars_qatnashish": "Har bir ustun — o'sha kungi dars yozuvlaridan darsda bo'lganlarning (kech kirganlar bilan) ulushi.",
    "forma": "Har bir ustun — o'sha kuni kuzatuvlarining ko'pida oq xalatsiz bo'lgan kishilar soni.",
    "chekish": "Har bir ustun — o'sha kuni tanilgan odamga bog'langan chekish holatlari soni.",
    "diqqat": "Har bir ustun — o'sha kuni diqqat balli past (sozlamadagi chegaradan) bo'lgan talaba-darslar soni.",
    "darsdan_erta": "Har bir ustun — o'sha kuni dars tugashidan oldin chiqib ketilgan talaba-darslar soni.",
    "darsga_kech": "Har bir ustun — o'sha kuni dars boshlanib ruxsat etilgan vaqtdan keyin xonaga kirgan talaba-darslar soni.",
    "faollik": "Har bir ustun — o'sha kuni faollik balli past bo'lgan o'qituvchi darslari soni.",
}


def _tiles(data: Data, key: str) -> list[dict]:
    ms = data.members
    enrolled = sum(1 for m in ms if m.enrolled)
    if key in ("davomat", "kechikish", "erta_ketish"):
        a = _sum_att(data, ms)
        people_with = [data.att[m.id] for m in ms if m.id in data.att]
        start_at = _hhmm(data.policy.start_for(data.kind))
        late_after = _hhmm(data.policy.late_after(data.kind))
        day_word = "kun" if len(_days(data.start, data.end)) > 1 else "kishi"
        if key == "davomat":
            return [
                _tile("Kelganlar ulushi", _fmt_pct(a.rate),
                      hint=f"Kelgan va kelmagan {a.present + a.absent} {day_word}dan kelganlari",
                      tone=_rate_tone(a.rate)),
                _tile("Keldi", a.present, day_word,
                      f"Shundan {a.late} tasi kech keldi ({late_after} dan keyin)", "success"),
                _tile("Kelmadi", a.absent, day_word,
                      f"{sum(1 for p in people_with if p.absent)} kishida kelmagan {day_word} bor", "danger"),
                _tile("Yuzi kiritilgan", enrolled, "kishi",
                      f"Ro'yxatdagi {len(ms)} kishidan. Faqat ularni kamera taniy oladi", "info"),
            ]
        if key == "kechikish":
            late_people = sum(1 for p in people_with if p.late)
            return [
                _tile("Kech kelish holatlari", a.late, "ta",
                      f"Kelgan {a.present} {day_word}ning {_fmt_pct(svc.pct(a.late, a.present))} i", "warning"),
                _tile("Kech kelgan kishilar", late_people, "kishi",
                      f"Yozuvi bor {len(people_with)} kishidan", "warning"),
                _tile("O'rtacha necha daqiqa kech", round(a.late_minutes / a.late) if a.late else "—", "daqiqa",
                      f"Boshlanish {start_at}, {data.policy.grace_minutes} daqiqa ruxsat — {late_after} dan keyin kech"),
                _tile("O'z vaqtida kelgan", a.present - a.late, day_word,
                      f"{late_after} gacha ko'ringanlar", "success"),
            ]
        early_people = sum(1 for p in people_with if p.early)
        return [
            _tile("Erta ketish holatlari", a.early, "ta",
                  f"Hukm chiqarilgan {a.checked_out} kunning "
                  f"{_fmt_pct(svc.pct(a.early, a.checked_out))} i", "warning"),
            _tile("Erta ketgan kishilar", early_people, "kishi", f"Yozuvi bor {len(people_with)} kishidan", "warning"),
            # Halollik plitkasi: baholab bo'lmagan kunlar 0 ga qo'shilmaydi.
            _tile("Aniqlab bo'lmadi", a.unknown, "kun",
                  "Kamera o'sha kuni odamni yetarlicha ko'rmagan — qachon ketgani noma'lum",
                  "warning" if a.unknown else "neutral"),
            _tile("Hukm chiqarilgan kunlar", a.checked_out, "kun",
                  f"O'tgan ish kunlari, ish tugashi {_hhmm(data.policy.work_end)}; bugungi kun hali tugamagani "
                  "uchun hisobga olinmaydi"),
        ]
    if key in ("dars_otkazish", "dars_qatnashish"):
        t = _sum_tri(data, ms)
        who = sum(1 for m in ms if m.id in data.lessons)
        if key == "dars_otkazish":
            return [
                _tile("O'z vaqtida kirgan darslar ulushi", _fmt_pct(svc.pct(t.ok, t.total)),
                      hint=f"Tekshirilgan {t.total} darsdan o'z vaqtida boshlanganlari",
                      tone=_rate_tone(svc.pct(t.ok, t.total))),
                _tile("O'z vaqtida boshlangan", t.ok, "dars", f"{who} o'qituvchining darslari", "success"),
                _tile("O'qituvchi kech kirgan", t.late, "dars", "Xonada ko'ringan, lekin ruxsat etilgan vaqtdan keyin",
                      "warning"),
                _tile("O'qituvchi kirmagan", t.miss, "dars", "Kamera xonani ko'rgan, o'qituvchi ko'rinmagan",
                      "danger"),
            ]
        return [
            _tile("Darsga kirganlar ulushi", _fmt_pct(t.rate),
                  hint=f"Jami {t.total} ta dars yozuvidan (kech kirganlar ham kirgan hisoblanadi)",
                  tone=_rate_tone(t.rate)),
            _tile("Darsda bo'lgan", t.ok, "ta dars", None, "success"),
            _tile("Darsga kech kirgan", t.late, "ta dars", None, "warning"),
            _tile("Darsga kirmagan", t.miss, "ta dars", f"{who} talabaning yozuvi bo'yicha", "danger"),
        ]
    counts = data.events.get(key, {})
    ids = {m.id for m in ms}
    total = sum(n for pid, n in counts.items() if pid in ids)
    people = sum(1 for pid in counts if pid in ids)
    unit = "kun" if key == "forma" else "ta"
    return [
        _tile(COUNT_COLUMN[key], total, unit, "Kunlik video tahlil natijalari bo'yicha",
              "danger" if total else "neutral"),
        _tile("Necha kishida uchradi", people, "kishi", f"Ro'yxatdagi {len(ms)} kishidan",
              "warning" if people else "neutral"),
        _tile("Bir kishiga o'rtacha", f"{total / people:.1f}".replace(".", ",") if people else "—", unit,
              "Faqat holati aniqlangan kishilar bo'yicha"),
    ]


# ─────────────────────────────────────────── gap bilan aytilgan javob

def _plural(kind: str) -> str:
    return "talaba" if kind == "talaba" else "xodim"


def period_words(data: Data) -> str:
    """Davrni gap ichida ishlatish uchun: "bugun", "tanlangan kunda", "5 kun ichida"."""
    days = (data.end - data.start).days + 1
    if days > 1:
        return f"{days} kun ichida"
    return "bugun" if data.start == svc.today() else "tanlangan kunda"


def summary_lines(data: Data, key: str, scope: str) -> list[str]:
    """Sahifa tepasidagi javob — plitkalardagi ayni sonlardan tuziladi.

    Ma'lumot bo'lmasa son o'rniga sabab yoziladi (bo'sh gap qolmaydi).
    """
    stop = blocker(data, key)
    if stop:
        return [f"{scope}: hozircha bu savolga javob berib bo'lmaydi.", stop]
    who, when = _plural(data.kind), period_words(data)
    total = len(data.members)
    ms = data.members
    lines: list[str] = []

    if key in ("davomat", "kechikish", "erta_ketish"):
        a = _sum_att(data, ms)
        one_day = data.start == data.end
        day_word = "kishi" if one_day else "kun"
        late_after = _hhmm(data.policy.late_after(data.kind))
        if a.present + a.absent == 0:
            lines.append(f"{scope}: {when} {total} {who}dan birortasi ham kamerada ko'rinmadi va kelmagan deb ham "
                         "belgilanmadi — bu davrda davomat yozuvi yo'q.")
        elif key == "davomat":
            unknown = total - (a.present + a.absent) if one_day else 0
            tail = f", {unknown} tasi haqida yozuv yo'q" if unknown > 0 else ""
            if one_day:
                lines.append(f"{scope}: {total} {who}dan {when} {a.present - a.late} tasi o'z vaqtida keldi, "
                             f"{a.late} tasi kech keldi, {a.absent} tasi kelmadi{tail}.")
            else:
                lines.append(f"{scope}: {total} {who} bo'yicha {when} {a.present + a.absent} ta kunlik yozuv bor — "
                             f"{a.present} kunda kelgan (shundan {a.late} kunda kech), {a.absent} kunda kelmagan.")
            lines.append(f"Kelganlar ulushi — {_fmt_pct(a.rate)}.")
        elif key == "kechikish":
            if a.late == 0:
                lines.append(f"{scope}: {when} hech kim kech kelmadi — kelganlarning hammasi {late_after} gacha "
                             "kamerada ko'rindi.")
            else:
                avg = round(a.late_minutes / a.late)
                lines.append(f"{scope}: {when} {a.late} marta kech kelindi — bu kelgan {a.present} {day_word}ning "
                             f"{_fmt_pct(svc.pct(a.late, a.present))} i. O'rtacha {avg} daqiqa kech "
                             f"(kech kelish — {late_after} dan keyin birinchi marta ko'rinish).")
        else:
            # "Aniqlanmadi" ATAYLAB alohida aytiladi: kamera qoplamasi siyrak
            # bo'lgan joyda "0 ta erta ketish" ham, "hamma erta ketdi" ham
            # bir xil yolg'on.
            unsure = (f" Yana {a.unknown} kunni baholab bo'lmadi: kamera o'sha kuni odamni yetarlicha ko'rmagan, "
                      "shuning uchun qachon ketgani aniqlanmadi.") if a.unknown else ""
            if a.checked_out == 0:
                lines.append(f"{scope}: erta ketish haqida hukm chiqarib bo'ladigan kun yo'q — bugungi kun hisobga "
                             f"olinmaydi, qolgan kunlarda esa dalil yetarli emas.{unsure}")
            elif a.early == 0:
                lines.append(f"{scope}: {when} hech kim ish tugashidan ({_hhmm(data.policy.work_end)}) oldin "
                             f"ketmadi — {a.checked_out} kun bo'yicha hukm chiqarildi.{unsure}")
            else:
                lines.append(f"{scope}: {when} {a.early} marta ish tugashidan ({_hhmm(data.policy.work_end)}) oldin "
                             f"ketilgan — hukm chiqarilgan {a.checked_out} kunning "
                             f"{_fmt_pct(svc.pct(a.early, a.checked_out))} i.{unsure}")
    elif key in ("dars_otkazish", "dars_qatnashish"):
        t = _sum_tri(data, ms)
        if t.total == 0:
            lines.append(f"{scope}: {when} tekshirilgan dars topilmadi.")
        elif key == "dars_qatnashish":
            lines.append(f"{scope}: {when} {t.total} ta dars yozuvidan {t.ok} tasida talaba darsda bo'lgan, "
                         f"{t.late} tasida kech kirgan, {t.miss} tasida kirmagan.")
            lines.append(f"Darsga kirganlar ulushi — {_fmt_pct(t.rate)} (kech kirganlar ham kirgan hisoblanadi).")
        else:
            lines.append(f"{scope}: {when} tekshirilgan {t.total} darsdan {t.ok} tasiga o'qituvchi o'z vaqtida "
                         f"kirgan, {t.late} tasiga kech kirgan, {t.miss} tasiga umuman kirmagan.")
            lines.append(f"O'z vaqtida boshlangan darslar ulushi — {_fmt_pct(svc.pct(t.ok, t.total))}.")
    else:
        counts = data.events.get(key, {})
        ids = {m.id for m in ms}
        n = sum(v for pid, v in counts.items() if pid in ids)
        people = sum(1 for pid in counts if pid in ids)
        what = COUNT_WHAT[key]
        lines.append(f"{scope}: {when} {n} ta {what} qayd etildi — {people} kishida "
                     f"(ro'yxatdagi {total} {who}dan)." if n
                     else f"{scope}: {when} {what} qayd etilmadi.")

    extra = note_for(data, key)
    if extra and extra not in lines:
        lines.append(extra)
    return lines


def scope_label(kind: str, f: Filters, faculty_names: dict, members: list[Member],
                unit_of: Callable[[str | None], svc.UnitInfo] | None) -> str:
    """Tanlovning odamcha nomi: "Davolash ishi, 2-kurs, DI-2301 guruhi"."""
    parts: list[str] = []
    if kind == "talaba":
        if f.faculty:
            name = NO_FACULTY_LABEL if f.faculty == NO_FACULTY else None
            if name is None:
                try:
                    name = faculty_names.get(uuid.UUID(f.faculty), NO_FACULTY_LABEL)
                except ValueError:
                    name = NO_FACULTY_LABEL
            parts.append(str(name))
        if f.course:
            parts.append(f"{f.course}-kurs")
        if f.group:
            parts.append(f"{f.group} guruhi")
    else:
        if f.unit and members and unit_of is not None:
            parts.append(unit_of(members[0].raw).name)
        elif f.unit_kind:
            parts.append(UNIT_KIND_LABELS.get(f.unit_kind, f.unit_kind))
    if f.q:
        parts.append(f"ismida «{f.q}» bo'lganlar")
    if not parts:
        return "Barcha talabalar" if kind == "talaba" else "Barcha xodimlar"
    return ", ".join(parts)


# Odamlar jadvalining sarlavhasi va saralash tartibi — build_report'dagi
# people.sort() bilan bir xil aytiladi (eng yomoni yuqorida).
_PEOPLE_TITLE = {
    "davomat": "Kim qancha kelgan",
    "kechikish": "Kim kech kelgan",
    "erta_ketish": "Kim erta ketgan",
    "dars_otkazish": "Qaysi o'qituvchi darsga kech kirgan yoki kirmagan",
    "dars_qatnashish": "Qaysi talaba darsga kirmagan",
    "forma": "Kim oq xalatsiz yurgan",
    "chekish": "Kim chekkan",
    "diqqat": "Qaysi talabaning diqqati past",
    "darsdan_erta": "Kim darsdan erta chiqqan",
    "darsga_kech": "Kim darsga kech kirgan",
    "faollik": "Qaysi o'qituvchining darsdagi faolligi past",
}
_PEOPLE_HINT = {
    "davomat": "Eng kam kelgan kishi yuqorida. Faqat shu davrda kelgan yoki kelmagan deb yozilganlar ro'yxatda.",
    "kechikish": "Eng ko'p kech kelgan kishi yuqorida. Bir marta ham kech kelmaganlar ro'yxatga kirmaydi.",
    "erta_ketish": "Eng ko'p erta ketgan kishi yuqorida. Erta ketmaganlar ro'yxatga kirmaydi.",
    "dars_otkazish": "O'z vaqtida kirgan darslari eng kam o'qituvchi yuqorida.",
    "dars_qatnashish": "Darsga kirgan ulushi eng past talaba yuqorida.",
    "forma": "Oq xalatsiz kunlari eng ko'p kishi yuqorida.",
    "chekish": "Holati eng ko'p takrorlangan kishi yuqorida.",
    "diqqat": "Diqqati past darslari eng ko'p talaba yuqorida.",
    "darsdan_erta": "Eng ko'p erta chiqqan talaba yuqorida.",
    "darsga_kech": "Eng ko'p kech kirgan talaba yuqorida.",
    "faollik": "Faolligi past darslari eng ko'p o'qituvchi yuqorida.",
}
SORT_HINT = "Ustun nomini bosib tartibni o'zgartirish mumkin."

_BREAKDOWN_SUBTITLE = {
    "davomat": "Har bir qatorda kelganlarning ulushi",
    "kechikish": "Har bir qatorda kech kelish holatlari soni",
    "erta_ketish": "Har bir qatorda erta ketish holatlari soni",
    "dars_otkazish": "Har bir qatorda o'z vaqtida boshlangan darslar ulushi",
    "dars_qatnashish": "Har bir qatorda darsga kirganlar ulushi",
    "forma": "Har bir qatorda oq xalatsiz kunlar soni",
    "chekish": "Har bir qatorda holatlar soni",
    "diqqat": "Har bir qatorda diqqati past darslar soni",
    "darsdan_erta": "Har bir qatorda erta chiqilgan darslar soni",
    "darsga_kech": "Har bir qatorda kech kirilgan darslar soni",
    "faollik": "Har bir qatorda faolligi past darslar soni",
}


def _empty_state(data: Data, key: str) -> dict:
    """Bo'sh ro'yxat sababi va nima qilish kerakligi — quruq "Ma'lumot yo'q" emas."""
    stop = blocker(data, key)
    if stop:
        return {"title": "Bu son hozir hisoblanmayapti", "description": stop}
    when = period_words(data)
    who = _plural(data.kind)
    if key in ("davomat", "kechikish", "erta_ketish"):
        a = _sum_att(data, data.members)
        if a.present + a.absent == 0:
            return {"title": "Bu davrda davomat yozuvi yo'q",
                    "description": f"{when.capitalize()} tanlangan {len(data.members)} {who} bo'yicha birorta kelgan "
                                   "yoki kelmagan yozuvi yo'q. Boshqa kunni tanlang yoki kameralar ishlayotganini "
                                   "tekshiring."}
        if key == "kechikish":
            return {"title": "Kech kelgan odam yo'q",
                    "description": f"{when.capitalize()} kelganlarning hammasi "
                                   f"{_hhmm(data.policy.late_after(data.kind))} gacha kamerada ko'rindi."}
        if key == "erta_ketish":
            return {"title": "Erta ketgan odam yo'q",
                    "description": f"{when.capitalize()} hech kim ish tugashidan "
                                   f"({_hhmm(data.policy.work_end)}) oldin ketmagan."}
        return {"title": "Ro'yxat bo'sh", "description": "Tanlangan filtrga mos odam topilmadi."}
    if key in ("dars_otkazish", "dars_qatnashish"):
        return {"title": "Tekshirilgan dars yo'q",
                "description": f"{when.capitalize()} bu tanlov bo'yicha dars jadvalida tekshirilgan dars topilmadi."}
    what = COUNT_WHAT[key]
    return {"title": "Birorta holat qayd etilmagan",
            "description": f"{when.capitalize()} {what} qayd etilmadi — bu yaxshi natija (yoki bu kunlar hali "
                           "tahlil qilinmagan)."}


def _row_out(m: Member, unit: str, values: dict) -> dict:
    return {"id": str(m.id), "full_name": m.name, "initials": svc.initials(m.name),
            "photo_url": svc.photo_url(m.photo_key), "unit": unit, "values": values}


EVIDENCE_COLUMN = {"key": "dalil", "label": "Video dalil", "unit": "ta", "better": "none", "type": "number"}


def with_evidence(data: Data, key: str, spec: Spec | None) -> Spec | None:
    """Odam qatoriga shu mezon bo'yicha video dalillar soni (2 daqiqalik
    klip — odam kartasida ko'riladi). Dalil turi yo'q mezonda o'zgarmaydi."""
    if spec is None or not finding_types(key):
        return spec
    base = spec.values

    def values(pid):
        row = base(pid)
        if row is None:
            return None
        _total, clips = findings_for(data, key, pid)
        return {**row, "dalil": clips or None}

    return replace(spec, columns=[*spec.columns, EVIDENCE_COLUMN], values=values)


def build_report(data: Data, key: str, group_title: str, group_of: Callable[[Member], GroupKey],
                 unit_label: Callable[[Member], str], limit: int | None = PEOPLE_LIMIT) -> dict:
    spec = with_evidence(data, key, spec_for(data, key))
    report: dict = {"tiles": _tiles(data, key), "trend": _trend(data, key), "note": note_for(data, key),
                    "blocked": blocker(data, key) is not None,
                    "columns": [], "people": [], "people_total": 0, "breakdown": None,
                    "people_title": _PEOPLE_TITLE[key], "people_hint": _PEOPLE_HINT[key],
                    "empty": None, "sort_key": None, "worst_desc": True}
    if spec is None:
        report["empty"] = _empty_state(data, key)
        return report

    groups: dict[GroupKey, list[Member]] = defaultdict(list)
    for m in data.members:
        groups[group_of(m)].append(m)
    rows = []
    for g, ms in groups.items():
        value, detail = spec.group_value(ms)
        rows.append({"id": g.id, "name": g.name, "value": value, "detail": detail, "headcount": len(ms)})
    rate_like = spec.group_unit == "%"
    known = sorted((r for r in rows if r["value"] is not None), key=lambda r: r["value"], reverse=not rate_like)
    unknown = sorted((r for r in rows if r["value"] is None), key=lambda r: svc.norm_name(r["name"]))
    report["breakdown"] = {"title": group_title, "subtitle": _BREAKDOWN_SUBTITLE[key], "unit": spec.group_unit,
                           "better": "up" if rate_like else "down", "rows": known + unknown}

    people = []
    for m in data.members:
        values = spec.values(m.id)
        if values is not None:
            people.append((m, values))
    sign = -1 if spec.worst_desc else 1
    people.sort(key=lambda mv: (sign * (mv[1][spec.sort_key] or 0), svc.norm_name(mv[0].name)))
    report["people_total"] = len(people)
    picked = people if limit is None else people[:limit]
    hidden = spec.sort_key.startswith("_")  # jadval tartibi serverda — ustun emas
    report["people"] = [_row_out(m, unit_label(m), {k: val for k, val in v.items() if not k.startswith("_")})
                        for m, v in picked]
    report["columns"] = spec.columns
    report["sort_key"] = None if hidden else spec.sort_key
    report["worst_desc"] = spec.worst_desc
    report["people_hint"] = ("Tartib: avval kelmaganlar, keyin yozuvi yo'qlar, so'ng eng ko'p kech kelganlar."
                             if hidden else _PEOPLE_HINT[key]) + " " + SORT_HINT
    if not people:
        report["empty"] = _empty_state(data, key)
    return report


# ─────────────────────────────────────────── yig'uvchi

@dataclass
class Context:
    kind: str
    start: date_type
    end: date_type
    filters: Filters
    scope: list[Member]
    members: list[Member]
    unit_of: Callable[[str | None], svc.UnitInfo] | None
    faculty_names: dict


async def context(db: AsyncSession, kind: str, start: date_type, end: date_type, f: Filters) -> Context:
    everyone = await population(db, kind)
    unit_of = None
    if kind == "xodim":
        catalog = await svc.unit_catalog(db)
        unit_of = lambda raw: catalog.units[catalog.unit_id(raw)]  # noqa: E731
        scope = everyone
    else:
        scope = filter_members(everyone, kind, Filters(faculty=f.faculty))
    members = filter_members(scope, kind, f, unit_of)
    return Context(kind, start, end, f, scope, members, unit_of, await svc.faculty_names(db))


def unit_label_fn(ctx: Context) -> Callable[[Member], str]:
    if ctx.kind == "xodim":
        return lambda m: ctx.unit_of(m.raw).name if ctx.unit_of else (m.raw or "")

    def label(m: Member) -> str:
        course, group = student_course_group(m.raw)
        parts = [ctx.faculty_names.get(m.faculty_id) if m.faculty_id else None,
                 f"{course}-kurs" if course else None, group or None]
        return " · ".join(p for p in parts if p)
    return label


async def report(db: AsyncSession, kind: str, start: date_type, end: date_type, f: Filters, criterion: str | None,
                 limit: int | None = PEOPLE_LIMIT) -> dict:
    ctx = await context(db, kind, start, end, f)
    data = await collect(db, kind, start, end, f, ctx.scope, ctx.members)
    available = criteria_for(kind)
    key = criterion if any(c.key == criterion for c in available) else available[0].key
    criteria = []
    for c in available:
        value, tone = indicator(data, c.key)
        stop = blocker(data, c.key)
        criteria.append({"key": c.key, "code": criterion_code(c.key, kind), "label": c.label,
                         "description": describe(c.key, data.policy, kind),
                         "indicator": value, "tone": tone, "unavailable": stop, "available": stop is None})
    title, group_of = breakdown_level(kind, f, ctx.faculty_names, ctx.unit_of)
    body = build_report(data, key, title, group_of, unit_label_fn(ctx), limit)
    scope = scope_label(kind, f, ctx.faculty_names, ctx.members, ctx.unit_of)
    enrolled = sum(1 for m in ctx.members if m.enrolled)
    body["summary"] = summary_lines(data, key, scope)
    return {
        "kind": kind,
        "period": {"from": start.isoformat(), "to": end.isoformat(), "days": (end - start).days + 1},
        "scope": scope,
        "population": {"total": len(ctx.members), "enrolled": enrolled,
                       "not_enrolled": len(ctx.members) - enrolled},
        "criteria": criteria,
        "criterion": key,
        "report": body,
    }


async def filter_options(db: AsyncSession, kind: str) -> dict:
    everyone = await population(db, kind)
    if kind == "talaba":
        names = await svc.faculty_names(db)
        faculties: Counter = Counter()
        groups: Counter = Counter()
        for m in everyone:
            fid = str(m.faculty_id) if m.faculty_id else NO_FACULTY
            faculties[fid] += 1
            course, group = student_course_group(m.raw)
            groups[(fid, course, group)] += 1
        return {
            "faculties": sorted(
                ({"id": fid, "name": names.get(uuid.UUID(fid), NO_FACULTY_LABEL) if fid != NO_FACULTY
                  else NO_FACULTY_LABEL, "count": n} for fid, n in faculties.items()),
                key=lambda r: (r["id"] == NO_FACULTY, svc.norm_name(r["name"]))),
            "groups": sorted(
                ({"faculty_id": fid, "course": course, "name": group, "count": n}
                 for (fid, course, group), n in groups.items() if group),
                key=lambda r: (r["course"] or 99, svc.norm_name(r["name"]))),
            "courses": sorted({c for (_f, c, _g) in groups if c}),
            "units": [],
            "unit_kinds": [],
        }
    catalog = await svc.unit_catalog(db)
    counts: Counter = Counter(catalog.unit_id(m.raw) for m in everyone)
    units = [{"id": u.id, "name": u.name, "kind": u.kind, "count": counts.get(u.id, 0)}
             for u in catalog.units.values() if counts.get(u.id)]
    return {"faculties": [], "groups": [], "courses": [], "units": units,
            "unit_kinds": [{"id": k, "label": v} for k, v in UNIT_KIND_LABELS.items()
                           if any(u["kind"] == k for u in units)]}
