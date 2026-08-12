"""AI modules REGISTRY endpoints.

Honest scope note: this manages which of the TT hujjat's 25 criteria are
configured/enabled and their tuning knobs (threshold, sensitivity) — it
does NOT run any actual computer-vision inference. Building real
detectors for all 25 criteria (fire detection, fall detection, crowd
density, dress-code classification, etc.) is a multi-month ML engineering
project requiring trained models most of which don't exist as off-the-shelf
packages. The one criterion with genuine inference wired up is face
recognition — see app/services/face_recognition.py and /api/face/compare.
Every other row here has accuracy=0 and active=False until a real model
is plugged in behind it.
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

router = APIRouter(prefix="/api/ai-modules", tags=["ai-modules"])

PermDep = Annotated[CurrentUser, Depends(require_permission("configureAi"))]


def _to_out(m: AIModuleConfig) -> AIModuleOut:
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
        camera_count=m.camera_count,
        active=m.active,
    )


@router.get("", response_model=list[AIModuleOut])
async def list_ai_modules(db: Annotated[AsyncSession, Depends(get_db)], _: PermDep) -> list[AIModuleOut]:
    result = await db.execute(select(AIModuleConfig).order_by(AIModuleConfig.code))
    return [_to_out(m) for m in result.scalars().all()]


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

    if body.active and module.accuracy == 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Bu modul uchun hali haqiqiy AI model ulanmagan (accuracy=0) — faollashtirib bo'lmaydi",
        )

    module.threshold = body.threshold
    module.sensitivity = body.sensitivity
    module.active = body.active

    await log_action(db, request, current_user.id, f"AI modulni sozladi: {module.name}", "AI Modullari")
    await db.commit()
    await db.refresh(module)
    return _to_out(module)
