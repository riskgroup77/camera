# -*- coding: utf-8 -*-
"""Yuzli/JSHSHIRli klonlarni HEMIS yozuviga birlashtirish (bir yo'la).

09.10 holati: odam havola orqali o'tganda yangi yozuv (klon) ochilgan — yuz
va JSHSHIR shunda; HEMIS'dan kelgan yozuvda esa guruh, davomat va dars
jadvali. Keyin klonlar faolsizlantirilgan: kamera ularni tanimaydi,
tahrirlashda "Bu JSHSHIR boshqa yozuvga biriktirilgan" xatosi chiqadi.

Juftlash — person_dedupe.find_clone_pairs (ism turlicha yozilishi,
kirill/lotin, so'z tartibi, familiya o'zgargani; guruh raqami va yagonalik).
Birlashtirish — person_dedupe.merge_manual: yuzi tasdiqlangan yozuv qoladi,
ism/guruh/fakultet/HEMIS ID rasmiy yozuvdan, davomat va darslar ko'chadi,
natija faol; odam yuzini qayta topshirmaydi. Noaniq juftlar (bir klonga
bir nechta nomzod) tegilmaydi — reestrdagi "Birlashtirish" tugmasi bilan.

    docker exec camera-api-api-1 python scripts/klonlarni_birlashtirish.py              # sinov + hisobot
    docker exec camera-api-api-1 python scripts/klonlarni_birlashtirish.py --qollash    # bajarish

Bajarishdan oldin ishtirokchi yozuvlar klon_zaxira_<sana> jadvaliga
nusxalanadi (qaytarish uchun).
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.database import SessionLocal
from app.models import AuditLog
from app.services import person_dedupe as pd
from app.services.face_matching import announce_roster_change

ROWS_SQL = """
    select s.id, s.type, s.full_name, s.group_or_position, s.reported_group, s.hemis_id, s.pinfl, s.active,
           s.self_registered, s.biometrics_status, (s.biometric_embedding is not null) as biometric_embedding,
           (s.biometric_photo_key is not null and s.biometric_photo_left_key is not null
            and s.biometric_photo_right_key is not null) as uch_tomon
    from students_staff s
"""
REPORT = "/tmp/klonlar_hisobot.json"


def _label(row: dict) -> str:
    face = "yuz" + ("+3" if row.get("uch_tomon") else "") if row.get("biometric_embedding") else "yuzsiz"
    return (f"{row['full_name']} [{row.get('group_or_position') or '-'}; {face}; "
            f"{'JSHSHIR' if row.get('pinfl') else 'JSHSHIRsiz'}; {'faol' if row.get('active') else 'faol emas'}]")


async def run(apply: bool) -> None:
    async with SessionLocal() as db:
        rows = [dict(r._mapping) for r in (await db.execute(text(ROWS_SQL))).all()]
    groups, unsure = pd.find_clone_pairs(rows)
    with_face = sum(any(pd._is_face(c) for c in clones) for _, clones in groups)
    print(f"Aniq guruhlar: {len(groups)} (yuzli klon bilan: {with_face}); klonlar: {sum(len(c) for _, c in groups)}; "
          f"noaniq (tegilmaydi): {len(unsure)}")
    print("Turi bo'yicha:", dict(collections.Counter(t["type"] for t, _ in groups)))
    json.dump(
        {
            "aniq": [{"hemis": _label(t), "klonlar": [_label(c) for c in clones]} for t, clones in groups],
            "noaniq": [{"klon": _label(c), "nomzodlar": [_label(t) for t in hits]} for c, hits in unsure],
        },
        open(REPORT, "w", encoding="utf-8"), ensure_ascii=False,
    )
    print(f"Hisobot: {REPORT}")
    if not apply:
        print("SINOV — hech narsa yozilmadi. Bajarish uchun --qollash.")
        return

    backup = f"klon_zaxira_{date.today():%Y%m%d}"
    ids = [str(t["id"]) for t, _ in groups] + [str(c["id"]) for _, clones in groups for c in clones]
    async with SessionLocal() as db:
        await db.execute(text(f"create table if not exists {backup} as select * from students_staff where false"))
        await db.execute(
            text(f"insert into {backup} select * from students_staff where id = any(cast(:ids as uuid[]))"), {"ids": ids}
        )
        await db.commit()
    print(f"Zaxira: {backup} ({len(ids)} yozuv)")

    merged = failed = 0
    moved_total: collections.Counter = collections.Counter()
    errors: list[str] = []
    for target, clones in groups:
        survivor = target["id"]
        for clone in sorted(clones, key=pd._face_rank, reverse=True):
            async with SessionLocal() as db:
                try:
                    result = await pd.merge_manual(db, survivor, clone["id"], apply=True)
                    db.add(AuditLog(
                        user_id=None, user_name="Klonlarni birlashtirish (skript)", module="Shaxslar reestri",
                        status="muvaffaqiyatli", ip="internal",
                        action=(f"Klon birlashtirildi: {result['result']['full_name']} ← {clone['full_name']} "
                                f"({', '.join(f'{k}: {v}' for k, v in result['moved'].items()) or 'ko‘chirilgan yozuv yo‘q'})"),
                    ))
                    await db.commit()
                    survivor = result["keeper"]["id"]
                    merged += 1
                    moved_total.update(result["moved"])
                except Exception as exc:  # MergeError yoki baza cheklovi — shu juftlik o'tkaziladi
                    await db.rollback()
                    failed += 1
                    errors.append(f"{clone['full_name']} -> {target['full_name']}: {str(exc).splitlines()[0][:160]}")
    async with SessionLocal() as db:
        db.add(AuditLog(
            user_id=None, user_name="Klonlarni birlashtirish (skript)", module="Shaxslar reestri",
            status="muvaffaqiyatli", ip="internal",
            action=f"Klonlar birlashtirildi: {merged} ta; rad etildi: {failed}; zaxira: {backup}",
        ))
        await db.commit()
    await announce_roster_change()
    print(f"Birlashtirildi: {merged}; rad etildi: {failed}; ko'chirildi: {dict(moved_total)}")
    for line in errors[:40]:
        print("  ! " + line)
    print("Yozildi.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--qollash", action="store_true", help="bazaga yozish (aks holda faqat hisobot)")
    asyncio.run(run(parser.parse_args().qollash))


if __name__ == "__main__":
    main()
