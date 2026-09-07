# -*- coding: utf-8 -*-
"""Sinov uchun bitta xodim yozuvini yaratadi.

MAQSAD. Ro'yxatdan o'tish oqimini (JSHSHIR -> kamera -> uch burilish)
haqiqiy odam ma'lumotini ishlatmasdan sinab ko'rish. Yozuv oddiy
xodimdan farq qilmaydi — farq faqat JSHSHIR raqamida: u ataylab eslab
qolinadigan qilib tanlangan.

ISHGA TUSHIRISH (server, konteyner ichida):

    docker compose exec -T api python scripts/create_test_user.py

Sinov tugagach o'chirish:

    docker compose exec -T api python scripts/create_test_user.py --remove

XAVFSIZLIK IZOHI. 14 ta nol — taxmin qilish oson raqam. Bu sinov uchun
maqbul, lekin yozuv doimiy qolib ketmasligi kerak: uni bilgan istalgan
odam shu yozuvga o'z yuzini biriktirib qo'yishi mumkin. Sinov
tugagandan keyin --remove bilan o'chiring.

Skript IDEMPOTENT: qayta ishga tushirilsa yangi yozuv yaratmaydi,
mavjudini ko'rsatadi. Biometrikaga tegmaydi — allaqachon yuz
biriktirilgan bo'lsa u saqlanadi.
"""

from __future__ import annotations

import asyncio
import os
import sys

# "python scripts/create_test_user.py" da Python yo'liga scripts/ tushadi,
# loyiha ildizi emas — "app" paketi topilishi uchun uni o'zimiz qo'shamiz.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Faculty, StudentStaff
from app.services.face_matching import invalidate_candidate_matrix_cache

PINFL = "00000000000000"
FULL_NAME = "Soyibnazarov Hojiakbar"
POSITION = "Sinov hisobi"
FACULTY_NAME = ""  # bo'sh — fakultetsiz (rektorat va texnik bo'limlar kabi)

ENROLL_URL = "https://cam.fermi.uz/royxatdan-otish"


async def create() -> int:
    async with SessionLocal() as db:
        existing = (
            await db.execute(select(StudentStaff).where(StudentStaff.pinfl == PINFL))
        ).scalar_one_or_none()

        if existing is not None:
            print("Bunday JSHSHIRli yozuv allaqachon bor — yangisi yaratilmadi.\n")
            _show(existing)
            return 0

        faculty = None
        if FACULTY_NAME:
            faculty = (
                await db.execute(select(Faculty).where(Faculty.name == FACULTY_NAME))
            ).scalar_one_or_none()
            if faculty is None:
                print(f"DIQQAT: '{FACULTY_NAME}' nomli fakultet topilmadi — fakultetsiz yaratiladi.")

        record = StudentStaff(
            full_name=FULL_NAME,
            type="xodim",
            pinfl=PINFL,
            faculty_id=faculty.id if faculty else None,
            group_or_position=POSITION,
            biometrics_status="yoq",
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)

        print("Sinov yozuvi yaratildi.\n")
        _show(record)
        return 0


async def remove() -> int:
    async with SessionLocal() as db:
        record = (
            await db.execute(select(StudentStaff).where(StudentStaff.pinfl == PINFL))
        ).scalar_one_or_none()
        if record is None:
            print("Bunday JSHSHIRli yozuv topilmadi — o'chiradigan narsa yo'q.")
            return 0

        had_face = record.biometrics_status == "tasdiqlangan"
        await db.delete(record)
        await db.commit()

    # Yuz biriktirilgan bo'lsa, keshdagi vektorlar ro'yxati eskiradi:
    # o'chirilgan odam kameralarda hali ham tanilib turardi.
    if had_face:
        invalidate_candidate_matrix_cache()

    print(f"Sinov yozuvi o'chirildi (yuz biriktirilgan edi: {'ha' if had_face else 'yo‘q'}).")
    return 0


def _show(record: StudentStaff) -> None:
    status = {
        "tasdiqlangan": "yuzi tasdiqlangan",
        "kutilmoqda": "kutilmoqda",
        "yoq": "yuzi hali yuklanmagan",
    }.get(record.biometrics_status, record.biometrics_status)

    print("=" * 58)
    print(f"  F.I.SH.   : {record.full_name}")
    print(f"  JSHSHIR   : {record.pinfl}")
    print(f"  Turi      : xodim")
    print(f"  Lavozim   : {record.group_or_position}")
    print(f"  Holati    : {status}")
    print("-" * 58)
    print(f"  Sinash uchun: {ENROLL_URL}")
    print(f"  JSHSHIR maydoniga {record.pinfl} ni kiriting")
    print("=" * 58)
    print()
    print("Sinov tugagach o'chirish:")
    print("  docker compose exec -T api python scripts/create_test_user.py --remove")


if __name__ == "__main__":
    action = remove() if "--remove" in sys.argv else create()
    sys.exit(asyncio.run(action))
