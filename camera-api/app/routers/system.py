"""Real server resource metrics for the admin dashboard's "Server resurslari"
widget — CPU/RAM/disk usage of the machine running this API process, via
psutil. Replaces the frontend's old hardcoded mock/admin.ts systemResources."""

from typing import Annotated

import psutil
from fastapi import APIRouter, Depends

from app.dependencies import CurrentUser, get_current_user
from app.schemas.system import SystemResourcesOut

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/resources", response_model=SystemResourcesOut)
async def get_system_resources(_: Annotated[CurrentUser, Depends(get_current_user)]) -> SystemResourcesOut:
    return SystemResourcesOut(
        cpu=round(psutil.cpu_percent(interval=0.1)),
        ram=round(psutil.virtual_memory().percent),
        disk=round(psutil.disk_usage("/").percent),
    )
