"""Shared helpers for Camera ↔ AIModuleConfig mapping (exclude-list semantics)."""

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Camera


def camera_allows_module_code(excluded_module_codes: list | None, module_code: int) -> bool:
    if excluded_module_codes is None:
        return True
    return module_code not in excluded_module_codes


async def count_faol_cameras_for_module(db: AsyncSession, module_code: int) -> int:
    """How many faol cameras would run this module (global active flag aside)."""
    result = await db.execute(
        select(func.count())
        .select_from(Camera)
        .where(Camera.status == "faol")
        .where(
            or_(
                Camera.excluded_module_codes.is_(None),
                ~Camera.excluded_module_codes.contains([module_code]),
            )
        )
    )
    return int(result.scalar_one())


def set_camera_module_enabled(camera: Camera, module_code: int, enabled: bool) -> None:
    """Update one camera's exclude-list for a single module code."""
    excluded = list(camera.excluded_module_codes or [])
    if enabled:
        if module_code in excluded:
            excluded.remove(module_code)
    elif module_code not in excluded:
        excluded.append(module_code)
    camera.excluded_module_codes = excluded if excluded else None
