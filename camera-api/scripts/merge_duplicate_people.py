# -*- coding: utf-8 -*-
"""Bir odamning ikki yozuvini birlashtirish.

MUAMMO. Xodimlar ro'yxati import qilingandan keyin ba'zi xodimlar admin
panelidagi "Yangi biriktirish" orqali QAYTA qo'shilgan va yuzi o'sha yangi
yozuvda tasdiqlangan. Natijada bitta odamning ikki yozuvi bor:

    import qilingan  — JSHSHIR va aniq kafedra bor
    qo'lda qo'shilgan — JSHSHIR yo'q, lavozim yozilgan, yuzi TASDIQLANGAN

Hisobotlarda bu odam ikki marta sanaladi; JSHSHIR bilan qidirilganda esa
qo'lda qo'shilgan (yuzi bor) yozuv topilmaydi. Yangi dublikatlarning oldi
admin panelning o'zida olingan (students_staff.create — o'xshash ism
tekshiruvi); bu skript mavjudlarini tozalaydi.

UCH REJIM.

  1. ANIQ juftliklar (standart). Turi bir xil, to'liq ismi bir xil
     (katta-kichik harf, bo'shliq, ‘ ’ ` ʻ farqi hisobga olinmaydi), import
     nusxasining yuzi tasdiqlanmagan.

  2. NOANIQ juftliklar (faqat --qisman bilan). Ism boshqacha yozilgan —
     qoidasi app/services/name_matching.py da. Shu jumladan IKKALA yozuv
     ham tasdiqlangan holat (rasmiy JSHSHIRli yozuv qoladi). Faqat BIRGA-BIR
     juftliklar olinadi; o'z turidagi nomzod bo'lsa, boshqa turdagisi
     e'tiborga olinmaydi.

  3. QO'LDA ko'rsatilgan juftlik (--juftlik SAQLANADI O'CHIRILADI). Hisobot
     "qo'lda hal qiling" deb ko'rsatgan holatlar uchun — yozuv ID'sining
     boshidagi 8 belgi yetarli. Saqlanadigan yozuvda JSHSHIR bo'lmasa,
     o'chiriladigandan ko'chiriladi.

NIMA QILADI. Har bir juftlik uchun: saqlanadigan yozuvning identifikatori
va yuzi o'zgarmaydi; unga JSHSHIR, fakultet, kafedra, rasmiy ism va pasport
ko'chiriladi (kerak bo'lsa); o'chiriladigan yozuvning davomati, dars
davomati va dars jadvalidagi o'qituvchi bog'lanishi o'tkaziladi (bir kun
yoki dars uchun ikkalasida bo'lsa — saqlanadigandagisi qoladi); ikkinchi
yozuv o'chiriladi va audit jurnaliga yoziladi.

ISHGA TUSHIRISH (server, /opt/camera/camera-api):

    docker compose cp scripts/merge_duplicate_people.py api:/app/scripts/merge_duplicate_people.py
    docker compose exec -T api python scripts/merge_duplicate_people.py --qisman --dry-run
    docker compose exec -T api python scripts/merge_duplicate_people.py --qisman
    docker compose exec -T api python scripts/merge_duplicate_people.py --juftlik 1a2b3c4d 5e6f7a8b --dry-run

Qayta ishga tushirish xavfsiz: birlashtirilganlar ikkinchi marta topilmaydi.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import SessionLocal
from app.models import AttendanceRecord, AuditLog, Faculty, LessonAttendance, LessonSession, StudentStaff
from app.services.face_matching import announce_roster_change
from app.services.name_matching import name_key, name_tokens, names_match  # noqa: F401  (testlar ham shu yerdan oladi)
from app.timezone import to_local

AUDIT_USER = "Dublikatlarni birlashtirish"
RESTART_HINT = (
    "\nMUHIM: yuz vektori bor yozuvlar o'chirildi. AI tanish ro'yxatini 5 daqiqagacha xotirada\n"
    "saqlaydi — API'ni qayta ishga tushiring (docker compose ... restart api) yoki 5 daqiqa kuting."
)


def _is_confirmed(record: StudentStaff) -> bool:
    return record.biometrics_status == "tasdiqlangan" and bool(record.biometric_embedding)


def _mask(pinfl: str | None) -> str:
    return f"••••••••••{pinfl[-4:]}" if pinfl else "JSHSHIR yo'q"


@dataclass
class Pair:
    keep: StudentStaff  # saqlanadi
    remove: StudentStaff  # ma'lumoti ko'chiriladi va o'chiriladi
    take_identity: bool  # True — JSHSHIR va kafedra `remove` dan `keep` ga ko'chiriladi
    kind: str  # "aniq" | "qisman" | "ikkalasi_tasdiqlangan" | "qo'lda"


@dataclass
class Plan:
    pairs: list[Pair] = field(default_factory=list)  # aniq — standart birlashtiriladi
    partial: list[Pair] = field(default_factory=list)  # noaniq — faqat --qisman bilan
    ambiguous: list[list[StudentStaff]] = field(default_factory=list)
    cross_type: list[tuple[StudentStaff, StudentStaff]] = field(default_factory=list)
    incomplete: list[StudentStaff] = field(default_factory=list)  # faqat bitta so'z
    not_found: list[StudentStaff] = field(default_factory=list)  # ro'yxatda o'xshashi yo'q


def build_plan(records: list[StudentStaff]) -> Plan:
    plan = Plan()

    # 1-bosqich: aniq juftliklar
    groups: dict[tuple[str, str], list[StudentStaff]] = defaultdict(list)
    for record in records:
        groups[(record.type, name_key(record.full_name))].append(record)

    handled: set = set()
    for members in groups.values():
        keeps = [r for r in members if not r.pinfl and _is_confirmed(r)]
        sources = [r for r in members if r.pinfl and not _is_confirmed(r)]
        if len(keeps) == 1 and len(sources) == 1:
            plan.pairs.append(Pair(keep=keeps[0], remove=sources[0], take_identity=True, kind="aniq"))
            handled.update({keeps[0].id, sources[0].id})
        elif keeps and sources:
            plan.ambiguous.append(keeps + sources)
            handled.update(r.id for r in keeps + sources)

    # 2-bosqich: qolgan JSHSHIRsiz tasdiqlanganlar uchun noaniq moslik
    orphans = [r for r in records if not r.pinfl and _is_confirmed(r) and r.id not in handled]
    candidate_tokens = [(c, name_tokens(c.full_name)) for c in records if c.pinfl and c.id not in handled]

    matches: dict = {}
    reverse: dict = defaultdict(list)
    for orphan in orphans:
        tokens = name_tokens(orphan.full_name)
        if len(tokens) < 2:
            plan.incomplete.append(orphan)
            continue
        found = [c for c, c_tokens in candidate_tokens if names_match(tokens, c_tokens)]
        same_type = [c for c in found if c.type == orphan.type]
        if same_type:
            found = same_type  # o'z turidagi nomzod bor — boshqa turdagi namesake e'tiborsiz
        matches[orphan.id] = (orphan, found)
        for candidate in found:
            reverse[candidate.id].append(orphan)

    for orphan, found in matches.values():
        if not found:
            plan.not_found.append(orphan)
            continue
        if len(found) > 1 or len(reverse[found[0].id]) > 1:
            group = [orphan, *found] if len(found) > 1 else [*reverse[found[0].id], found[0]]
            if not any({r.id for r in g} == {r.id for r in group} for g in plan.ambiguous):
                plan.ambiguous.append(group)
            continue
        source = found[0]
        if source.type != orphan.type:
            plan.cross_type.append((orphan, source))
        elif _is_confirmed(source):
            plan.partial.append(Pair(keep=source, remove=orphan, take_identity=False, kind="ikkalasi_tasdiqlangan"))
        else:
            plan.partial.append(Pair(keep=orphan, remove=source, take_identity=True, kind="qisman"))
    return plan


# ── birlashtirish ─────────────────────────────────────────────────────────


async def _merge(db: AsyncSession, pair: Pair) -> dict[str, int]:
    keep, remove = pair.keep, pair.remove
    moved: dict[str, int] = {}

    keep_days = select(AttendanceRecord.date).where(AttendanceRecord.student_staff_id == keep.id)
    result = await db.execute(
        update(AttendanceRecord)
        .where(AttendanceRecord.student_staff_id == remove.id)
        .where(AttendanceRecord.date.not_in(keep_days))
        .values(student_staff_id=keep.id)
        .execution_options(synchronize_session=False)
    )
    moved["davomat"] = result.rowcount or 0

    keep_lessons = select(LessonAttendance.lesson_session_id).where(LessonAttendance.student_staff_id == keep.id)
    result = await db.execute(
        update(LessonAttendance)
        .where(LessonAttendance.student_staff_id == remove.id)
        .where(LessonAttendance.lesson_session_id.not_in(keep_lessons))
        .values(student_staff_id=keep.id)
        .execution_options(synchronize_session=False)
    )
    moved["dars_davomati"] = result.rowcount or 0

    result = await db.execute(
        update(LessonSession)
        .where(LessonSession.teacher_id == remove.id)
        .values(teacher_id=keep.id)
        .execution_options(synchronize_session=False)
    )
    moved["dars_jadvali"] = result.rowcount or 0

    await db.execute(delete(AttendanceRecord).where(AttendanceRecord.student_staff_id == remove.id))
    await db.execute(delete(LessonAttendance).where(LessonAttendance.student_staff_id == remove.id))

    removed_name, removed_unit = remove.full_name, remove.group_or_position
    identity = (remove.pinfl, remove.full_name, remove.faculty_id, remove.group_or_position,
                remove.passport_series, remove.passport_number)
    previous_unit = keep.group_or_position
    previous_name = keep.full_name

    # JSHSHIR unikal: avval nusxani o'chirib, keyin raqamni beramiz
    await db.delete(remove)
    await db.flush()

    pinfl, full_name, faculty_id, unit, series, number = identity
    if pair.take_identity:
        keep.pinfl = pinfl
        keep.full_name = full_name
        if faculty_id is not None:
            keep.faculty_id = faculty_id
        if unit:
            keep.group_or_position = unit
        if number and not keep.passport_number:
            keep.passport_series, keep.passport_number = series, number
        action = (
            f"Dublikat birlashtirildi ({pair.kind}): «{removed_name}» JSHSHIR {_mask(pinfl)} va «{unit}» "
            f"yuzi tasdiqlangan «{previous_name}» yozuviga ko'chirildi (oldingi lavozim: «{previous_unit}»), "
            f"nusxa o'chirildi"
        )
    else:
        if keep.faculty_id is None and faculty_id is not None:
            keep.faculty_id = faculty_id
        action = (
            f"Dublikat birlashtirildi ({pair.kind}): «{removed_name}» («{removed_unit}», {_mask(pinfl)}) "
            f"o'chirildi, «{keep.full_name}» {_mask(keep.pinfl)} saqlandi"
        )

    db.add(AuditLog(user_id=None, user_name=AUDIT_USER, action=action, module="Talabalar",
                    status="muvaffaqiyatli", ip="internal"))
    await db.flush()
    return moved


def _print_totals(count: int, totals: dict[str, int], left: int, deleted_face: bool) -> None:
    print()
    print(f"  Birlashtirildi              : {count} ta juftlik")
    print(f"  Ko'chirilgan davomat        : {totals['davomat']} ta kun")
    print(f"  Ko'chirilgan dars davomati  : {totals['dars_davomati']} ta")
    print(f"  Dars jadvalida o'qituvchi   : {totals['dars_jadvali']} ta darsda almashtirildi")
    print(f"  O'chirilmay qolgan nusxa    : {left}")
    print("\nHammasi joyida." if left == 0 else "\nDIQQAT: ba'zi nusxalar o'chmadi — yuqoriga qarang.")
    if deleted_face:
        print(RESTART_HINT)


async def run(
    dry_run: bool = False,
    include_partial: bool = False,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> Plan:
    async with session_factory() as db:
        records = list((await db.execute(select(StudentStaff))).scalars().all())
        faculties = {f.id: f.name for f in (await db.execute(select(Faculty))).scalars().all()}
        plan = build_plan(records)
        _report(plan, faculties, dry_run, include_partial)

        to_merge = plan.pairs + (plan.partial if include_partial else [])
        if dry_run or not to_merge:
            return plan

        removed_ids = [p.remove.id for p in to_merge]
        deleted_face = any(_is_confirmed(p.remove) for p in to_merge)
        totals: dict[str, int] = defaultdict(int)
        for pair in to_merge:
            for key, value in (await _merge(db, pair)).items():
                totals[key] += value
        await db.commit()
        await announce_roster_change()
        left = await db.scalar(select(func.count()).select_from(StudentStaff).where(StudentStaff.id.in_(removed_ids)))

    _print_totals(len(to_merge), totals, left, deleted_face)
    return plan


async def _by_id_prefix(db: AsyncSession, prefix: str) -> StudentStaff:
    prefix = prefix.strip().lower()
    if len(prefix) < 8:
        raise SystemExit(f"ID kamida 8 belgi bo'lishi kerak: {prefix}")
    records = (await db.execute(select(StudentStaff))).scalars().all()
    found = [r for r in records if str(r.id).startswith(prefix)]
    if len(found) != 1:
        raise SystemExit(f"«{prefix}» bilan boshlanadigan yozuv {'topilmadi' if not found else 'bir nechta'}")
    return found[0]


async def run_pair(
    keep_prefix: str,
    remove_prefix: str,
    dry_run: bool = False,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> Pair:
    """Hisobot "qo'lda hal qiling" degan holat uchun — admin o'zi tanlaydi."""
    async with session_factory() as db:
        keep = await _by_id_prefix(db, keep_prefix)
        remove = await _by_id_prefix(db, remove_prefix)
        if keep.id == remove.id:
            raise SystemExit("Saqlanadigan va o'chiriladigan yozuv bir xil")
        if keep.type != remove.type:
            raise SystemExit("Biri talaba, biri xodim — bunday yozuvlar birlashtirilmaydi")
        faculties = {f.id: f.name for f in (await db.execute(select(Faculty))).scalars().all()}
        pair = Pair(keep=keep, remove=remove, take_identity=not keep.pinfl and bool(remove.pinfl), kind="qo'lda")

        print(f"  saqlanadi  : {_describe(keep, faculties)}")
        print(f"  o'chiriladi: {_describe(remove, faculties)}")
        if pair.take_identity:
            print(f"  JSHSHIR va kafedra ko'chiriladi: {_mask(remove.pinfl)}, «{remove.group_or_position}»")
        if dry_run:
            print("\n[dry-run] Bazaga hech narsa yozilmadi.")
            return pair

        deleted_face = _is_confirmed(remove)
        removed_id = remove.id
        totals = await _merge(db, pair)
        await db.commit()
        # Yuz vektorlari ro'yxati o'zgardi — API jarayonlaridagi kesh ham.
        await announce_roster_change()
        left = await db.scalar(select(func.count()).select_from(StudentStaff).where(StudentStaff.id == removed_id))

    _print_totals(1, defaultdict(int, totals), left, deleted_face)
    return pair


