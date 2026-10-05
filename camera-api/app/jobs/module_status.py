"""Shared helpers every AI sweep loop uses to respect (1) the admin
panel's per-module "active" toggle (AIModuleConfig.active) and (2) the
per-camera module exclusion list (Camera.excluded_module_codes).

Before is_module_active()/any_module_active(), disabling a module in the
UI only changed what the frontend displayed; the background sweep kept
running against every camera regardless. A missing row (shouldn't happen
post-seed) reads as inactive, not an error — a sweep should never crash
over a registry gap.

Before camera_allows_module(), every active module ran on every 'faol'
camera with no way to scope it — e.g. vehicle detection (#25) sweeping
an indoor classroom camera that will never see a car. Camera.excluded_
module_codes is an EXCLUDE list, not an allow list, specifically so every
existing camera (column is nullable) keeps today's behavior — every
active module still runs on it — until an admin deliberately opts it out
of specific modules via PATCH /api/cameras/{id}/modules."""

from datetime import datetime, time as time_type, timedelta, timezone
import logging

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.config import settings
from app.models import AIModuleConfig, Camera, Event, ModuleCameraSuppression
from app.services.camera_roles import effective_room_type, role_allows_clause
from app.timezone import local_now

logger = logging.getLogger("app.module_status")


def _parse_hhmm(value: str, fallback: time_type) -> time_type:
    try:
        hour, minute = value.split(":")
        return time_type(int(hour), int(minute))
    except (ValueError, AttributeError):
        logger.warning("invalid behaviour-hours value; using fallback", extra={"value": value})
        return fallback


