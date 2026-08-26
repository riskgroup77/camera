"""AI modules REGISTRY endpoints.

Manages which of the TT hujjat's 25 criteria are enabled and their tuning
knobs (threshold, sensitivity). Most criteria DO have a real detector
behind them (classical CV/heuristics in app/jobs/*.py — see each row's
`method` field and app/seed.py's per-criterion notes), enforced by every
sweep loop via app/jobs/module_status.py; `accuracy` is frequently 0 not
because nothing runs, but because nobody has benchmarked that heuristic
against ground truth yet. Only `has_detector=False` rows (ID-badge, PPE,
smoking, general dress-code) have no detector at all — activating those
is rejected outright since the toggle would otherwise do nothing.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.models import AIModuleConfig
from app.schemas.ai_module import AIModuleOut, AIModuleUpdateIn
from app.services.camera_module_mapping import count_faol_cameras_for_module

router = APIRouter(prefix="/api/ai-modules", tags=["ai-modules"])

PermDep = Annotated[CurrentUser, Depends(require_permission("configureAi"))]


def _to_out(m: AIModuleConfig, camera_count: int) -> AIModuleOut:
    return AIModuleOut(
        id=str(m.id),
        code=m.code,
        group=m.group,
        name=m.name,
        description=m.description,
        method=m.method,
        accuracy=m.accuracy,
        threshold=m.threshold,
        sensitivity=m.sensitivity,
        camera_count=camera_count,
        active=m.active,
        has_detector=m.has_detector,
    )


@router.get("", response_model=list[AIModuleOut])
async def list_ai_modules(db: Annotated[AsyncSession, Depends(get_db)], _: PermDep) -> list[AIModuleOut]:
    result = await db.execute(select(AIModuleConfig).order_by(AIModuleConfig.code))
    modules = result.scalars().all()
    out: list[AIModuleOut] = []
    for m in modules:
        count = await count_faol_cameras_for_module(db, m.code)
        out.append(_to_out(m, count))
    return out


@router.patch("/{module_id}", response_model=AIModuleOut)
async def update_ai_module(
    module_id: str,
    body: AIModuleUpdateIn,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: PermDep,
) -> AIModuleOut:
    result = await db.execute(select(AIModuleConfig).where(AIModuleConfig.id == module_id))
    module = result.scalar_one_or_none()
    if module is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modul topilmadi")

    if body.active and not module.has_detector:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu modul uchun hali aniqlash logikasi yozilmagan — faollashtirib bo'lmaydi",
        )

    module.threshold = body.threshold
    module.sensitivity = body.sensitivity
    module.active = body.active

    await log_action(db, request, current_user.id, f"AI modulni sozladi: {module.name}", "AI Modullari")
    await db.commit()
    await db.refresh(module)
    count = await count_faol_cameras_for_module(db, module.code)
    return _to_out(module, count)
