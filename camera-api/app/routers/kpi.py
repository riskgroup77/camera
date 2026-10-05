"""Rahbariyat KPI paneli: GET /api/kpi?dan=YYYY-MM-DD&gacha=YYYY-MM-DD.

Hisob-kitob app/services/kpi.py da. Davr berilmasa — oxirgi 7 kun.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.services import kpi, situation as svc

router = APIRouter(prefix="/api/kpi", tags=["kpi"])

ReadDep = Annotated[CurrentUser, Depends(require_permission("viewReports"))]
DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("")
async def get_kpi(db: DbDep, _: ReadDep, dan: str | None = None, gacha: str | None = None) -> dict:
    start, end = svc.resolve_range(dan, gacha, default_days=7)
    return await svc.cached(("kpi", start, end), lambda: kpi.build(db, start, end))
