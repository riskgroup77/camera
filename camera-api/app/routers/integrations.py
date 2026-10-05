"""HEMIS integratsiyasi: sozlama holati, sinxronlash, tarix."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_action
from app.config import settings
from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.models import IntegrationSyncRun, User
from app.pagination import Page, PageParams, build_page, paginate
from app.schemas.integrations import (
    HemisStatusOut,
    HemisTestOut,
    SyncRunOut,
    SyncStartedOut,
)
from app.services.integrations import hemis
from app.timezone import to_local

router = APIRouter(tags=["integrations"])

ManageDep = Annotated[CurrentUser, Depends(require_permission("manageIntegrations"))]
DbDep = Annotated[AsyncSession, Depends(get_db)]
MODULE = "Integratsiyalar"


def run_to_out(run: IntegrationSyncRun) -> SyncRunOut:
    duration = None
    if run.started_at and run.finished_at:
        duration = max(0, int((run.finished_at - run.started_at).total_seconds()))
    return SyncRunOut(
        id=str(run.id),
        source=run.source,
        status=run.status,
        started_at=to_local(run.started_at).isoformat(timespec="seconds") if run.started_at else None,
        finished_at=to_local(run.finished_at).isoformat(timespec="seconds") if run.finished_at else None,
        duration_seconds=duration,
        triggered_by=run.triggered_by,
        stats=run.stats,
        error=run.error,
    )


def _public_base_url() -> str | None:
    """Manzil ko'rsatiladi, lekin undagi login/parol (user:pass@) — yo'q."""
    url = settings.hemis_base_url.strip()
    if not url:
        return None
    if "@" in url.split("//", 1)[-1].split("/", 1)[0]:
        scheme, rest = url.split("//", 1) if "//" in url else ("", url)
        rest = rest.split("@", 1)[1]
        url = f"{scheme}//{rest}" if scheme else rest
    return url


@router.get("/api/integrations/hemis/status", response_model=HemisStatusOut)
async def hemis_status(db: DbDep, _: ManageDep) -> HemisStatusOut:
    base = select(IntegrationSyncRun).where(IntegrationSyncRun.source == hemis.SOURCE)
    last = (await db.execute(base.order_by(IntegrationSyncRun.started_at.desc()).limit(1))).scalar_one_or_none()
    running = (
        await db.execute(
            base.where(IntegrationSyncRun.status == "ishlamoqda").order_by(IntegrationSyncRun.started_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    success = (
        await db.execute(
            base.where(IntegrationSyncRun.status == "muvaffaqiyatli")
            .order_by(IntegrationSyncRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return HemisStatusOut(
        configured=hemis.hemis_configured(),
        base_url=_public_base_url(),
        sync_interval_hours=settings.hemis_sync_interval_hours,
        deactivate_missing=settings.hemis_deactivate_missing,
        page_size=settings.hemis_page_size,
        running=run_to_out(running) if running else None,
        last_run=run_to_out(last) if last else None,
        last_success_at=(
            to_local(success.finished_at).isoformat(timespec="seconds")
            if success and success.finished_at
            else None
        ),
    )


@router.post("/api/integrations/hemis/test", response_model=HemisTestOut)
async def hemis_test(_: ManageDep) -> HemisTestOut:
    if not hemis.hemis_configured():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "HEMIS sozlanmagan: HEMIS_BASE_URL va HEMIS_API_TOKEN kerak")
    return HemisTestOut.model_validate(await hemis.test_connection())


@router.post("/api/integrations/hemis/sync", response_model=SyncStartedOut, status_code=status.HTTP_202_ACCEPTED)
async def hemis_sync(request: Request, db: DbDep, current_user: ManageDep) -> SyncStartedOut:
    if not hemis.hemis_configured():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "HEMIS sozlanmagan: HEMIS_BASE_URL va HEMIS_API_TOKEN kerak")
    user = await db.get(User, current_user.id)
    run = await hemis.launch_sync(db, user.full_name if user else "admin")
    if run is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "HEMIS sinxronlash allaqachon ishlamoqda")
    await log_action(db, request, current_user.id, "HEMIS sinxronlashni boshladi", MODULE)
    await db.commit()
    return SyncStartedOut(run_id=str(run.id))


@router.get("/api/integrations/runs", response_model=Page[SyncRunOut])
async def list_runs(
    db: DbDep,
    _: ManageDep,
    page_params: Annotated[PageParams, Depends()],
    source: Annotated[str | None, Query(max_length=50)] = None,
) -> Page[SyncRunOut]:
    stmt = select(IntegrationSyncRun)
    if source:
        stmt = stmt.where(IntegrationSyncRun.source == source)
    stmt = stmt.order_by(IntegrationSyncRun.started_at.desc())
    rows, total = await paginate(db, stmt, page_params)
    return build_page([run_to_out(r) for r in rows], total, page_params)


@router.get("/api/integrations/runs/{run_id}", response_model=SyncRunOut)
async def get_run(run_id: uuid.UUID, db: DbDep, _: ManageDep) -> SyncRunOut:
    run = await db.get(IntegrationSyncRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sinxronlash topilmadi")
    # Fon vazifasi boshqa sessiyada yozadi — eski nusxa qaytmasin.
    await db.refresh(run)
    return run_to_out(run)
