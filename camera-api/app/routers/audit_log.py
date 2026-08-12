from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, require_permission
from app.models import AuditLog
from app.pagination import Page, PageParams, build_page, paginate
from app.schemas.audit_log import AuditLogOut

router = APIRouter(prefix="/api/audit-log", tags=["audit-log"])


def _to_out(entry: AuditLog) -> AuditLogOut:
    return AuditLogOut(
        id=str(entry.id),
        timestamp=entry.occurred_at.strftime("%Y-%m-%d %H:%M:%S"),
        user=entry.user_name,
        action=entry.action,
        module=entry.module,
        status=entry.status,
        ip=entry.ip,
    )


@router.get("", response_model=Page[AuditLogOut])
async def list_audit_log(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[CurrentUser, Depends(require_permission("systemSettings"))],
    page_params: Annotated[PageParams, Depends()],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    module: Annotated[str | None, Query()] = None,
) -> Page[AuditLogOut]:
    stmt = select(AuditLog).order_by(AuditLog.occurred_at.desc())
    if status_filter:
        stmt = stmt.where(AuditLog.status == status_filter)
    if module:
        stmt = stmt.where(AuditLog.module == module)

    records, total = await paginate(db, stmt, page_params)
    items = [_to_out(e) for e in records]
    return build_page(items, total, page_params)
