"""Shared helpers for Camera ↔ AIModuleConfig mapping (exclude-list semantics)."""

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIModuleConfig, Camera, ModuleCameraSuppression
from app.services.camera_roles import role_allows


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


async def camera_counts_by_module(db: AsyncSession) -> dict[int, int]:
    """Har modul uchun faol kamera soni — bitta aylanishda (ilgari har modulga
    alohida COUNT so'rovi). Avtomatik o'chirilgan juftliklar sanalmaydi."""
    codes = (await db.execute(select(AIModuleConfig.code))).scalars().all()
    cameras = (
        await db.execute(
            select(
                Camera.id,
                Camera.excluded_module_codes,
                Camera.room_type,
                Camera.is_entrance,
                Camera.is_exit,
                Camera.is_perimeter,
            ).where(Camera.status == "faol")
        )
    ).all()
    suppressed = set(
        (
            await db.execute(
                select(ModuleCameraSuppression.camera_id, ModuleCameraSuppression.module_code).where(
                    ModuleCameraSuppression.restored_at.is_(None)
                )
            )
        ).all()
    )
    # Xona turi mos kelmagan kamera ham sanalmaydi (app/services/camera_roles.py).
    return {
        code: sum(
            1
            for camera in cameras
            if camera_allows_module_code(camera.excluded_module_codes, code)
            and (camera.id, code) not in suppressed
            and role_allows(camera, code)
        )
        for code in codes
    }
