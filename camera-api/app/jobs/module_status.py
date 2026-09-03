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

from datetime import time as time_type
import logging

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.config import settings
from app.models import AIModuleConfig, Camera
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


async def is_module_active(db: AsyncSession, code: int) -> bool:
    result = await db.execute(select(AIModuleConfig.active).where(AIModuleConfig.code == code))
    if not bool(result.scalar_one_or_none()):
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
    return or_(
        Camera.excluded_module_codes.is_(None),
        ~Camera.excluded_module_codes.contains([module_code]),
    )
