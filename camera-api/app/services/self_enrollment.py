"""QR orqali o'zini ro'yxatdan o'tkazganlarni avtomatik tasdiqlash.

Institut qarori (2026-09-19): har birini admin qo'lda tasdiqlashi shart emas.
Tiriklik (liveness) tekshiruvi topshirishda bajariladi. Bitta himoya qoladi:
yangi yuz bazada boshqa, allaqachon tasdiqlangan odamning yuziga juda
o'xshasa (bir odam ikki nom bilan yoki birovning nomidan), u "kutilmoqda"da
qoladi va admin ko'radi."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AuditLog, StudentStaff

logger = logging.getLogger("app.self_enrollment")
_LOCK_KEY = 7_310_422_001


def _unit(vec: list[float]) -> np.ndarray | None:
    arr = np.asarray(vec, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    return arr / norm if norm > 0 else None


async def _confirmed_matrix(db: AsyncSession) -> tuple[list[uuid.UUID], list[str], np.ndarray | None]:
    rows = (
        await db.execute(
            select(StudentStaff.id, StudentStaff.full_name, StudentStaff.biometric_embedding).where(
                StudentStaff.biometrics_status == "tasdiqlangan", StudentStaff.biometric_embedding.is_not(None)
            )
        )
    ).all()
    ids, names, vecs = [], [], []
    for pid, name, raw in rows:
        try:
            vec = _unit(json.loads(raw))
        except (ValueError, TypeError):
            continue
        if vec is not None:
            ids.append(pid)
            names.append(name)
            vecs.append(vec)
    return ids, names, (np.stack(vecs) if vecs else None)


def lookalike(
    embedding: list[float], ids: list[uuid.UUID], names: list[str], matrix: np.ndarray | None, exclude: uuid.UUID
) -> tuple[str, float] | None:
    """Boshqa tasdiqlangan odam bilan o'xshashlik chegaradan yuqori bo'lsa — (ism, o'xshashlik)."""
    vec = _unit(embedding)
    if vec is None or matrix is None:
        return None
    scores = matrix @ vec
    for idx in np.argsort(-scores)[:3]:
        if ids[idx] != exclude and scores[idx] >= settings.self_enrollment_duplicate_threshold:
            return names[idx], float(scores[idx])
    return None


async def decide_status(db: AsyncSession, record: StudentStaff, embedding: list[float]) -> tuple[str, str | None]:
    """Yangi topshirilgan yuz uchun: ("tasdiqlangan", None) yoki ("kutilmoqda", sabab).

    Avtomatik tasdiqlash o'chirilgan bo'lsa — eski tartib: ro'yxatda bor
    odam darhol tasdiqlanadi, o'zini o'zi qo'shgan odam admin qaroriga
    qoladi. O'xshash yuz tekshiruvi esa har doim ishlaydi."""
    if record.self_registered:
        # Institut ro'yxatida (HEMIS) yo'q, o'zini o'zi qo'shgan odam — uni
        # hech kim tasdiqlamagan. Avtomatik tasdiqlansa, istalgan begona
        # o'zini ro'yxatdan o'tkazib "begona shaxs" tekshiruvidan chiqib
        # ketardi. Har doim administrator qaroriga qoladi.
        return "kutilmoqda", "institut ro'yxatida yo'q — administrator tasdig'i kerak"
    ids, names, matrix = await _confirmed_matrix(db)
    hit = lookalike(embedding, ids, names, matrix, record.id)
    if hit:
        return "kutilmoqda", f"yuzi {hit[0]} ga o'xshash ({hit[1]:.2f})"
    if settings.self_enrollment_identity_check:
        # JSHSHIR sir emas: topshirgan odam AYNAN shu odam ekani HEMIS
        # surati bilan tekshiriladi (app/services/identity_check.py).
        from app.services import identity_check

        similarity, problem = await identity_check.hemis_similarity(record, embedding)
        if similarity is None:
            return "kutilmoqda", f"shaxsni avtomatik tasdiqlab bo'lmadi: {problem}"
        if similarity < settings.self_enrollment_identity_threshold:
            return "kutilmoqda", f"HEMIS surati bilan mos kelmadi ({similarity:.2f})"
    if not record.has_all_angles:
        return "kutilmoqda", "yuz 3 tomondan olinmagan — qayta o'tishi kerak"
    return "tasdiqlangan", None


async def approve_pending(db: AsyncSession) -> tuple[int, int]:
    """Kutilayotganlarni (yuzi bor) tasdiqlaydi; o'xshash yuzlilar qoladi.
    Ishga tushishda chaqiriladi — idempotent. Qaytaradi: (tasdiqlandi, qoldi)."""
    if not settings.self_enrollment_auto_approve:
        return 0, 0
    if settings.self_enrollment_identity_check:
        # Kutayotganlar orasida HEMIS surati bilan mos kelmaganlar ham bor —
        # ularni ishga tushishda ko'r-ko'rona tasdiqlash shaxs tekshiruvini
        # aylanib o'tish bo'lardi. Ular administrator qaroriga qoladi.
        return 0, 0
    # api va ai-worker bir vaqtda ishga tushadi — faqat bittasi bajaradi
    # (tranzaksiya qulfi commit bilan bo'shaydi).
    locked = (await db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})).scalar()
    if not locked:
        return 0, 0
    pending = (
        await db.execute(
            select(StudentStaff).where(
                StudentStaff.biometrics_status == "kutilmoqda",
                StudentStaff.biometric_embedding.is_not(None),
                # O'zini o'zi qo'shganlar faqat administrator qarori bilan.
                StudentStaff.self_registered.is_(False),
            )
        )
    ).scalars().all()
    if not pending:
        await db.commit()
        return 0, 0
    ids, names, matrix = await _confirmed_matrix(db)
    approved, held = 0, 0
    now = datetime.now(timezone.utc)
    for record in pending:
        try:
            embedding = json.loads(record.biometric_embedding)
        except (ValueError, TypeError):
            held += 1
            continue
        if lookalike(embedding, ids, names, matrix, record.id) or not record.has_all_angles:
            held += 1
            continue
        record.biometrics_status = "tasdiqlangan"
        record.biometrics_confirmed_at = now
        approved += 1
        vec = _unit(embedding)
        if vec is not None:
            # Keyingi kutilayotganlar shu odam bilan ham solishtiriladi
            # (bir odam ikki marta ro'yxatdan o'tgan bo'lsa, ikkinchisi qoladi).
            ids.append(record.id)
            names.append(record.full_name)
            matrix = vec[None, :] if matrix is None else np.vstack([matrix, vec])
    if approved:
        db.add(
            AuditLog(
                user_id=None,
                user_name="Avtomatik tasdiqlash",
                action=f"O'zi ro'yxatdan o'tgan {approved} kishi avtomatik tasdiqlandi; {held} tasi o'xshash yuz sababli tekshiruvda",
                module="Talabalar",
                status="muvaffaqiyatli",
                ip="internal",
            )
        )
    await db.commit()
    logger.info("self-enrollment auto-approve", extra={"approved": approved, "held": held})
    return approved, held