def is_within_behaviour_hours(now: time_type | None = None) -> bool:
    """Whether the configured active window covers this moment.

    Handles a window that crosses midnight (start > end, e.g. 21:00-07:00)
    because nothing stops an operator configuring one, and getting that
    silently backwards would disable a module all day instead of all
    night."""
    current = now if now is not None else local_now().time()
    start = _parse_hhmm(settings.behaviour_hours_start, time_type(7, 0))
    end = _parse_hhmm(settings.behaviour_hours_end, time_type(21, 0))
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def is_within_attendance_priority_window(now: time_type | None = None) -> bool:
    """settings.attendance_priority_windows dagi oynalardan biri shu paytni
    qamraydimi. Noto'g'ri yozilgan oyna e'tiborsiz qoldiriladi (logga yoziladi)
    — xato sozlama modulni kun bo'yi to'xtatib qo'ymasligi kerak."""
    current = now if now is not None else local_now().time()
    for part in (settings.attendance_priority_windows or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            start_text, end_text = part.split("-", 1)
            start_h, start_m = start_text.strip().split(":")
            end_h, end_m = end_text.strip().split(":")
            start = time_type(int(start_h), int(start_m))
            end = time_type(int(end_h), int(end_m))
        except ValueError:
            logger.warning("invalid attendance priority window; ignored", extra={"value": part})
            continue
        if start <= end:
            if start <= current <= end:
                return True
        elif current >= start or current <= end:
            return True
    return False


async def _trial_quota_reached(db: AsyncSession, code: int) -> bool:
    """Sinov moduli shu soat ichida yetarlicha namuna berdimi."""
    if settings.trial_events_per_module_hour <= 0:
        return False
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    count = await db.scalar(
        select(func.count())
        .select_from(Event)
        .where(Event.module_code == code)
        .where(Event.is_trial.is_(True))
        .where(Event.occurred_at >= since)
    )
    return (count or 0) >= settings.trial_events_per_module_hour


async def is_module_active(db: AsyncSession, code: int) -> bool:
    row = (
        await db.execute(select(AIModuleConfig.active, AIModuleConfig.mode).where(AIModuleConfig.code == code))
    ).one_or_none()
    if row is None or not row.active:
        return False

    # Sinov rejimida soatlik namuna kvotasi to'lgan bo'lsa, modul shu soat
    # oxirigacha umuman tekshirilmaydi: aniqlikni o'lchash uchun namuna
    # yetarli, qolgan kadrlar faqat CPU va ombor yeydi.
    if row.mode == "sinov" and await _trial_quota_reached(db, code):
        return False

    # Ish vaqti oynasi — settings.behaviour_hours_* izohiga qarang.
    # Tekshiruv aynan SHU YERDA, chunki har bir sweep baribir shu
    # funksiyani chaqiradi: har biriga alohida qo'shilsa, keyin
    # qo'shiladigan modul uni unutib qolardi. Va bu tekshiruv sweep
    # ishni BOSHLASHIDAN oldin bo'lgani uchun kadr olish ham, model
    # chaqirish ham bajarilmaydi.
    if settings.behaviour_hours_enabled and code in settings.behaviour_hours_codes:
        if not is_within_behaviour_hours():
            return False

    return True


async def any_module_active(db: AsyncSession, codes: list[int]) -> bool:
    """For sweeps that serve more than one TT criterion at once (e.g.
    dress_code_ai's #10+#11, lesson_quality_ai's #19+#21) — the sweep
    itself isn't skipped unless ALL of its criteria are off; which
    individual criterion gets evaluated/written is each sweep's own
    concern, not this helper's."""
    result = await db.execute(select(AIModuleConfig.active).where(AIModuleConfig.code.in_(codes)))
    return any(result.scalars().all())


def camera_allows_module(module_code: int) -> ColumnElement[bool]:
    """A .where() filter expression: True for a camera whose
    excluded_module_codes does NOT contain module_code — including the
    common case of excluded_module_codes being NULL entirely (JSONB's
    containment operator returns NULL, not False, against a NULL column,
    which SQL's WHERE would otherwise silently treat as "exclude this
    row" — the opposite of the intended default). Use alongside
    Camera.status == "faol" in every sweep's camera query, e.g.:
        select(Camera).where(Camera.status == "faol").where(camera_allows_module(CODE))
    """
    suppressed = (
        select(ModuleCameraSuppression.id)
        .where(ModuleCameraSuppression.camera_id == Camera.id)
        .where(ModuleCameraSuppression.module_code == module_code)
        .where(ModuleCameraSuppression.restored_at.is_(None))
        .exists()
    )
    return and_(
        or_(
            Camera.excluded_module_codes.is_(None),
            ~Camera.excluded_module_codes.contains([module_code]),
        ),
        # Operatorlar ko'p rad etgani uchun avtomatik o'chirilgan juftlik
        # (app/jobs/module_suppression.py) — admin qaytarguncha ishlamaydi.
        ~suppressed,
        # Xona turi: uyqu faqat auditoriyada, xalat faqat laboratoriyada va
        # h.k. — app/services/camera_roles.py.
        role_allows_clause(module_code),
    )


async def load_suppressed_pairs(db: AsyncSession) -> set[tuple[str, int]]:
    """Faol avtomatik o'chirishlar {(camera_id, module_code)} — kamerani
    Python'da tekshiradigan sweeplar uchun (unified_face_sweep)."""
    rows = await db.execute(
        select(ModuleCameraSuppression.camera_id, ModuleCameraSuppression.module_code).where(
            ModuleCameraSuppression.restored_at.is_(None)
        )
    )
    return {(str(camera_id), code) for camera_id, code in rows.all()}


def _parse_windows(value: str) -> list[tuple[time_type, time_type]]:
    windows: list[tuple[time_type, time_type]] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            start_text, end_text = part.split("-")
            windows.append((time_type.fromisoformat(start_text.strip()), time_type.fromisoformat(end_text.strip())))
        except ValueError:
            logger.warning("invalid time window ignored", extra={"value": part})
    return windows


def _inside_window(window: tuple[time_type, time_type], current: time_type) -> bool:
    start, end = window
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def is_unauthorized_alert_time(now: datetime | None = None) -> bool:
    """Begona shaxs (#1) signal beradigan paytmi: ish kuni bo'lmagan kun yoki
    settings.unauthorized_active_windows oynalaridan biri.

    Oynalar bo'sh yoki hammasi noto'g'ri yozilgan bo'lsa — cheklov yo'q:
    xato sozlama xavfsizlik modulini jimgina o'chirib qo'ymasligi kerak."""
    from app.jobs.absence_marker import is_working_day

    moment = now if now is not None else local_now()
    if not is_working_day(moment.date()):
        return True
    windows = _parse_windows(settings.unauthorized_active_windows)
    if not windows:
        return True
    current = moment.time()
    return any(_inside_window(window, current) for window in windows)


def camera_can_report_unauthorized(camera: Camera) -> bool:
    """Kunduzi ichkaridagi notanish yuz — odatda ro'yxatdan o'tmagan talaba.
    Signal faqat kirish, perimetr va cheklangan xona kameralaridan
    (settings.unauthorized_perimeter_only; tur — app/services/camera_roles.py)."""
    if not settings.unauthorized_perimeter_only:
        return True
    return effective_room_type(camera) in {"kirish", "tashqi", "cheklangan"}
