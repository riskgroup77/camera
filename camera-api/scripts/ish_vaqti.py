# -*- coding: utf-8 -*-
"""Kechikish chegarasini o'rnatish — "Sozlamalar → Ish vaqti" bilan bir xil.

Chegara = ish/dars boshlanishi + ruxsat etilgan daqiqalar. Skript
boshlanish vaqtiga tegmaydi, faqat ruxsatni chegara chiqadigan qilib
o'rnatadi va oxirgi 60 kun yozuvlarini qayta hisoblaydi (qo'lda tuzatilgan
va HEMIS davomati yozuvlariga tegilmaydi — app/routers/attendance_policy.py).

    docker exec camera-api-api-1 python scripts/ish_vaqti.py --kechikish 09:00 --sinov
    docker exec camera-api-api-1 python scripts/ish_vaqti.py --kechikish 09:00

Boshqa jarayonlar yangi qoidani bir daqiqa ichida o'qiydi (kesh).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import replace
from datetime import datetime, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models import AttendancePolicy, AuditLog
from app.routers.attendance_policy import recompute_statuses
from app.services.attendance_policy import from_row, load_policy, set_cached


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


async def run(late_after: time, dry_run: bool) -> None:
    async with SessionLocal() as db:
        row = await db.get(AttendancePolicy, 1)
        if row is None:
            raise SystemExit("Ish vaqti qoidasi bazada yo'q — avval saytda 'Sozlamalar → Ish vaqti' ni saqlang")
        start = max(row.staff_start, row.student_start)
        grace = _minutes(late_after) - _minutes(start)
        if grace < 0 or grace > 180:
            raise SystemExit(f"Chegara {late_after:%H:%M} boshlanishdan ({start:%H:%M}) 0..180 daqiqa keyin bo'lishi kerak")
        old = row.grace_minutes
        row.grace_minutes = grace
        holidays = (await load_policy(db, force=True)).holidays
        await db.flush()
        policy = replace(from_row(row), holidays=holidays)
        changed = await recompute_statuses(db, policy)
        print(f"Boshlanish: xodim {row.staff_start:%H:%M}, talaba {row.student_start:%H:%M}; ruxsat {old} -> {grace} daqiqa")
        print(f"Kechikish chegarasi: xodim {policy.late_after('xodim'):%H:%M}, talaba {policy.late_after('talaba'):%H:%M}")
        print(f"Qayta hisoblangan yozuvlar: {changed}" + ("   (SINOV — saqlanmadi)" if dry_run else ""))
        if dry_run:
            await db.rollback()
            return
        db.add(AuditLog(
            user_id=None, user_name="Ish vaqti (skript)", module="Davomat", status="muvaffaqiyatli", ip="internal",
            action=f"Kechikish chegarasi {late_after:%H:%M} (ruxsat {old} -> {grace} daq); {changed} ta yozuv qayta hisoblandi",
        ))
        await db.commit()
        set_cached(policy)
        print("Saqlandi.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kechikish", required=True, type=lambda v: datetime.strptime(v, "%H:%M").time(),
                        help="shu vaqtdan keyin kelgan — kech keldi (HH:MM)")
    parser.add_argument("--sinov", action="store_true", help="hisoblaydi, lekin saqlamaydi")
    args = parser.parse_args()
    asyncio.run(run(args.kechikish, args.sinov))


if __name__ == "__main__":
    main()
