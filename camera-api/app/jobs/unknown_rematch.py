"""Noma'lum yuzlarni yangi baza bilan qayta solishtirish.

MUAMMO (2026-09-25). HEMIS rasmlari bazaga kun davomida yuklanadi (7000 ta).
Ertalab kirgan talabaning yuzi hali bazada bo'lmagan — kamera uni
"noma'lum" deb yozgan (bir kunda 1500 ta, kunlik chegaragacha), keyin esa
uning rasmi yuklangan. Bu yozuvlar operator qo'lida qolib ketardi va
talaba o'sha kuni "kelmadi" chiqardi.

YECHIM. Har settings.unknown_rematch_interval_seconds da oxirgi
settings.unknown_rematch_days kundagi ko'rib chiqilmagan noma'lum yuzlar
hozirgi baza (galereya bilan) bilan qayta solishtiriladi. Faqat ISHONCHLI
moslik qabul qilinadi — oddiy tanishdan qat'iyroq:

  * o'xshashlik >= unknown_rematch_similarity va ikkinchi nomzoddan
    >= unknown_rematch_margin uzoq;
  * yuz >= unknown_rematch_min_px (kichik yuz vektori shovqinli).

Mos kelsa: yozuv "talaba" (resolved_by = None — avtomatik), tashrif
yoziladi, eshik kamerasi bo'lsa — o'sha kun davomati (birinchi ko'rinish
vaqti bilan). Yuz galereyaga QO'SHILMAYDI: avtomatik qaror bazaning o'zini
o'zgartirmasin (xato bo'lsa, bitta davomat yozuvi bilan cheklanadi).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select, update

from app.config import settings
from app.database import SessionLocal
from app.models import Camera
from app.models.unknown_sighting import UnknownSighting
from app.services.camera_roles import is_door_camera
from app.services.face_matching import load_candidate_matrix_cached
from app.services.presence import record_visit
from app.timezone import local_now
from app.timezone import business_date, business_today

logger = logging.getLogger("app.jobs.unknown_rematch")

BATCH = 2000


def _vector(raw: str) -> np.ndarray | None:
    try:
        vector = np.asarray(json.loads(raw), dtype=np.float64)
    except (ValueError, TypeError):
        return None
    norm = float(np.linalg.norm(vector))
    return vector / norm if vector.ndim == 1 and norm > 0 else None


async def run_unknown_rematch_once(now: datetime | None = None) -> dict[str, int]:
    stats = {"tekshirildi": 0, "tanildi": 0, "davomat": 0}
    if not settings.unknown_rematch_enabled:
        return stats
    today = business_today() if now is None else business_date(now)
    since = today - timedelta(days=max(0, settings.unknown_rematch_days - 1))
    from app.jobs.attendance_ai import upsert_attendance_from_recognition

    async with SessionLocal() as db:
        sightings = (
            await db.execute(
                select(UnknownSighting)
                .where(
                    UnknownSighting.status == "kutilmoqda",
                    UnknownSighting.day >= since,
                    UnknownSighting.face_px >= settings.unknown_rematch_min_px,
                )
                # Eng yangisi birinchi: bugungi kelishlar (davomat uchun eng
                # muhimi) kechagi 1500 ta tanilmagan yuz ortida qolib ketmasin.
                .order_by(UnknownSighting.day.desc(), UnknownSighting.first_seen_at.desc())
                .limit(BATCH)
            )
        ).scalars().all()
        if not sightings:
            return stats
        matrix = await load_candidate_matrix_cached(db)
        if matrix.is_empty:
            return stats
        usable = [(s, v) for s in sightings if (v := _vector(s.embedding)) is not None and v.shape[0] == matrix.matrix.shape[1]]
        stats["tekshirildi"] = len(usable)
        if not usable:
            return stats
        graded = matrix.graded_matches(
            np.stack([v for _, v in usable]),
            strict_threshold=settings.unknown_rematch_similarity,
            relaxed_threshold=2.0,  # yumshoq moslik bu yerda qabul qilinmaydi
            margin=1.0,
            strict_margin=settings.unknown_rematch_margin,
        )
        # Oddiy qiymatlar oldindan olinadi: bitta yozuv yiqilib rollback
        # bo'lsa, ORM obyektlari eskiradi — qolganlari baribir ishlashi kerak.
        matched = [
            (sighting.id, sighting.camera_id, sighting.first_seen_at, match)
            for (sighting, _), match in zip(usable, graded, strict=True)
            if match.grade == "strict" and match.person_id is not None
        ]
        for sighting_id, camera_id, seen_at, match in matched:
            try:
                await db.execute(
                    update(UnknownSighting)
                    .where(UnknownSighting.id == sighting_id, UnknownSighting.status == "kutilmoqda")
                    .values(
                        status="talaba",
                        person_id=uuid.UUID(str(match.person_id)),
                        resolved_by=None,
                        resolved_at=datetime.now(timezone.utc),
                    )
                )
                stats["tanildi"] += 1
                if camera_id is not None:
                    camera = await db.get(Camera, camera_id)
                    await record_visit(db, match.person_id, camera_id, seen_at, match.similarity)
                    if camera is not None and is_door_camera(camera):
                        await upsert_attendance_from_recognition(
                            db, str(match.person_id), seen_at, camera, off_hours_module_active=False
                        )
                        stats["davomat"] += 1
                await db.commit()
            except Exception:
                # Bitta buzuq yozuv (masalan, odam o'chirilgan) butun
                # navbatni har safar to'xtatib qo'ymasin.
                await db.rollback()
                logger.exception("unknown sighting re-match item failed", extra={"sighting_id": str(sighting_id)})
    if stats["tanildi"]:
        logger.info("unknown sightings re-matched", extra={"event": "unknown_rematch", "stats": stats})
    return stats


async def unknown_rematch_loop() -> None:
    while True:
        await asyncio.sleep(settings.unknown_rematch_interval_seconds)
        try:
            await run_unknown_rematch_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("unknown sighting re-match failed")
