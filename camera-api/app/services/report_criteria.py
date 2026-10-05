"""Hisobot kriteriyalari: karta raqamlari, ro'yxatlar va odam kesimi.

UCH DARAJA. Sahifa "umumiy raqam -> kim -> isbot" yo'lidan boradi:

  1. build_criteria()  — har kriteriya uchun karta: nechta odam keldi,
     kechikdi, kelmadi, nechtasi kamerada umuman ko'rinmadi va h.k.
  2. people_for()      — kartaning bitta raqami ortidagi odamlar ro'yxati.
  3. person_detail()   — bitta odamning davr bo'yicha kesimi; kun bosilsa
     o'sha kunning kamera tashriflari presence endpointidan olinadi.

HALOLLIK QOIDASI. Raqam nolga teng bo'lishining ikki xil sababi bor:
hech kim kelmagani yoki TIZIM QARAMAGANI. Ikkinchisi — masalan talabalar
davomati moduli o'chirilgan yoki yuzlar ro'yxatga kiritilmagan — har
kartada `note` bilan aytiladi, aks holda hisobot yolg'on xulosa beradi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type, datetime, time, timedelta, timezone

from sqlalchemy import case, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AIModuleConfig,
    AttendanceRecord,
    Building,
    Camera,
    DailyPersonCriteria,
    Event,
    LessonAttendance,
    LessonSession,
    PresenceVisit,
    StudentStaff,
)
from app.schemas.report_criteria import (
    ReportBucketOut,
    ReportCriteriaOut,
    ReportCriterionOut,
    ReportPeriodOut,
    ReportPersonDayOut,
    ReportPersonDetailOut,
    ReportPersonRowOut,
)
from app.services.event_status import fold_review_counts
from app.storage import presigned_url
from app.timezone import INSTITUTE_TZ, UZ_WEEKDAYS, local_now
from app.utils import compute_initials
from app.timezone import business_date, business_today, day_start

PRESENT = ("keldi", "kech_keldi")
POPULATION_LABELS = {"xodim": "O'qituvchilar va xodimlar", "talaba": "Talabalar"}

# Davr tugmalari — sahifadagi "Bugun / Kecha / Hafta / Oylik".
PERIOD_LABELS = {"bugun": "Bugun", "kecha": "Kecha", "hafta": "Hafta", "oy": "Shu oy"}

STAFF_ATTENDANCE_CODE = 6
STUDENT_ATTENDANCE_CODE = 7
COAT_CODE = 10
SMOKING_CODE = 15
# 2026-10-04: #26 (o'qituvchi o'rniga boshqasi) olib tashlandi — xonada
# ko'ringan boshqa xodim #22 hodisasining tafsilotida aytiladi.
PUNCTUALITY_CODES = (22,)


@dataclass(frozen=True)
class Period:
    key: str
    label: str
    start: date_type
    end: date_type

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def out(self) -> ReportPeriodOut:
        return ReportPeriodOut(
            key=self.key,
            label=self.label,
            start=self.start.isoformat(),
            end=self.end.isoformat(),
            days=self.days,
        )

    def bounds_utc(self) -> tuple[datetime, datetime]:
        """Mahalliy kun chegaralari UTC'da — tashriflar timestamp bo'yicha."""
        start = day_start(self.start)
        # Ish kuni ertasi 06:00 gacha: 00:00–05:59 dagi kuzatuvlar ham shu davrniki.
        end = day_start(self.end + timedelta(days=1)) - timedelta(microseconds=1)
        return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _working_days(period: Period) -> int:
    """Davrdagi ish kunlari (bugungacha): yakshanba va bayramlar kirmaydi."""
    from app.services.attendance_policy import current_policy

    policy = current_policy()
    last = min(period.end, business_today())
    days = (last - period.start).days + 1
    return sum(1 for i in range(max(0, days)) if policy.is_work_day(period.start + timedelta(days=i)))


def resolve_period(key: str) -> Period:
    today = business_today()
    if key == "kecha":
        day = today - timedelta(days=1)
        return Period("kecha", PERIOD_LABELS["kecha"], day, day)
    if key == "hafta":
        return Period("hafta", PERIOD_LABELS["hafta"], today - timedelta(days=6), today)
    if key == "oy":
        return Period("oy", PERIOD_LABELS["oy"], today.replace(day=1), today)
    return Period("bugun", PERIOD_LABELS["bugun"], today, today)


def _hm(value) -> str | None:
    return value.strftime("%H:%M") if value else None


def _tone_for_status(status: str) -> str:
    return {"keldi": "green", "kech_keldi": "amber", "kelmadi": "red"}.get(status, "slate")


async def _module_active(db: AsyncSession, code: int) -> bool:
    value = await db.scalar(select(AIModuleConfig.active).where(AIModuleConfig.code == code))
    return bool(value)


async def _attendance_counts(db: AsyncSession, population: str, period: Period) -> dict[str, int]:
    rows = (
        await db.execute(
            select(AttendanceRecord.status, func.count())
            .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
            .where(StudentStaff.type == population, StudentStaff.active.is_(True))
            .where(AttendanceRecord.date.between(period.start, period.end))
            .group_by(AttendanceRecord.status)
        )
    ).all()
    return {status: count for status, count in rows}


async def _seen_people(db: AsyncSession, population: str, period: Period) -> int:
    start, end = period.bounds_utc()
    return (
        await db.scalar(
            select(func.count(func.distinct(PresenceVisit.student_staff_id)))
            .join(StudentStaff, StudentStaff.id == PresenceVisit.student_staff_id)
            .where(StudentStaff.type == population, StudentStaff.active.is_(True))
            # "Ko'rindi" + "Ko'rinmadi" = ro'yxatdan o'tganlar (ro'yxat bilan bir xil to'plam).
            .where(StudentStaff.biometrics_status == "tasdiqlangan")
            .where(PresenceVisit.first_seen_at.between(start, end))
        )
    ) or 0


async def _people_counts(db: AsyncSession, population: str) -> tuple[int, int]:
    total = (
        await db.scalar(select(func.count()).select_from(StudentStaff).where(StudentStaff.type == population, StudentStaff.active.is_(True)))
    ) or 0
    enrolled = (
        await db.scalar(
            select(func.count())
            .select_from(StudentStaff)
            .where(StudentStaff.type == population, StudentStaff.active.is_(True))
            .where(StudentStaff.biometrics_status == "tasdiqlangan")
        )
    ) or 0
    return total, enrolled


async def _event_counts(
    db: AsyncSession, codes: tuple[int, ...], period: Period, *, include_trial: bool = False
) -> dict[str, int]:
    start, end = period.bounds_utc()
    trial_filter = true() if include_trial else Event.is_trial.is_(False)
    rows = (
        await db.execute(
            select(Event.status, func.count())
            .where(trial_filter)
            .where(Event.module_code.in_(codes))
            .where(Event.occurred_at.between(start, end))
            .group_by(Event.status)
        )
    ).all()
    # Uch toifa: jarayonda -> ko'rilmagan, hal_qilindi -> tasdiqlangan.
    return fold_review_counts({status: count for status, count in rows})


async def _lesson_counts(db: AsyncSession, period: Period) -> dict[str, int]:
    rows = (
        await db.execute(
            select(LessonAttendance.status, func.count())
            .join(LessonSession, LessonSession.id == LessonAttendance.lesson_session_id)
            .where(LessonSession.date.between(period.start, period.end))
            .group_by(LessonAttendance.status)
        )
    ).all()
    return {status or "baholanmagan": count for status, count in rows}


async def _coat_counts(db: AsyncSession, population: str, period: Period) -> dict[str, int]:
    """Oq xalat (#10) — kunlik video tahlil natijasi: odam-kunlar holati."""
    rows = (
        await db.execute(
            select(DailyPersonCriteria.coat_status, func.count())
            .join(StudentStaff, StudentStaff.id == DailyPersonCriteria.student_staff_id)
            .where(StudentStaff.type == population)
            .where(DailyPersonCriteria.day.between(period.start, period.end))
            .where(DailyPersonCriteria.coat_status.in_(("kiygan", "kiymagan", "aniqlanmadi")))
            .group_by(DailyPersonCriteria.coat_status)
        )
    ).all()
    return {status: count for status, count in rows}


async def _attention_counts(db: AsyncSession, period: Period) -> dict[str, int]:
    """Diqqat (#19) — talaba-darslar balli bo'yicha: yaxshi / o'rta / past."""
    score = LessonAttendance.attention_score
    bucket = case((score >= 75, "yaxshi"), (score >= 60, "orta"), else_="past")
    rows = (
        await db.execute(
            select(bucket, func.count())
            .join(LessonSession, LessonSession.id == LessonAttendance.lesson_session_id)
            .where(LessonSession.date.between(period.start, period.end))
            .where(score.is_not(None))
            .group_by(bucket)
        )
    ).all()
    return {key: count for key, count in rows}


def _coat_criterion(counts: dict[str, int]) -> ReportCriterionOut:
    total = sum(counts.values())
    return ReportCriterionOut(
        key="forma",
        title="Oq xalat",
        subtitle="Kun bo'yi kuzatuvlar bo'yicha: oq xalatda yurgan yoki yurmagan (odam-kunlar)",
        total=total,
        unit="odam-kun",
        detail="none",
        module_codes=[COAT_CODE],
        note=None if total else "Bu davrda kunlik video tahlil oq xalat bo'yicha natija bermadi.",
        buckets=[
            ReportBucketOut(key="kiygan", label="Kiygan", count=counts.get("kiygan", 0), tone="green"),
            ReportBucketOut(key="kiymagan", label="Kiymagan", count=counts.get("kiymagan", 0), tone="red"),
            ReportBucketOut(key="aniqlanmadi", label="Aniqlanmadi", count=counts.get("aniqlanmadi", 0), tone="slate"),
        ],
    )


def _smoking_criterion(counts: dict[str, int]) -> ReportCriterionOut:
    criterion = _events_criterion(
        "chekish",
        "Chekish",
        "Hovli va koridorlarda qo'lni og'izga takror ko'tarish — operator tasdiqlaydi",
        (SMOKING_CODE,),
        counts,
        None if sum(counts.values()) else "Bu davrda bunday holat qayd etilmadi.",
    )
    return criterion


def _events_criterion(
    key: str, title: str, subtitle: str, codes: tuple[int, ...], counts: dict[str, int], note: str | None
) -> ReportCriterionOut:
    total = sum(counts.values())
    return ReportCriterionOut(
        key=key,
        title=title,
        subtitle=subtitle,
        total=total,
        unit="signal",
        detail="events",
        module_codes=list(codes),
        note=note,
        buckets=[
            ReportBucketOut(key="yangi", label="Ko'rilmagan", count=counts.get("yangi", 0), tone="amber"),
            ReportBucketOut(
                key="tasdiqlangan", label="Tasdiqlangan", count=counts.get("tasdiqlangan", 0), tone="red"
            ),
            ReportBucketOut(
                key="rad_etilgan", label="Rad etilgan", count=counts.get("rad_etilgan", 0), tone="slate"
            ),
        ],
    )


async def build_criteria(db: AsyncSession, population: str, period: Period) -> ReportCriteriaOut:
    total_people, enrolled = await _people_counts(db, population)
    attendance = await _attendance_counts(db, population, period)
    seen = await _seen_people(db, population, period)

    attendance_code = STAFF_ATTENDANCE_CODE if population == "xodim" else STUDENT_ATTENDANCE_CODE
    attendance_on = await _module_active(db, attendance_code)
    attendance_note: str | None = None
    if not attendance_on:
        attendance_note = (
            "Bu populyatsiya uchun davomat moduli o'chirilgan — raqamlar yangilanmaydi."
        )
    elif enrolled == 0:
        attendance_note = "Hech kimning yuzi ro'yxatga kiritilmagan, shuning uchun kamera hech kimni taniy olmaydi."
    elif sum(attendance.values()) == 0:
        attendance_note = "Bu davrda birorta davomat yozuvi yo'q."

    criteria: list[ReportCriterionOut] = [
        ReportCriterionOut(
            key="davomat",
            title="Davomat",
            subtitle="Kelgan, kechikkan va kelmagan kun-yozuvlari",
            total=sum(attendance.values()),
            unit="kun-yozuv",
            note=attendance_note,
            buckets=[
                ReportBucketOut(key="keldi", label="Keldi", count=attendance.get("keldi", 0), tone="green"),
                ReportBucketOut(
                    key="kech_keldi", label="Kechikdi", count=attendance.get("kech_keldi", 0), tone="amber"
                ),
                ReportBucketOut(key="kelmadi", label="Kelmadi", count=attendance.get("kelmadi", 0), tone="red"),
            ],
        ),
        ReportCriterionOut(
            key="korinish",
            title="Kamerada ko'rinish",
            subtitle="Ro'yxatdan o'tganlardan nechtasini kamera shu davrda tanidi",
            total=enrolled,
            unit="odam",
            note=(
                "Ro'yxatdan o'tganlar yo'q — kamera hech kimni taniy olmaydi."
                if enrolled == 0
                else None
            ),
            buckets=[
                ReportBucketOut(key="korindi", label="Ko'rindi", count=seen, tone="green"),
                ReportBucketOut(
                    key="korinmadi", label="Ko'rinmadi", count=max(0, enrolled - seen), tone="slate"
                ),
            ],
        ),
        ReportCriterionOut(
            key="biometrika",
            title="Ro'yxatdan o'tish",
            subtitle="Yuzi tasdiqlanganlar — davomat faqat shular uchun ishlaydi (hozirgi holat)",
            total=total_people,
            unit="odam",
            buckets=[
                ReportBucketOut(key="tasdiqlangan", label="Tasdiqlangan", count=enrolled, tone="green"),
                ReportBucketOut(
                    key="tasdiqlanmagan",
                    label="Tasdiqlanmagan",
                    count=max(0, total_people - enrolled),
                    tone="red",
                ),
            ],
        ),
    ]

    if population == "xodim":
        punctuality = await _event_counts(db, PUNCTUALITY_CODES, period)
        lessons_exist = (
            await db.scalar(
                select(func.count())
                .select_from(LessonSession)
                .where(LessonSession.date.between(period.start, period.end))
            )
        ) or 0
        criteria.append(
            _events_criterion(
                "dars_intizomi",
                "Dars intizomi",
                "O'qituvchi darsga kechikkan yoki kelmagan holatlar",
                PUNCTUALITY_CODES,
                punctuality,
                None if lessons_exist else "Bu davrga dars jadvali kiritilmagan — tekshirish ishlamaydi.",
            )
        )
    else:
        lessons = await _lesson_counts(db, period)
        lesson_total = sum(lessons.values())
        criteria.append(
            ReportCriterionOut(
                key="dars_davomati",
                title="Darsga qatnashish",
                subtitle="Dars kesimidagi davomat (kunlik davomatdan alohida)",
                total=lesson_total,
                unit="dars-yozuv",
                detail="none",
                note=None if lesson_total else "Dars jadvali kiritilmagan — dars davomati yig'ilmaydi.",
                buckets=[
                    ReportBucketOut(key="keldi", label="Qatnashdi", count=lessons.get("keldi", 0), tone="green"),
                    ReportBucketOut(
                        key="kech_keldi", label="Kechikdi", count=lessons.get("kech_keldi", 0), tone="amber"
                    ),
                    ReportBucketOut(
                        key="kelmadi", label="Qatnashmadi", count=lessons.get("kelmadi", 0), tone="red"
                    ),
                ],
            )
        )
        attention = await _attention_counts(db, period)
        attention_total = sum(attention.values())
        criteria.append(
            ReportCriterionOut(
                key="diqqat",
                title="Darsda diqqat",
                subtitle="Har talaba-dars bo'yicha diqqat balli: yuz yo'nalishi va telefon",
                total=attention_total,
                unit="dars-yozuv",
                detail="none",
                module_codes=[19],
                note=None if attention_total else "Bu davrda diqqat o'lchangan dars yo'q.",
                buckets=[
                    ReportBucketOut(key="yaxshi", label="Yaxshi (75+)", count=attention.get("yaxshi", 0), tone="green"),
                    ReportBucketOut(key="orta", label="O'rta (60–74)", count=attention.get("orta", 0), tone="amber"),
                    ReportBucketOut(key="past", label="Past (<60)", count=attention.get("past", 0), tone="red"),
                ],
            )
        )

    criteria.append(_coat_criterion(await _coat_counts(db, population, period)))
    criteria.append(_smoking_criterion(await _event_counts(db, (SMOKING_CODE,), period, include_trial=True)))

    return ReportCriteriaOut(
        population=population,
        population_label=POPULATION_LABELS.get(population, population),
        period=period.out(),
        people_total=total_people,
        enrolled_total=enrolled,
        criteria=criteria,
    )


def _people_base(population: str):
    """To'liq StudentStaff obyekti tanlanadi — sahifalash yordamchisi
    (app/pagination.py) ustunlar ro'yxatini emas, obyektlarni qaytaradi."""
    return (
        select(StudentStaff)
        .options(selectinload(StudentStaff.faculty))
        .where(StudentStaff.type == population, StudentStaff.active.is_(True))
    )


async def _attendance_people_ids(db: AsyncSession, population: str, period: Period, bucket: str) -> list:
    stmt = (
        select(AttendanceRecord.student_staff_id)
        .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
        .where(StudentStaff.type == population, StudentStaff.active.is_(True))
        .where(AttendanceRecord.date.between(period.start, period.end))
    )
    if bucket in ("keldi", "kech_keldi", "kelmadi"):
        stmt = stmt.where(AttendanceRecord.status == bucket)
    return list((await db.execute(stmt.distinct())).scalars().all())


async def _visit_people_ids(db: AsyncSession, population: str, period: Period) -> list:
    start, end = period.bounds_utc()
    stmt = (
        select(PresenceVisit.student_staff_id)
        .join(StudentStaff, StudentStaff.id == PresenceVisit.student_staff_id)
        .where(StudentStaff.type == population, StudentStaff.active.is_(True))
        .where(StudentStaff.biometrics_status == "tasdiqlangan")
        .where(PresenceVisit.first_seen_at.between(start, end))
        .distinct()
    )
    return list((await db.execute(stmt)).scalars().all())


async def people_query(db: AsyncSession, population: str, criterion: str, bucket: str, period: Period):
    """Kriteriya va "chelak" bo'yicha odamlar so'rovi (sahifalash uchun)."""
    stmt = _people_base(population)

    if criterion == "davomat":
        ids = await _attendance_people_ids(db, population, period, bucket)
        stmt = stmt.where(StudentStaff.id.in_(ids)) if ids else stmt.where(False)
    elif criterion == "korinish":
        seen_ids = await _visit_people_ids(db, population, period)
        if bucket == "korinmadi":
            stmt = stmt.where(StudentStaff.biometrics_status == "tasdiqlangan")
            if seen_ids:
                stmt = stmt.where(StudentStaff.id.not_in(seen_ids))
        else:
            stmt = stmt.where(StudentStaff.id.in_(seen_ids)) if seen_ids else stmt.where(False)
    elif criterion == "biometrika":
        if bucket == "tasdiqlanmagan":
            stmt = stmt.where(StudentStaff.biometrics_status != "tasdiqlangan")
        else:
            stmt = stmt.where(StudentStaff.biometrics_status == "tasdiqlangan")
    else:
        stmt = stmt.where(False)

    return stmt.order_by(StudentStaff.full_name)


async def decorate_people(
    db: AsyncSession, people: list[StudentStaff], period: Period
) -> list[ReportPersonRowOut]:
    """Ro'yxat qatorlariga davomat va tashrif raqamlarini qo'shadi.

    Uch qo'shimcha so'rov — faqat SHU SAHIFADAGI odamlar uchun, ya'ni
    ro'yxat qancha uzun bo'lsa ham so'rovlar soni o'zgarmaydi."""
    ids = [person.id for person in people]
    if not ids:
        return []

    attendance = {
        person_id: (present, late, absent, first_in, last_out)
        for person_id, present, late, absent, first_in, last_out in (
            await db.execute(
                select(
                    AttendanceRecord.student_staff_id,
                    func.count().filter(AttendanceRecord.status.in_(PRESENT)),
                    func.count().filter(AttendanceRecord.status == "kech_keldi"),
                    func.count().filter(AttendanceRecord.status == "kelmadi"),
                    func.min(AttendanceRecord.check_in),
                    func.max(AttendanceRecord.check_out),
                )
                .where(AttendanceRecord.student_staff_id.in_(ids))
                .where(AttendanceRecord.date.between(period.start, period.end))
                .group_by(AttendanceRecord.student_staff_id)
            )
        ).all()
    }

    start, end = period.bounds_utc()
    visits = {
        person_id: (count, cameras, last_seen)
        for person_id, count, cameras, last_seen in (
            await db.execute(
                select(
                    PresenceVisit.student_staff_id,
                    func.count(),
                    func.count(func.distinct(PresenceVisit.camera_id)),
                    func.max(PresenceVisit.last_seen_at),
                )
                .where(PresenceVisit.student_staff_id.in_(ids))
                .where(PresenceVisit.first_seen_at.between(start, end))
                .group_by(PresenceVisit.student_staff_id)
            )
        ).all()
    }

    # Oxirgi ko'rilgan kamera nomi — "isbot bor" degan belgi.
    last_cameras: dict = {}
    for person_id, camera_name, seen_at in (
        await db.execute(
            select(PresenceVisit.student_staff_id, Camera.name, PresenceVisit.last_seen_at)
            .join(Camera, Camera.id == PresenceVisit.camera_id)
            .where(PresenceVisit.student_staff_id.in_(ids))
            .where(PresenceVisit.first_seen_at.between(start, end))
            .order_by(PresenceVisit.last_seen_at.desc())
        )
    ).all():
        last_cameras.setdefault(person_id, camera_name)

    out: list[ReportPersonRowOut] = []
    for person in people:
        present, late, absent, first_in, last_out = attendance.get(person.id, (0, 0, 0, None, None))
        visit_count, camera_count, last_seen = visits.get(person.id, (0, 0, None))
        out.append(
            ReportPersonRowOut(
                id=str(person.id),
                full_name=person.full_name,
                initials=compute_initials(person.full_name),
                photo_url=presigned_url(person.biometric_photo_key) if person.biometric_photo_key else None,
                faculty=person.faculty.name if person.faculty else "Fakultetsiz",
                unit=person.group_or_position,
                biometrics_status=person.biometrics_status,
                present_days=present,
                late_days=late,
                absent_days=absent,
                first_check_in=_hm(first_in),
                last_check_out=_hm(last_out),
                visits=visit_count,
                cameras=camera_count,
                last_seen_at=last_seen.isoformat() if last_seen else None,
                last_seen_camera=last_cameras.get(person.id),
            )
        )
    return out


async def person_detail(db: AsyncSession, person: StudentStaff, period: Period) -> ReportPersonDetailOut:
    records = {
        row.date: row
        for row in (
            await db.execute(
                select(AttendanceRecord)
                .where(AttendanceRecord.student_staff_id == person.id)
                .where(AttendanceRecord.date.between(period.start, period.end))
            )
        ).scalars().all()
    }

    start, end = period.bounds_utc()
    visits = (
        await db.execute(
            select(PresenceVisit)
            .where(PresenceVisit.student_staff_id == person.id)
            .where(PresenceVisit.first_seen_at.between(start, end))
            .order_by(PresenceVisit.first_seen_at)
        )
    ).scalars().all()

    # Kamera nomlari va binolar bitta so'rovda — tashrif ro'yxati
    # "qayerda ko'rilgan" degan isbotni shu ikkisidan quradi.
    camera_names: dict = {}
    building_names: list[str] = []
    camera_ids = {visit.camera_id for visit in visits if visit.camera_id}
    if camera_ids:
        for camera_id, camera_name, building_name in (
            await db.execute(
                select(Camera.id, Camera.name, Building.name)
                .outerjoin(Building, Building.id == Camera.building_id)
                .where(Camera.id.in_(camera_ids))
            )
        ).all():
            camera_names[camera_id] = camera_name
            if building_name and building_name not in building_names:
                building_names.append(building_name)

    per_day: list[ReportPersonDayOut] = []
    day = period.start
    while day <= period.end:
        record = records.get(day)
        day_visits = [
            visit
            for visit in visits
            if business_date(visit.first_seen_at) == day
        ]
        per_day.append(
            ReportPersonDayOut(
                date=day.isoformat(),
                weekday=UZ_WEEKDAYS[day.weekday()],
                status=record.status if record else None,
                check_in=_hm(record.check_in) if record else None,
                check_out=_hm(record.check_out) if record else None,
                visits=len(day_visits),
                first_camera=camera_names.get(day_visits[0].camera_id) if day_visits else None,
            )
        )
        day += timedelta(days=1)

    present = sum(1 for row in records.values() if row.status in PRESENT)
    late = sum(1 for row in records.values() if row.status == "kech_keldi")
    absent = sum(1 for row in records.values() if row.status == "kelmadi")
    check_ins = [row.check_in for row in records.values() if row.check_in]
    check_outs = [row.check_out for row in records.values() if row.check_out]

    note = None
    if person.biometrics_status != "tasdiqlangan":
        note = "Yuzi ro'yxatga kiritilmagan — kamera bu odamni tanimaydi, davomat ham yozilmaydi."
    elif not visits and not records:
        note = "Bu davrda kamera bu odamni umuman ko'rmagan."

    return ReportPersonDetailOut(
        id=str(person.id),
        full_name=person.full_name,
        initials=compute_initials(person.full_name),
        type=person.type,
        photo_url=presigned_url(person.biometric_photo_key) if person.biometric_photo_key else None,
        faculty=person.faculty.name if person.faculty else "Fakultetsiz",
        unit=person.group_or_position,
        biometrics_status=person.biometrics_status,
        biometrics_confirmed_label=(
            person.biometrics_confirmed_at.astimezone(INSTITUTE_TZ).strftime("%d.%m.%Y %H:%M")
            if person.biometrics_confirmed_at
            else None
        ),
        period=period.out(),
        present_days=present,
        late_days=late,
        absent_days=absent,
        working_days=_working_days(period),
        visits=len(visits),
        cameras=len({visit.camera_id for visit in visits}),
        buildings=building_names,
        first_check_in=_hm(min(check_ins)) if check_ins else None,
        last_check_out=_hm(max(check_outs)) if check_outs else None,
        days=per_day,
        note=note,
    )
