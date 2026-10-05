# -*- coding: utf-8 -*-
"""Bir kunlik davomatni HEMIS'dan olish — qoida: app/services/hemis_attendance.py.

Dastur davomatni o'zi yuritmagan kun uchun (masalan, ishga tushirilgan
kundan oldingi kun). Kamera yozgan yozuvlarga tegilmaydi; HEMIS'dan
olingan yozuv source='hemis', kelish vaqti bo'sh.

ISHGA TUSHIRISH (server):

    docker exec camera-api-api-1 python scripts/hemis_davomat.py --kun 2026-10-05            # sinov
    docker exec camera-api-api-1 python scripts/hemis_davomat.py --kun 2026-10-05 --qollash  # yozish

Qayta ishga tushirish xavfsiz: mavjud yozuv (kun + odam) o'zgartirilmaydi.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.database import SessionLocal
from app.models import AttendanceRecord, AuditLog, StudentStaff
from app.services.hemis_attendance import day_attendance
from app.services.integrations import hemis

SOURCE = "hemis"
AUDIT_USER = "HEMIS davomati"


async def fetch_day(day: date) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    # HEMIS lesson_date — kunning UTC yarim tuni (1791158400 = 2026-10-05).
    start = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
    params = {"lesson_date_from": start, "lesson_date_to": start + 86399}
    async with hemis.HemisClient() as client:
        controls = await client.fetch_all("attendance-control-list", params=params)
        absences = await client.fetch_all("attendance-list", params=params)
        students = await client.fetch_all(hemis.ENTITY_ENDPOINTS["students"])
        employees = await hemis.fetch_employees(client)
    # Boshqa kunlar aralashmasin (filtr e'tiborsiz qolsa ham).
    controls = [r for r in controls if r.get("lesson_date") in (None, start)]
    absences = [r for r in absences if r.get("lesson_date") in (None, start)]
    return controls, absences, students, employees


async def run(day: date, apply: bool) -> None:
    controls, absences, students, employees = await fetch_day(day)
    by_group: dict = {}
    number_of: dict = {}
    for item in students:
        person = hemis.map_student(item)
        group = (item.get("group") or {}).get("id") if isinstance(item.get("group"), dict) else None
        if person is None or not person.active or item.get("id") is None:
            continue
        number_of[item["id"]] = person.hemis_id
        if group is not None:
            by_group.setdefault(group, []).append(item["id"])
    staff_number = {item.get("id"): hemis.map_employee(item).hemis_id for item in employees
                    if item.get("id") is not None and hemis.map_employee(item) is not None}

    result = day_attendance(controls, absences, by_group)
    wanted: dict[str, str] = {number_of[sid]: status for sid, status in result.students.items() if sid in number_of}
    teachers = {staff_number[t] for t in result.teachers if t in staff_number}

    async with SessionLocal() as db:
        rows = (await db.execute(
            select(StudentStaff.id, StudentStaff.hemis_id, StudentStaff.type)
            .where(StudentStaff.active.is_(True), StudentStaff.hemis_id.in_([*wanted, *teachers]))
        )).all()
        existing = set((await db.execute(
            select(AttendanceRecord.student_staff_id).where(AttendanceRecord.date == day)
        )).scalars().all())
        plan: list[tuple] = []
        for pid, hemis_id, kind in rows:
            status = wanted.get(hemis_id) if kind == "talaba" else ("keldi" if hemis_id in teachers else None)
            if status and pid not in existing:
                plan.append((pid, kind, status))
        counts = Counter((kind, status) for _, kind, status in plan)
        print(f"HEMIS {day}: davomat olingan darslar {len(controls)}, guruhlar {result.groups_checked} "
              f"(talabasi topilmagan {result.groups_without_students}), kelmaganlik qaydlari {len(absences)}")
        print(f"  HEMIS bo'yicha talabalar: keldi {sum(1 for s in wanted.values() if s == 'keldi')}, "
              f"kelmadi {sum(1 for s in wanted.values() if s == 'kelmadi')}; dars o'tgan o'qituvchilar {len(teachers)}")
        print(f"  bazada topildi: {len(rows)}; shu kuni yozuvi bor (kamera) — tegilmaydi: "
              f"{sum(1 for pid, *_ in rows if pid in existing)}")
        print(f"  YOZILADI: talaba keldi {counts[('talaba', 'keldi')]}, talaba kelmadi {counts[('talaba', 'kelmadi')]}, "
              f"xodim keldi {counts[('xodim', 'keldi')]}" + ("" if apply else "   (SINOV — yozilmadi; --qollash bilan yoziladi)"))
        if not apply or not plan:
            return
        for start in range(0, len(plan), 1000):
            chunk = plan[start:start + 1000]
            await db.execute(
                insert(AttendanceRecord)
                .values([{"student_staff_id": pid, "date": day, "status": status, "source": SOURCE} for pid, _, status in chunk])
                .on_conflict_do_nothing(index_elements=["student_staff_id", "date"])
            )
        db.add(AuditLog(
            user_id=None, user_name=AUDIT_USER, module="Davomat", status="muvaffaqiyatli", ip="internal",
            action=f"{day} davomati HEMIS'dan: {dict(counts)}",
        ))
        await db.commit()
        print("Yozildi.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kun", required=True, type=date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument("--qollash", action="store_true", help="bazaga yozish (aks holda faqat hisobot)")
    args = parser.parse_args()
    asyncio.run(run(args.kun, args.qollash))


if __name__ == "__main__":
    main()
