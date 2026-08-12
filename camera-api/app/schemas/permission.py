from typing import Literal

from app.schemas.base import CamelModel


class PermissionEntryOut(CamelModel):
    super_admin: bool
    admin: bool


class PermissionToggleIn(CamelModel):
    """Matches the frontend's usePermissions().toggle(key, role) call —
    `role` here means the matrix COLUMN, not the JWT role."""

    role: Literal["superAdmin", "admin"]
