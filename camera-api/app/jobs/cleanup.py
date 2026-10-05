"""Background maintenance sweep — deletes rows that exist for a bounded
time and are useless once past it: RevokedToken (blocklist entries past
their own JWT exp — see the model's docstring), PasswordResetToken (past
expiry or already used/single-use), and AuditLog rows older than the
retention window. No Celery/cron dependency: this runs as a plain asyncio
task started from main.py's lifespan, since a single periodic sweep
doesn't justify a task queue.

Shaxsga doir ma'lumotlarni saqlash muddati (2026-09-19) ham shu yerda:

* faolsizlantirilgan odamning biometrikasi (yuz rasmi va vektori)
  settings.biometric_retention_days_after_inactive kundan keyin
  o'chiriladi — maqsadga erishilgach ma'lumot saqlanmasligi kerak;
* hodisa suratlari settings.snapshot_retention_days kundan keyin
  ombordan o'chiriladi (hodisa qatorining o'zi event_retention_days
  gacha qoladi, faqat surat ketadi);
* turniket qaydlari (access_events) va bildirishnoma jurnali
  (notification_log) o'z muddatidan keyin o'chiriladi.

Har bir qadam PARTIYALAB ishlaydi: bir aylanishda cheklangan miqdor.
Muddat birinchi marta yoqilganda yoki uzoq to'xtab qolgandan keyin
yuz minglab qator to'planib qolgan bo'lishi mumkin — ularni bitta
tranzaksiyada o'chirish bazani uzoq qulflab qo'yardi. Qolgani keyingi
aylanishlarda o'chadi.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal
from app.models import (
    AccessEvent, AuditLog, Event, NotificationLog, PasswordResetToken, PresenceVisit, RevokedToken, StudentStaff,
    UnknownSighting,
)
from app.services.face_matching import announce_roster_change
from app.services.privacy import clear_biometrics, erase_face_samples, has_biometrics_clause, unique_keys
from app.storage import delete_file, delete_files_quietly

logger = logging.getLogger("app.cleanup")

#: Bitta partiyadagi qatorlar soni va bir aylanishdagi partiyalar chegarasi.
ROW_BATCH_SIZE = 5000
SNAPSHOT_BATCH_SIZE = 500
BIOMETRIC_BATCH_SIZE = 200
MAX_BATCHES_PER_SWEEP = 20


async def _delete_objects(keys: list[str]) -> list[str]:
    """Ombordagi obyektlarni birma-bir o'chiradi va MUVAFFAQIYATLI
    o'chganlarining kalitlarini qaytaradi. Xato bo'lgan kalit bazada
    qoladi va keyingi aylanishda qayta urinib ko'riladi — suratni
    "o'chdi" deb belgilab, aslida omborda qoldirib ketmaslik uchun."""
    deleted: list[str] = []
    for key in keys:
        try:
            await asyncio.to_thread(delete_file, key)
            deleted.append(key)
        except Exception:
            logger.warning("could not delete stored object", extra={"key": key}, exc_info=True)
    return deleted


async def _purge_inactive_biometrics(db: AsyncSession, now: datetime) -> int:
    days = settings.biometric_retention_days_after_inactive
    if days <= 0:
        return 0

    # Faolsizlantirish vaqti yozilmagan yozuvlar (masalan to'g'ridan-to'g'ri
    # bazada o'zgartirilgan) uchun soat shu paytdan boshlanadi. Aks holda
    # ular hech qachon muddatga yetmasdi, yoki aksincha — vaqtsiz qolgan
    # yozuvni darhol o'chirish ham adolatsiz bo'lardi.
    await db.execute(
        update(StudentStaff)
        .where(StudentStaff.active.is_(False), StudentStaff.deactivated_at.is_(None))
        .values(deactivated_at=now)
    )
    await db.commit()

    cutoff = now - timedelta(days=days)
    purged = 0
    for _ in range(MAX_BATCHES_PER_SWEEP):
        people = (
            (
                await db.execute(
                    select(StudentStaff)
                    .where(
                        StudentStaff.active.is_(False),
                        StudentStaff.deactivated_at < cutoff,
                        has_biometrics_clause(),
                    )
                    .order_by(StudentStaff.deactivated_at)
                    .limit(BIOMETRIC_BATCH_SIZE)
                )
            )
            .scalars()
            .all()
        )
        if not people:
            break
        keys = [key for person in people for key in clear_biometrics(person)]
        # Galereya namunalari va biriktirilgan kamera kadrlari ham — faqat
        # asosiy rasm o'chib, qolgan yuz vektorlari qolib ketmasin.
        keys = unique_keys([*keys, *await erase_face_samples(db, [person.id for person in people])])
        await db.commit()
        # Commit'dan keyin: vektor bazadan ketgan, ombordagi xato buni
        # orqaga qaytarmaydi (app/services/privacy.py, finish_erasure).
        await delete_files_quietly(keys)
        purged += len(people)
        if len(people) < BIOMETRIC_BATCH_SIZE:
            break

    if purged:
        await announce_roster_change()
    return purged


async def _prune_snapshots(db: AsyncSession, now: datetime) -> int:
    days = settings.snapshot_retention_days
    # 0 — suratlar hodisa bilan birga (event_retention_days) o'chadi.
    if days <= 0:
        return 0
    cutoff = now - timedelta(days=days)
    pruned = 0
    for _ in range(MAX_BATCHES_PER_SWEEP):
        rows = (
            await db.execute(
                select(Event.id, Event.snapshot_key)
                .where(Event.occurred_at < cutoff, Event.snapshot_key.is_not(None))
                .order_by(Event.occurred_at)
                .limit(SNAPSHOT_BATCH_SIZE)
            )
        ).all()
        if not rows:
            break
        deleted = set(await _delete_objects([key for _id, key in rows]))
        ids = [event_id for event_id, key in rows if key in deleted]
        if ids:
            await db.execute(update(Event).where(Event.id.in_(ids)).values(snapshot_key=None))
            await db.commit()
            pruned += len(ids)
        if not deleted:
            # Ombor umuman javob bermayapti — shu partiyani qayta-qayta
            # aylantirib o'tirmaymiz, keyingi sweep'da urinamiz.
            logger.warning("snapshot pruning stopped: object storage rejected a whole batch")
            break
        if len(rows) < SNAPSHOT_BATCH_SIZE:
            break
    return pruned


async def _delete_in_batches(db: AsyncSession, model, column, cutoff: datetime) -> int:
    """`column < cutoff` bo'lgan qatorlarni ROW_BATCH_SIZE lab o'chiradi."""
    removed = 0
    for _ in range(MAX_BATCHES_PER_SWEEP):
        batch_ids = select(model.id).where(column < cutoff).limit(ROW_BATCH_SIZE).scalar_subquery()
        result = await db.execute(delete(model).where(model.id.in_(batch_ids)))
        await db.commit()
        count = result.rowcount or 0
        removed += count
        if count < ROW_BATCH_SIZE:
            break
    return removed


async def _prune_access_events(db: AsyncSession, now: datetime) -> int:
    days = settings.access_event_retention_days
    if days <= 0:
        return 0
    return await _delete_in_batches(db, AccessEvent, AccessEvent.occurred_at, now - timedelta(days=days))


async def _prune_notification_logs(db: AsyncSession, now: datetime) -> int:
    days = settings.notification_log_retention_days
    if days <= 0:
        return 0
    return await _delete_in_batches(db, NotificationLog, NotificationLog.created_at, now - timedelta(days=days))


async def _prune_presence_visits(db: AsyncSession, now: datetime) -> int:
    days = settings.presence_visit_retention_days
    if days <= 0:
        return 0
    return await _delete_in_batches(db, PresenceVisit, PresenceVisit.last_seen_at, now - timedelta(days=days))


async def _prune_unknown_sightings(db: AsyncSession, now: datetime) -> int:
    """Eski notanish yuzlar — qator va kesilgan yuz rasmi (ombordan) birga."""
    days = settings.unknown_sighting_retention_days
    if days <= 0:
        return 0
    cutoff = now - timedelta(days=days)
    removed = 0
    for _ in range(MAX_BATCHES_PER_SWEEP):
        rows = (
            await db.execute(
                select(UnknownSighting.id, UnknownSighting.crop_key)
                .where(UnknownSighting.last_seen_at < cutoff)
                .limit(ROW_BATCH_SIZE)
            )
        ).all()
        if not rows:
            break
        await db.execute(delete(UnknownSighting).where(UnknownSighting.id.in_([row_id for row_id, _key in rows])))
        await db.commit()
        # Odamga biriktirilgan notanish yuz rasmi uning asosiy surati bo'lib
        # qolgan bo'lishi mumkin — bunday rasm o'chirilmaydi.
        keys = [key for _id, key in rows if key]
        in_use = set()
        if keys:
            in_use = set(
                (
                    await db.execute(
                        select(StudentStaff.biometric_photo_key).where(StudentStaff.biometric_photo_key.in_(keys))
                    )
                ).scalars().all()
            )
        # Qatorlar o'chgach — rasm o'chmasa ham tozalash orqaga qaytmaydi.
        await delete_files_quietly([key for key in keys if key not in in_use])
        removed += len(rows)
        if len(rows) < ROW_BATCH_SIZE:
            break
    return removed


async def run_cleanup_once(db: AsyncSession) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    retention_cutoff = now - timedelta(days=settings.audit_log_retention_days)

    revoked_result = await db.execute(delete(RevokedToken).where(RevokedToken.expires_at < now))
    reset_result = await db.execute(
        delete(PasswordResetToken).where(
            (PasswordResetToken.expires_at < now) | (PasswordResetToken.used_at.is_not(None))
        )
    )
    audit_result = await db.execute(delete(AuditLog).where(AuditLog.occurred_at < retention_cutoff))
    event_cutoff = now - timedelta(days=settings.event_retention_days)
    # Collect the snapshot keys BEFORE the rows go away — once they're
    # deleted nothing knows those objects exist, and MinIO grows forever.
    # (Every purged event previously leaked its JPEG; delete_file() existed
    # in app/storage.py but had no caller anywhere in the codebase.)
    await db.commit()
    # Partiyalab: uzoq to'xtashdan yoki muddat qisqartirilgandan keyin
    # yuz minglab hodisani bitta tranzaksiyada o'chirish xotira va
    # qulflarni band qilardi.
    events_deleted = 0
    snapshots_deleted = 0
    for _ in range(MAX_BATCHES_PER_SWEEP):
        rows = (
            await db.execute(
                select(Event.id, Event.snapshot_key).where(Event.occurred_at < event_cutoff).limit(ROW_BATCH_SIZE)
            )
        ).all()
        if not rows:
            break
        await db.execute(delete(Event).where(Event.id.in_([row_id for row_id, _key in rows])))
        await db.commit()
        events_deleted += len(rows)
        # After the commit: the rows are gone regardless of whether object
        # storage cooperates, and a failed object delete must not roll the
        # purge back (see delete_files_quietly).
        snapshots_deleted += await delete_files_quietly([key for _id, key in rows if key])
        if len(rows) < ROW_BATCH_SIZE:
            break

    counts = {
        "revoked_tokens": revoked_result.rowcount or 0,
        "password_reset_tokens": reset_result.rowcount or 0,
        "audit_logs": audit_result.rowcount or 0,
        "events": events_deleted,
        "event_snapshots": snapshots_deleted,
    }

    # Shaxsga doir ma'lumotlar. Har biri alohida himoyalangan: bittasining
    # xatosi (masalan ombor ishlamasligi) qolganlarini to'xtatmasin.
    steps = (
        ("biometrics_purged", _purge_inactive_biometrics),
        ("snapshots_pruned", _prune_snapshots),
        ("access_events", _prune_access_events),
        ("notification_logs", _prune_notification_logs),
        ("presence_visits", _prune_presence_visits),
        ("unknown_sightings", _prune_unknown_sightings),
    )
    for name, step in steps:
        try:
            counts[name] = await step(db, now)
        except Exception:
            await db.rollback()
            logger.exception("cleanup step failed", extra={"step": name})
            counts[name] = 0

    if any(counts.values()):
        logger.info("cleanup sweep removed expired rows", extra=counts)
    return counts


async def cleanup_loop() -> None:
    """Runs forever, sleeping between sweeps. Errors are caught and logged
    rather than left to crash the loop, so one bad sweep (e.g. a transient
    DB hiccup) doesn't silently stop all future cleanup."""
    interval_seconds = timedelta(hours=settings.cleanup_interval_hours).total_seconds()
    while True:
        try:
            async with SessionLocal() as db:
                await run_cleanup_once(db)
        except Exception:
            logger.exception("cleanup sweep failed")
        await asyncio.sleep(interval_seconds)