# ── hisobot ───────────────────────────────────────────────────────────────


def _describe(record: StudentStaff, faculties: dict) -> str:
    created = to_local(record.created_at).strftime("%d.%m.%Y %H:%M") if record.created_at else "?"
    confirmed = (
        to_local(record.biometrics_confirmed_at).strftime("%d.%m.%Y %H:%M")
        if record.biometrics_confirmed_at
        else ("ha" if _is_confirmed(record) else "yo'q")
    )
    return (
        f"[{str(record.id)[:8]}] {record.full_name} | {'Talaba' if record.type == 'talaba' else 'Xodim'} | "
        f"{_mask(record.pinfl)} | {faculties.get(record.faculty_id, 'Fakultetsiz')} | "
        f"«{record.group_or_position}» | qo'shilgan {created} | yuz: {confirmed}"
    )


def _report(plan: Plan, faculties: dict, dry_run: bool, include_partial: bool) -> None:
    line = "=" * 76
    print(line)
    print(f"  Aniq dublikat juftliklar: {len(plan.pairs)}")
    print(line)
    for i, pair in enumerate(sorted(plan.pairs, key=lambda p: name_key(p.remove.full_name)), 1):
        print(f"  {i:>3}. {pair.remove.full_name}")
        print(f"       saqlanadi : «{pair.keep.group_or_position}» (yuzi tasdiqlangan)")
        print(f"       ko'chadi  : «{pair.remove.group_or_position}», JSHSHIR {_mask(pair.remove.pinfl)}")

    print()
    print(line)
    status = "BIRLASHTIRILADI" if include_partial else "faqat --qisman bilan birlashtiriladi"
    print(f"  Noaniq juftliklar (ism boshqacha yozilgan): {len(plan.partial)} — {status}")
    print(line)
    for i, pair in enumerate(sorted(plan.partial, key=lambda p: name_key(p.keep.full_name)), 1):
        label = "ikkalasi ham tasdiqlangan" if pair.kind == "ikkalasi_tasdiqlangan" else "ism farqi"
        print(f"  {i:>3}. [{label}]")
        print(f"       saqlanadi : {_describe(pair.keep, faculties)}")
        print(f"       o'chiriladi: {_describe(pair.remove, faculties)}")

    if plan.ambiguous:
        print(f"\n  QO'LDA HAL QILING — bir ismda bir nechta yozuv ({len(plan.ambiguous)}).")
        print("  Qaysi birini saqlashni tanlab: --juftlik SAQLANADI_ID O'CHIRILADI_ID --dry-run")
        for group in plan.ambiguous:
            print("    ---")
            for record in group:
                print(f"    {_describe(record, faculties)}")
    if plan.cross_type:
        print(f"\n  QO'LDA HAL QILING — biri talaba, biri xodim ({len(plan.cross_type)}):")
        for orphan, source in plan.cross_type:
            print(f"    {_describe(orphan, faculties)}")
            print(f"    {_describe(source, faculties)}")
            print("    ---")
    if plan.incomplete:
        print(f"\n  Faqat bitta so'z yozilgan — ismini to'liq kiriting yoki --juftlik bilan birlashtiring ({len(plan.incomplete)}):")
        for record in plan.incomplete:
            print(f"    {_describe(record, faculties)}")
    if plan.not_found:
        print(f"\n  Kadrlar ro'yxatida o'xshashi topilmadi — yangi yoki ro'yxatdan tashqari xodimlar ({len(plan.not_found)}):")
        for record in sorted(plan.not_found, key=lambda r: name_key(r.full_name)):
            print(f"    {record.full_name} — «{record.group_or_position}»")
    if dry_run:
        print("\n[dry-run] Bazaga hech narsa yozilmadi.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bir odamning ikki yozuvini birlashtirish")
    parser.add_argument("--dry-run", action="store_true", help="faqat ko'rsatish, bazaga yozmaydi")
    parser.add_argument("--qisman", action="store_true",
                        help="ismi boshqacha yozilgan (noaniq) juftliklarni ham birlashtirish")
    parser.add_argument("--juftlik", nargs=2, metavar=("SAQLANADI", "OCHIRILADI"),
                        help="aniq ko'rsatilgan ikki yozuvni birlashtirish (ID boshidagi 8 belgi)")
    args = parser.parse_args(argv)
    if args.juftlik:
        asyncio.run(run_pair(args.juftlik[0], args.juftlik[1], dry_run=args.dry_run))
    else:
        asyncio.run(run(dry_run=args.dry_run, include_partial=args.qisman))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
