# -*- coding: utf-8 -*-
"""Eski qoida va AI uzilishi qoldirgan noto'g'ri davomat belgilarini tuzatish.

MUAMMO 1 — "kech keldi". 2026-09-18 gacha 09:00 dan keyin ISTALGAN kamerada
birinchi marta ko'rilgan odam "kech keldi" deb yozilardi — xona kamerasida
ham. 16.09 da 38 kishidan 37 tasi, 17.09 da 23 tadan 21 tasi shunday
belgilangan. Hozirgi qoida (app/jobs/attendance_ai.first_sighting_status):
kechikish faqat KIRISH kamerasida ko'rinish bilan aniqlanadi; xona kamerasida
birinchi ko'rilgan odam "keldi", kelish vaqti esa noma'lum.

MUAMMO 2 — AI uzilishi. 2026-09-17 16:23 dan 2026-09-18 10:16 gacha AI hech
kimni tanimagan. Bunday kuni uzilish tugaganidan keyingi birinchi ko'rinish
kirish kamerasida bo'lsa ham kechikishni isbotlamaydi — odam ertalab kelgan
bo'lishi mumkin. Buni --kor-emas SANA=HH:MM bilan ko'rsatasiz.

MUAMMO 2b — siyrak kuzatuv. 2026-09-18 12:18 gacha kirish kameralari 25-80 s
da bir marta tekshirilardi, odam esa eshikdan 2-3 s da o'tadi: ko'pchilik
ertalab ko'rilmagan, "birinchi ko'rinish" esa ko'pincha ketish payti. Bunday
kunni --ishonchsiz-kun SANA bilan ko'rsatasiz — o'sha kungi barcha "kech
keldi" "keldi, vaqt noma'lum" bo'ladi. Shuningdek hozirgi qoida
(settings.attendance_late_window_end, standart 12:00): shundan keyingi
birinchi kirish ko'rinishi kechikish emas.

MUAMMO 3 — "kelmadi". 14.09 da 4 kishi tanilgan, 519 kishi "kelmadi" deb
yozilgan: bu odamlarning emas, kameralarning holati. Hozirgi absence_marker
tanilganlar ulushi ATTENDANCE_ABSENCE_MIN_COVERAGE dan past kuni "kelmadi"
yozmaydi. --kelmadi bilan shunday kunlardagi "kelmadi" yozuvlari o'chiriladi
(kun "ma'lumot yo'q" bo'lib qoladi). Ulush HOZIRGI ro'yxat bo'yicha
hisoblanadi — o'sha kungi ro'yxat saqlanmagan.

HIMOYA.
  * Qo'lda kiritilgan/tuzatilgan yozuvlarga tegilmaydi (audit jurnalidagi
    "Davomat qayd etdi: F.I.Sh. (SANA)" bo'yicha).
  * Tashrif ma'lumoti yo'q "kech keldi" yozuviga tegilmaydi — dalil yo'q.
  * Rostdan kech kelgan, lekin birinchi marta xonada ko'rilgan odam ham
    "keldi" bo'ladi: noto'g'ri ayblovdan ko'ra noma'lum vaqt yaxshi.
  * Standart — faqat ko'rsatish. --qollash bilan yoziladi; audit jurnaliga
    bitta umumiy yozuv qo'shiladi.

ISHGA TUSHIRISH (server, /opt/camera/camera-api):

    C="docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.mediamtx-shard.yml"
    sudo $C exec -T api python scripts/fix_attendance_marks.py \\
        --dan 2026-09-14 --gacha 2026-09-18 --kor-emas 2026-09-18=10:16 --kelmadi
    # natijani ko'rib chiqib, xuddi shu buyruqqa --qollash qo'shiladi

Qayta ishga tushirish xavfsiz: tuzatilgan yozuvlar ikkinchi marta topilmaydi.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, select, update  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import AttendanceRecord, AuditLog, Camera, PresenceVisit, StudentStaff  # noqa: E402
from app.timezone import INSTITUTE_TZ, to_local  # noqa: E402

PRESENT = ("keldi", "kech_keldi")
_MANUAL = re.compile(r"^Davomat qayd etdi: (?P<name>.+) \((?P<day>\d{4}-\d{2}-\d{2})\)$")


@dataclass
class LateFix:
    record_id: object
    person: str
    day: date
    check_in: time | None
    status: str  # yangi holat
    new_check_in: time | None
    reason: str


@dataclass
class AbsenceGroup:
    day: date
    person_type: str
    recognized: int
    enrolled: int
    record_ids: list = field(default_factory=list)


@dataclass
class Plan:
    late_fixes: list[LateFix] = field(default_factory=list)
    kept_late: list[tuple[str, date, str]] = field(default_factory=list)
    skipped: list[tuple[str, date, str]] = field(default_factory=list)
    absences: list[AbsenceGroup] = field(default_factory=list)


def late_cutoff() -> time:
    return time.fromisoformat(settings.attendance_ai_late_cutoff)


def late_window_end() -> time | None:
    value = settings.attendance_late_window_end.strip()
    return time.fromisoformat(value) if value else None


def judge_late(
    first_seen: time | None,
    at_entrance: bool | None,
    cutoff: time,
    blind_until: time | None,
    window_end: time | None = None,
    unreliable_day: bool = False,
) -> tuple[str, time | None, str] | None:
    """"kech keldi" yozuvini hozirgi qoidalar bilan baholaydi.

    None — yozuv to'g'ri, o'zgarmaydi. Aks holda (yangi holat, yangi kelish
    vaqti, sabab)."""
    if first_seen is None:
        return None
    if first_seen < cutoff:
        return "keldi", first_seen, f"birinchi ko'rinish {first_seen:%H:%M} — kechikish chegarasidan oldin"
    if unreliable_day:
        return "keldi", None, "kirish kameralari o'sha kuni siyrak tekshirilgan — kelish vaqti noma'lum"
    if window_end is not None and first_seen >= window_end:
        return (
            "keldi",
            None,
            f"birinchi ko'rinish {first_seen:%H:%M} — {window_end:%H:%M} dan keyin (odatda ketish payti), "
            "kelish vaqti noma'lum",
        )
    if blind_until is not None and first_seen >= blind_until:
        return "keldi", None, f"AI shu kuni {blind_until:%H:%M} gacha ishlamagan — kelish vaqti noma'lum"
    if not at_entrance:
        return "keldi", None, "birinchi marta xona kamerasida ko'rilgan — kelish vaqti noma'lum"
    return None


async def _manual_entries(db: AsyncSession) -> set[tuple[str, date]]:
    actions = await db.scalars(
        select(AuditLog.action).where(AuditLog.user_id.is_not(None), AuditLog.action.like("Davomat qayd etdi: %"))
    )
    entries: set[tuple[str, date]] = set()
    for action in actions:
        match = _MANUAL.match(action)
        if match:
            entries.add((match["name"], date.fromisoformat(match["day"])))
    return entries


def _local_midnight(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=INSTITUTE_TZ)


async def _first_sightings(db: AsyncSession, first: date, last: date) -> dict[tuple[str, date], tuple[time, bool]]:
    """(odam, mahalliy sana) -> (birinchi ko'rinish vaqti, kirish kamerasimi)."""
    rows = await db.execute(
        select(PresenceVisit.student_staff_id, PresenceVisit.first_seen_at, Camera.is_entrance)
        .outerjoin(Camera, Camera.id == PresenceVisit.camera_id)
        # Mahalliy kun chegarasi UTC'dan farq qiladi — bir kun keng olinadi.
        .where(PresenceVisit.first_seen_at >= _local_midnight(first) - timedelta(days=1))
        .where(PresenceVisit.first_seen_at < _local_midnight(last) + timedelta(days=2))
        .order_by(PresenceVisit.first_seen_at)
    )
    earliest: dict[tuple[str, date], tuple[time, bool]] = {}
    for person_id, seen_at, is_entrance in rows.all():
        local = to_local(seen_at)
        key = (str(person_id), local.date())
        if first <= local.date() <= last and key not in earliest:
            earliest[key] = (local.time().replace(microsecond=0), bool(is_entrance))
    return earliest


async def build_plan(
    db: AsyncSession,
    first: date,
    last: date,
    blind: dict[date, time],
    include_absences: bool,
    unreliable_days: frozenset[date] | set[date] = frozenset(),
) -> Plan:
    plan = Plan()
    manual = await _manual_entries(db)
    cutoff = late_cutoff()
    window_end = late_window_end()

    late_rows = (
        await db.execute(
            select(AttendanceRecord, StudentStaff.full_name)
            .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
            .where(AttendanceRecord.date.between(first, last))
            .where(AttendanceRecord.status == "kech_keldi")
            .order_by(AttendanceRecord.date, AttendanceRecord.check_in)
        )
    ).all()
    sightings = await _first_sightings(db, first, last) if late_rows else {}
    for record, name in late_rows:
        if (name, record.date) in manual:
            plan.skipped.append((name, record.date, "qo'lda kiritilgan"))
            continue
        seen = sightings.get((str(record.student_staff_id), record.date))
        if seen is None:
            plan.skipped.append((name, record.date, "tashrif ma'lumoti yo'q — dalil yo'q"))
            continue
        verdict = judge_late(
            seen[0], seen[1], cutoff, blind.get(record.date), window_end, record.date in unreliable_days
        )
        if verdict is None:
            plan.kept_late.append((name, record.date, f"kirishda {seen[0]:%H:%M} da ko'rilgan"))
            continue
        status, new_check_in, reason = verdict
        plan.late_fixes.append(
            LateFix(record.id, name, record.date, record.check_in, status, new_check_in, reason)
        )

    if include_absences:
        enrolled = (
            await db.execute(
                select(StudentStaff.id, StudentStaff.type).where(StudentStaff.biometrics_status == "tasdiqlangan")
            )
        ).all()
        by_type: dict[str, set[str]] = {}
        for person_id, person_type in enrolled:
            by_type.setdefault(person_type, set()).add(str(person_id))
        rows = (
            await db.execute(
                select(AttendanceRecord, StudentStaff.full_name, StudentStaff.type)
                .join(StudentStaff, StudentStaff.id == AttendanceRecord.student_staff_id)
                .where(AttendanceRecord.date.between(first, last))
            )
        ).all()
        groups: dict[tuple[date, str], AbsenceGroup] = {}
        for record, name, person_type in rows:
            people = by_type.get(person_type, set())
            group = groups.setdefault(
                (record.date, person_type), AbsenceGroup(record.date, person_type, 0, len(people))
            )
            if record.status in PRESENT and str(record.student_staff_id) in people:
                group.recognized += 1
            elif record.status == "kelmadi" and (name, record.date) not in manual:
                group.record_ids.append(record.id)
        for group in sorted(groups.values(), key=lambda g: (g.day, g.person_type)):
            coverage = group.recognized / group.enrolled if group.enrolled else 0.0
            if group.record_ids and coverage < settings.attendance_absence_min_coverage:
                plan.absences.append(group)
    return plan


async def apply_plan(
    db: AsyncSession, plan: Plan, blind: dict[date, time], unreliable_days: frozenset[date] | set[date] = frozenset()
) -> None:
    for fix in plan.late_fixes:
        await db.execute(
            update(AttendanceRecord)
            .where(AttendanceRecord.id == fix.record_id, AttendanceRecord.status == "kech_keldi")
            .values(status=fix.status, check_in=fix.new_check_in)
        )
    removed = 0
    for group in plan.absences:
        result = await db.execute(
            delete(AttendanceRecord).where(
                AttendanceRecord.id.in_(group.record_ids), AttendanceRecord.status == "kelmadi"
            )
        )
        removed += result.rowcount or 0
    days = sorted({fix.day for fix in plan.late_fixes} | {group.day for group in plan.absences})
    outage = ", ".join(f"{day} {until:%H:%M} gacha" for day, until in sorted(blind.items()))
    sparse = ", ".join(day.isoformat() for day in sorted(unreliable_days))
    db.add(
        AuditLog(
            user_id=None,
            user_name="Tizim skripti",
            action=(
                f"Davomat qayta baholandi ({', '.join(d.isoformat() for d in days)}): "
                f"{len(plan.late_fixes)} ta \"kech keldi\" -> \"keldi\", "
                f"{removed} ta ishonchsiz \"kelmadi\" o'chirildi"
                + (f"; AI ishlamagan: {outage}" if outage else "")
                + (f"; kuzatuv siyrak: {sparse}" if sparse else "")
            ),
            module="Talabalar",
            status="muvaffaqiyatli",
            ip="internal",
        )
    )
    await db.commit()


def print_plan(plan: Plan) -> None:
    if plan.late_fixes:
        print(f"\"kech keldi\" -> \"keldi\": {len(plan.late_fixes)} ta")
        for fix in plan.late_fixes:
            was = fix.check_in.strftime("%H:%M") if fix.check_in else "—"
            now = fix.new_check_in.strftime("%H:%M") if fix.new_check_in else "noma'lum"
            print(f"  {fix.day}  {fix.person}: kelish {was} -> {now} ({fix.reason})")
    else:
        print("\"kech keldi\" dan tuzatiladigan yozuv yo'q")
    if plan.kept_late:
        print(f"\nO'z holicha qoladi (haqiqatan kirishda kech ko'rilgan): {len(plan.kept_late)} ta")
        for name, day, reason in plan.kept_late:
            print(f"  {day}  {name}: {reason}")
    if plan.skipped:
        print(f"\nTegilmaydi: {len(plan.skipped)} ta")
        for name, day, reason in plan.skipped:
            print(f"  {day}  {name}: {reason}")
    if plan.absences:
        print("\nIshonchsiz \"kelmadi\" (kameralar o'sha kuni odamlarning ozgina qismini tanigan):")
        for group in plan.absences:
            print(
                f"  {group.day}  {group.person_type}: tanilgan {group.recognized}/{group.enrolled} — "
                f"{len(group.record_ids)} ta \"kelmadi\" o'chiriladi"
            )


def _blind_arg(value: str) -> tuple[date, time]:
    try:
        day, until = value.split("=", 1)
        return date.fromisoformat(day), time.fromisoformat(until)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("format: SANA=HH:MM, masalan 2026-09-18=10:16") from exc


async def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Noto'g'ri davomat belgilarini hozirgi qoidalar bilan tuzatish")
    parser.add_argument("--dan", type=date.fromisoformat, required=True, help="birinchi sana (YYYY-MM-DD)")
    parser.add_argument("--gacha", type=date.fromisoformat, help="oxirgi sana (standart: --dan)")
    parser.add_argument("--kor-emas", type=_blind_arg, action="append", default=[], metavar="SANA=HH:MM",
                        help="shu kuni AI shu vaqtgacha ishlamagan (bir necha marta berish mumkin)")
    parser.add_argument("--ishonchsiz-kun", type=date.fromisoformat, action="append", default=[], metavar="SANA",
                        help="shu kuni kirish kameralari siyrak tekshirilgan: barcha \"kech keldi\" -> \"keldi\"")
    parser.add_argument("--kelmadi", action="store_true", help="past qamrovli kunlardagi \"kelmadi\" ni ham tozalash")
    parser.add_argument("--qollash", action="store_true", help="o'zgarishlarni yozish (standart: faqat ko'rsatish)")
    args = parser.parse_args(argv)
    last = args.gacha or args.dan
    if last < args.dan:
        parser.error("--gacha --dan dan oldin bo'lishi mumkin emas")
    blind = dict(args.kor_emas)
    unreliable = frozenset(args.ishonchsiz_kun)

    async with SessionLocal() as db:
        plan = await build_plan(db, args.dan, last, blind, args.kelmadi, unreliable)
        print_plan(plan)
        if not plan.late_fixes and not plan.absences:
            return 0
        if not args.qollash:
            print("\nHech narsa yozilmadi. Qo'llash uchun xuddi shu buyruqqa --qollash qo'shing.")
            return 0
        await apply_plan(db, plan, blind, unreliable)
    print("\nYozildi. Audit jurnaliga qayd qilindi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
