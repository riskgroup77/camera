# -*- coding: utf-8 -*-
"""Havola orqali rasm topshirgan, lekin tasdiqlanmagan HAMMANI tasdiqlash.

BUYURTMACHI QARORI (2026-10-07): /royxatdan-otish orqali o'tgan, lekin
"tasdiqlangan" bo'lmagan talaba va xodimlar — kamida bitta rasmi bo'lsa —
hammasi tasdiqlansin (bitta old rasm bilan ham; 26-sentabrdagi "3 tomondan
olish shart" qoidasi ular uchun bekor). 7-oktabr holati:
  talabalar: 1169 bitta old rasm bilan "yoq"ga tushirilgan, 85 tasdiq
  kutayotgan (institut ro'yxatida yo'q / shaxs tekshiruvi), 9 boshqa;
  xodimlar: 18 (oldingi tiklashda "o'xshash" deb qolgan), 1 kutayotgan.

Har odam uchun:
  * yuz vektori bazada bo'lsa — o'sha bilan;
  * bo'lmasa — saqlangan rasmdan (old, bo'lmasa chap/o'ng) qayta hisoblanadi;
  * boshqa tasdiqlangan odamga juda o'xshasa ham tasdiqlanadi (buyurtmachi
    "hammasi" dedi), lekin alohida sanaladi va ro'yxati chiqariladi — ular
    bir odamning ikki yozuvi bo'lishi mumkin (dublikatni birlashtirish uchun);
  * bitta ham rasmi yo'q yoki rasmda yuz topilmagan — tasdiqlab bo'lmaydi.

    docker exec camera-api-api-1 python scripts/yuzlarni_tasdiqlash.py                    # sinov
    docker exec camera-api-api-1 python scripts/yuzlarni_tasdiqlash.py --qollash          # yozish
    docker exec camera-api-api-1 python scripts/yuzlarni_tasdiqlash.py --tur xodim --qollash
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from sqlalchemy import or_, select

from app.database import SessionLocal
from app.jobs.hemis_photos import _embed_photo
from app.models import AuditLog, StudentStaff
from app.services.face_matching import announce_roster_change
from app.services.face_recognition import NoFaceDetectedError
from app.storage import read_file

MAX_PHOTO_BYTES = 8_000_000
OBSOLETE_REASONS = ("Yuz bir tomonlama olingan", "institut ro'yxatida yo'q", "shaxsni avtomatik", "HEMIS surati")


def _unit(vector) -> np.ndarray | None:
    arr = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    return arr / norm if norm > 0 and arr.shape == (512,) else None


async def _confirmed_matrix(db) -> tuple[list, np.ndarray]:
    rows = (await db.execute(
        select(StudentStaff.id, StudentStaff.full_name, StudentStaff.biometric_embedding)
        .where(StudentStaff.biometrics_status == "tasdiqlangan", StudentStaff.biometric_embedding.is_not(None))
    )).all()
    people, vectors = [], []
    for pid, name, raw in rows:
        try:
            vec = _unit(json.loads(raw))
        except (ValueError, TypeError):
            continue
        if vec is not None:
            people.append((pid, name))
            vectors.append(vec)
    return people, (np.stack(vectors) if vectors else np.zeros((0, 512), dtype=np.float32))


def closest_other(vector: np.ndarray, people: list, matrix: np.ndarray, own_id, threshold: float):
    """Eng o'xshash BOSHQA tasdiqlangan odam (chegaradan yuqori bo'lsa)."""
    if matrix.shape[0] == 0:
        return None
    sims = matrix @ vector
    for index in np.argsort(-sims)[:3]:
        pid, name = people[int(index)]
        if pid == own_id:
            continue
        sim = float(sims[int(index)])
        return (name, sim) if sim >= threshold else None
    return None


async def _vector_for(person: StudentStaff) -> np.ndarray:
    if person.biometric_embedding:
        try:
            vec = _unit(json.loads(person.biometric_embedding))
            if vec is not None:
                return vec
        except (ValueError, TypeError):
            pass
    errors = []
    for key in (person.biometric_photo_key, person.biometric_photo_left_key, person.biometric_photo_right_key):
        if not key:
            continue
        try:
            data = await asyncio.to_thread(read_file, key, MAX_PHOTO_BYTES)
            if len(data) > MAX_PHOTO_BYTES:
                raise ValueError("Rasm juda katta")
            raw, _height = await _embed_photo(data)
            vec = _unit(raw)
            if vec is not None:
                return vec
        except (NoFaceDetectedError, ValueError) as error:
            errors.append(str(error))
    raise ValueError(errors[0] if errors else "Rasm yo'q")


async def run(kind: str, apply: bool) -> None:
    from app.config import settings

    threshold = settings.self_enrollment_duplicate_threshold
    stats: Counter = Counter()
    similar: list[str] = []
    examples: dict[str, str] = {}
    async with SessionLocal() as db:
        people, matrix = await _confirmed_matrix(db)
        stmt = (
            select(StudentStaff)
            .where(
                StudentStaff.active.is_(True),
                StudentStaff.biometrics_status != "tasdiqlangan",
                StudentStaff.biometrics_opt_out_at.is_(None),
                or_(
                    StudentStaff.biometric_photo_key.is_not(None),
                    StudentStaff.biometric_photo_left_key.is_not(None),
                    StudentStaff.biometric_photo_right_key.is_not(None),
                    StudentStaff.biometric_embedding.is_not(None),
                ),
            )
            .order_by(StudentStaff.type, StudentStaff.full_name)
        )
        if kind != "hammasi":
            stmt = stmt.where(StudentStaff.type == kind)
        candidates = (await db.execute(stmt)).scalars().all()
        print(f"Kamida bitta rasmi bor, tasdiqlanmagan: {len(candidates)} "
              f"(talaba {sum(p.type == 'talaba' for p in candidates)}, xodim {sum(p.type == 'xodim' for p in candidates)})")
        now = datetime.now(timezone.utc)
        for index, person in enumerate(candidates, 1):
            try:
                vector = await _vector_for(person)
            except ValueError as error:
                reason = str(error).split("(")[0].strip()[:60]
                stats[f"{person.type}: tasdiqlab bo'lmadi — {reason}"] += 1
                examples.setdefault(reason, person.full_name)
                continue
            except Exception as error:  # ombor xatosi — keyingisiga
                stats[f"{person.type}: xato {type(error).__name__}"] += 1
                continue
            hit = closest_other(vector, people, matrix, person.id, threshold)
            if hit:
                stats[f"{person.type}: tasdiqlanadi (boshqa odamga o'xshash — tekshiring)"] += 1
                similar.append(f"{person.type}\t{person.full_name}\t{person.group_or_position or ''}\t~ {hit[0]} ({hit[1]:.2f})")
            else:
                stats[f"{person.type}: tasdiqlanadi"] += 1
            if apply:
                person.biometric_embedding = json.dumps([round(float(v), 6) for v in vector])
                person.biometrics_status = "tasdiqlangan"
                person.biometrics_confirmed_at = now
                if any((person.biometrics_review_reason or "").startswith(r) for r in OBSOLETE_REASONS):
                    person.biometrics_review_reason = None
            people.append((person.id, person.full_name))
            matrix = np.vstack([matrix, vector[None, :]])
            if index % 200 == 0:
                print(f"  ... {index}/{len(candidates)}")
                if apply:
                    await db.commit()
        print("Natija:")
        for reason, count in sorted(stats.items()):
            print(f"  {reason}: {count}")
        if similar:
            print(f"\nBoshqa tasdiqlangan odamga juda o'xshaganlar ({len(similar)}) — dublikat bo'lishi mumkin:")
            for line in similar[:60]:
                print("  " + line)
            if len(similar) > 60:
                print(f"  ... yana {len(similar) - 60} ta")
        if not apply:
            print("\nSINOV — hech narsa yozilmadi. Yozish uchun --qollash.")
            return
        confirmed = sum(v for k, v in stats.items() if "tasdiqlanadi" in k)
        db.add(AuditLog(
            user_id=None, user_name="Yuzlarni tasdiqlash (skript)", module="Talabalar", status="muvaffaqiyatli",
            ip="internal", action=f"Havola orqali topshirgan {confirmed} ta odam tasdiqlandi ({kind}); {dict(stats)}",
        ))
        await db.commit()
    if apply:
        await announce_roster_change()
    print("Yozildi.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tur", choices=("hammasi", "talaba", "xodim"), default="hammasi")
    parser.add_argument("--qollash", action="store_true", help="bazaga yozish (aks holda faqat hisobot)")
    args = parser.parse_args()
    asyncio.run(run(args.tur, args.qollash))


if __name__ == "__main__":
    main()
