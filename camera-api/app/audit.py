from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User


async def log_action(
    db: AsyncSession,
    request: Request,
    actor_id: str,
    action: str,
    module: str,
    status: str = "muvaffaqiyatli",
) -> None:
    """Records a mutation in audit_log. Must be called BEFORE db.commit() in
    the handler so the audit row lands in the same transaction as the
    mutation it describes — either both persist or neither does."""
    user = await db.get(User, actor_id)
    user_name = user.full_name if user else "Noma'lum"
    ip = request.client.host if request.client else "unknown"
    db.add(AuditLog(user_id=actor_id, user_name=user_name, action=action, module=module, status=status, ip=ip))
