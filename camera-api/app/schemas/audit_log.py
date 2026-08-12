from typing import Literal

from app.schemas.base import CamelModel


class AuditLogOut(CamelModel):
    """Matches src/types/index.ts `AuditLogEntry` exactly."""

    id: str
    timestamp: str
    user: str
    action: str
    module: str
    status: Literal["muvaffaqiyatli", "xatolik", "ogohlantirish"]
    ip: str
