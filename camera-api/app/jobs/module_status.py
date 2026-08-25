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

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.models import AIModuleConfig, Camera


async def is_module_active(db: AsyncSession, code: int) -> bool:
    result = await db.execute(select(AIModuleConfig.active).where(AIModuleConfig.code == code))
    return bool(result.scalar_one_or_none())


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
