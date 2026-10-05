"""Faqat davomat rejimi: qolgan AI mezonlarini vaqtincha FAOLSIZ qilish.

Hech narsa o'chirilmaydi — faqat ai_modules.active = false. Mezonning
sozlamalari (chegara, sezgirlik, rejim), signallar tarixi va kameralardagi
istisnolar joyida qoladi. Qaytarish uchun skript chiqargan `--yoqish`
buyrug'i ishlatiladi (yoki AI Modullari sahifasidagi tugmalar).

Standart rejim — faqat ko'rish; `--qollash` bilan yoziladi.

    C="docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.mediamtx-shard.yml -f docker-compose.ai-worker.yml"
    sudo $C exec -T api python scripts/davomat_rejimi.py                          # holat
    sudo $C exec -T api python scripts/davomat_rejimi.py --faqat-davomat           # nima o'zgarishini ko'rish
    sudo $C exec -T api python scripts/davomat_rejimi.py --faqat-davomat --qollash # yozish
    sudo $C exec -T api python scripts/davomat_rejimi.py --yoqish 1,3,20 --qollash # keyin qaytarish

--faqat-davomat:
  * #6 (xodimlar davomati) yoqiladi, qolgan hamma mezon faolsiz bo'ladi;
  * #7 (talabalar davomati) o'z holicha qoladi — talabalarning deyarli
    hech birida yuz rasmi yo'q; `--talaba-ham` bilan u ham yoqiladi;
  * kameralarda #6/#7 istisno qilingan bo'lsa (excluded_module_codes),
    ro'yxatdan olib tashlanadi — davomat 107 kameraning hammasida ishlasin.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import AIModuleConfig, AuditLog, Camera  # noqa: E402

STAFF = 6
STUDENT = 7


def parse_codes(text: str) -> set[int]:
    codes: set[int] = set()
    for part in text.replace(" ", "").split(","):
        if part:
            codes.add(int(part))
    return codes


def plan_attendance_only(active: dict[int, bool], *, students: bool) -> dict[int, bool]:
    """Kod -> yangi holat, faqat o'zgaradiganlari."""
    keep = {STAFF, STUDENT} if students else {STAFF}
    changes: dict[int, bool] = {}
    for code, is_active in active.items():
        if code == STUDENT and not students:
            continue  # o'z holicha
        want = code in keep
        if is_active != want:
            changes[code] = want
    return changes


def without_attendance(codes: list | None) -> list | None:
    if not codes:
        return codes
    kept = [code for code in codes if code not in (STAFF, STUDENT)]
    return kept or None


async def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Faqat davomat rejimi (AI mezonlarini faolsiz qilish/qaytarish)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--faqat-davomat", action="store_true", help="#6 yoqiq, qolganlari faolsiz")
    mode.add_argument("--yoqish", metavar="KODLAR", help="shu mezonlarni qayta yoqish, masalan 1,3,20")
    parser.add_argument("--talaba-ham", action="store_true", help="#7 talabalar davomatini ham yoqish")
    parser.add_argument("--qollash", action="store_true", help="bazaga yozish (standart: faqat ko'rish)")
    args = parser.parse_args(argv)

    async with SessionLocal() as db:
        modules = list((await db.execute(select(AIModuleConfig).order_by(AIModuleConfig.code))).scalars().all())
        by_code = {m.code: m for m in modules}
        active = {m.code: m.active for m in modules}

        print("Hozirgi holat:")
        for m in modules:
            print(f"  #{m.code:<3} {'YOQIQ ' if m.active else 'faolsiz'}  {m.name}")
        print()

        changes: dict[int, bool] = {}
        camera_fixes: list[tuple[Camera, list | None]] = []
        if args.faqat_davomat:
            changes = plan_attendance_only(active, students=args.talaba_ham)
            cameras = list((await db.execute(select(Camera))).scalars().all())
            for camera in cameras:
                cleaned = without_attendance(camera.excluded_module_codes)
                if cleaned != camera.excluded_module_codes:
                    camera_fixes.append((camera, cleaned))
        elif args.yoqish:
            wanted = parse_codes(args.yoqish)
            unknown = sorted(wanted - set(by_code))
            if unknown:
                print(f"Noma'lum mezon kodlari: {unknown}")
                return 2
            no_detector = sorted(code for code in wanted if not by_code[code].has_detector)
            if no_detector:
                print(f"Bu mezonlarning aniqlash kodi yo'q, yoqilmaydi: {no_detector}")
            changes = {code: True for code in sorted(wanted) if not active[code] and by_code[code].has_detector}
        else:
            print("O'zgartirish uchun --faqat-davomat yoki --yoqish KODLAR bering.")
            return 0

        if not changes and not camera_fixes:
            print("O'zgarish yo'q — hammasi allaqachon shu holatda.")
            return 0
        for code, want in sorted(changes.items()):
            print(f"  #{code:<3} -> {'YOQILADI' if want else 'faolsiz qilinadi'}  {by_code[code].name}")
        for camera, cleaned in camera_fixes:
            print(f"  kamera {camera.name}: davomat istisnosi olib tashlanadi ({camera.excluded_module_codes} -> {cleaned})")
        turned_off = sorted(code for code, want in changes.items() if not want)
        if turned_off:
            print()
            print("Keyin qaytarish buyrug'i (saqlab qo'ying):")
            print(f"  python scripts/davomat_rejimi.py --yoqish {','.join(map(str, turned_off))} --qollash")

        if not args.qollash:
            print()
            print("Hech narsa yozilmadi. Yozish uchun --qollash qo'shing.")
            return 0

        for code, want in changes.items():
            by_code[code].active = want
        for camera, cleaned in camera_fixes:
            camera.excluded_module_codes = cleaned
        summary = ", ".join(f"#{code}={'on' if want else 'off'}" for code, want in sorted(changes.items()))
        db.add(
            AuditLog(
                user_id=None,
                user_name="scripts/davomat_rejimi.py",
                action=f"AI mezonlari holati o'zgartirildi: {summary}"
                + (f"; {len(camera_fixes)} kamerada davomat istisnosi olib tashlandi" if camera_fixes else ""),
                module="AI modullari",
                status="muvaffaqiyatli",
                ip="internal",
            )
        )
        await db.commit()
        print()
        print("Yozildi. AI 5-60 soniya ichida yangi holatga o'tadi (qayta ishga tushirish shart emas).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
