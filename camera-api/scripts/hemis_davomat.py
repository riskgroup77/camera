# -*- coding: utf-8 -*-
"""Bir kunlik davomatni HEMIS'dan olish — qoida: app/services/hemis_attendance_sync.py.

Odatda buni fon vazifasi o'zi qiladi (app/jobs/hemis_attendance_sync.py: ish
soatlarida har 30 daqiqada bugun, ertalab — kecha yakuniy). Skript — qo'lda
ishga tushirish yoki o'tgan kunni to'ldirish uchun. Kamera yozgan yozuvlarga
tegilmaydi; HEMIS'dan olingan yozuv source='hemis', kelish vaqti — birinchi
qatnashgan darsi boshlanishi.

ISHGA TUSHIRISH (server):

    docker exec camera-api-api-1 python scripts/hemis_davomat.py --kun 2026-10-05                      # sinov
    docker exec camera-api-api-1 python scripts/hemis_davomat.py --kun 2026-10-05 --qollash            # yozish
    docker exec camera-api-api-1 python scripts/hemis_davomat.py --kun 2026-10-05 --yakuniy --qollash  # + darsi o'tmagan o'qituvchi "kelmadi"

Qayta ishga tushirish xavfsiz: kamera/qo'lda yozuvlar o'zgarmaydi; HEMIS
yozuvi faqat "kelmadi" -> "keldi" (keyingi darsda belgilangan) o'zgaradi.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.hemis_attendance_sync import sync_day


async def run(day: date, apply: bool, finalize: bool) -> None:
    result = await sync_day(day, apply=apply, finalize=finalize)
    print("\n".join(result.lines()))
    if apply:
        print("Yozildi.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kun", required=True, type=date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument("--qollash", action="store_true", help="bazaga yozish (aks holda faqat hisobot)")
    parser.add_argument(
        "--yakuniy", action="store_true",
        help="kun yakuni: jadvalda darsi bo'lib, HEMIS'da birorta darsi o'tmagan o'qituvchi — kelmadi",
    )
    args = parser.parse_args()
    asyncio.run(run(args.kun, args.qollash, args.yakuniy))


if __name__ == "__main__":
    main()
