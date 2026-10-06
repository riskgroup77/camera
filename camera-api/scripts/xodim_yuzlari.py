# -*- coding: utf-8 -*-
"""Xodimlarning yuzini o'zlarining RO'YXATDAN O'TISH rasmidan tiklash.

NIMA BO'LGAN (2026-10-06 tekshiruvi). Xodimlar /royxatdan-otish orqali
o'tgan — 613 tasining old tomondan olingan rasmi omborda (biometrics/...,
31-avgust — 19-sentabr) saqlangan. 26-sentabrdagi "3 tomondan olish shart"
qarori bilan ular "yoq" holatiga tushirilgan, yuz vektori o'chirilgan
(sabab: "Yuz bir tomonlama olingan — 3 tomondan qayta o'tishi kerak").
Shu sabab Nazoratda xodimlarning aksariyati "Yuzi bazada yo'q" chiqardi.

6-oktabr qarori: XODIMLAR uchun bitta rasm yetarli (settings.hemis_photo_staff_single,
app/jobs/hemis_photos.py). Bu skript o'sha qoidani ro'yxatdan o'tish
rasmiga qo'llaydi — u HEMIS portretidan sifatliroq (kamera oldida olingan).

Har xodim uchun: saqlangan rasm -> yuz (eng yirigi, chegara bilan qayta
urinish) -> vektor -> boshqa TASDIQLANGAN odamga juda o'xshasa YOZILMAYDI
(settings.self_enrollment_duplicate_threshold) -> "tasdiqlangan".
Talabalarga tegilmaydi.

    docker exec camera-api-api-1 python scripts/xodim_yuzlari.py            # sinov (yozmaydi)
    docker exec camera-api-api-1 python scripts/xodim_yuzlari.py --qollash  # yozish
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
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.jobs.hemis_photos import _embed_photo
from app.models import AuditLog, StudentStaff
from app.services.face_matching import announce_roster_change
from app.services.face_recognition import NoFaceDetectedError
from app.storage import read_file

MAX_PHOTO_BYTES = 8_000_000
ONE_SIDED = "Yuz bir tomonlama olingan"


def _unit(vector) -> np.ndarray | None:
    arr = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    return arr / norm if norm > 0 else None


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
        if vec is not None and vec.shape == (512,):
            people.append((pid, name))
            vectors.append(vec)
    matrix = np.stack(vectors) if vectors else np.zeros((0, 512), dtype=np.float32)
    return people, matrix


def lookalike(vector: np.ndarray, people: list, matrix: np.ndarray, own_id) -> tuple[str, float] | None:
    """Boshqa tasdiqlangan odamga juda o'xshaydimi (toza funksiya — sinovlanadi)."""
    if matrix.shape[0] == 0:
        return None
    sims = matrix @ vector
    best = None
    for index in np.argsort(-sims)[:3]:
        pid, name = people[int(index)]
        if pid == own_id:
            continue
        sim = float(sims[int(index)])
        if sim >= settings.self_enrollment_duplicate_threshold:
            best = (name, sim)
        break
    return best


async def run(apply: bool) -> None:
    stats: Counter = Counter()
    examples: dict[str, str] = {}
    async with SessionLocal() as db:
        people, matrix = await _confirmed_matrix(db)
        staff = (await db.execute(
            select(StudentStaff)
            .where(
                StudentStaff.active.is_(True),
                StudentStaff.type == "xodim",
                StudentStaff.biometrics_status != "tasdiqlangan",
                StudentStaff.biometric_photo_key.is_not(None),
                StudentStaff.biometrics_opt_out_at.is_(None),
            )
            .order_by(StudentStaff.full_name)
        )).scalars().all()
        print(f"Ro'yxatdan o'tish rasmi bor, yuzi tasdiqlanmagan xodimlar: {len(staff)}")
        now = datetime.now(timezone.utc)
        for index, person in enumerate(staff, 1):
            try:
                data = await asyncio.to_thread(read_file, person.biometric_photo_key, MAX_PHOTO_BYTES)
                if len(data) > MAX_PHOTO_BYTES:
                    raise ValueError("Rasm juda katta")
                raw, _height = await _embed_photo(data)
                vector = _unit(raw)
                if vector is None:
                    raise ValueError("Yuz vektori buzilgan")
                hit = lookalike(vector, people, matrix, person.id)
                if hit:
                    raise ValueError(f"Boshqa odamga juda o'xshaydi: {hit[0]} ({hit[1]:.2f})")
            except (NoFaceDetectedError, ValueError) as error:
                reason = str(error).split(":")[0][:60]
                stats[reason] += 1
                examples.setdefault(reason, person.full_name)
                continue
            except Exception as error:  # ombor xatosi va h.k. — keyingisiga o'tamiz
                reason = f"xato: {type(error).__name__}"
                stats[reason] += 1
                examples.setdefault(reason, person.full_name)
                continue
            stats["tiklanadi"] += 1
            if apply:
                person.biometric_embedding = json.dumps([round(float(v), 6) for v in vector])
                person.biometrics_status = "tasdiqlangan"
                person.biometrics_confirmed_at = now
                if (person.biometrics_review_reason or "").startswith(ONE_SIDED):
                    person.biometrics_review_reason = None
            # Keyingi xodimlar shu odam bilan ham solishtiriladi (dublikat yozuvlar).
            people.append((person.id, person.full_name))
            matrix = np.vstack([matrix, vector[None, :]])
            if index % 100 == 0:
                print(f"  ... {index}/{len(staff)}")
                if apply:
                    await db.commit()
        # Tasdiqlangan, lekin eskirgan "bir tomonlama" sababi qolganlar.
        stale = (await db.execute(
            select(StudentStaff).where(
                StudentStaff.type == "xodim",
                StudentStaff.biometrics_status == "tasdiqlangan",
                StudentStaff.biometrics_review_reason.startswith(ONE_SIDED),
            )
        )).scalars().all()
        for person in stale:
            if apply:
                person.biometrics_review_reason = None
        print("Natija:")
        for reason, count in stats.most_common():
            sample = f"   (masalan: {examples[reason]})" if reason in examples else ""
            print(f"  {reason}: {count}{sample}")
        print(f"  eskirgan 'bir tomonlama' sababi tozalanadi (allaqachon tasdiqlangan): {len(stale)}")
        if not apply:
            print("SINOV — hech narsa yozilmadi. Yozish uchun --qollash.")
            return
        db.add(AuditLog(
            user_id=None, user_name="Xodim yuzlari (skript)", module="Talabalar", status="muvaffaqiyatli", ip="internal",
            action=f"Xodim yuzlari ro'yxatdan o'tish rasmidan tiklandi: {stats['tiklanadi']} ta; {dict(stats)}",
        ))
        await db.commit()
    if stats["tiklanadi"]:
        await announce_roster_change()
    print("Yozildi.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--qollash", action="store_true", help="bazaga yozish (aks holda faqat hisobot)")
    args = parser.parse_args()
    asyncio.run(run(args.qollash))


if __name__ == "__main__":
    main()
