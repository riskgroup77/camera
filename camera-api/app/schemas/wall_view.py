from typing import Any, Literal

from pydantic import Field

from app.schemas.base import CamelModel

WallViewKind = Literal["view", "tour"]


class WallViewOut(CamelModel):
    id: str
    name: str
    kind: WallViewKind
    payload: dict[str, Any]
    shared: bool
    owner_id: str
    owner_name: str | None
    # Joriy foydalanuvchi uchun hisoblangan: frontend "umumiy" belgisini va
    # tahrirlash tugmalarini shunga qarab ko'rsatadi.
    mine: bool
    can_edit: bool
    created_at: str | None
    updated_at: str | None


class WallViewCreateIn(CamelModel):
    # Brauzer yaratgan id (crypto.randomUUID) — ?view=<id> havolalari va
    # import qayta-qayta bajarilganda takrorlanmasligi uchun saqlanadi.
    # UUID bo'lmasa yoki band bo'lsa server yangisini beradi.
    id: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=60)
    kind: WallViewKind = "view"
    payload: dict[str, Any]
    shared: bool = True


class WallViewUpdateIn(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    payload: dict[str, Any] | None = None
    shared: bool | None = None


class WallViewImportItem(WallViewCreateIn):
    updated_at: str | None = None


class WallViewImportIn(CamelModel):
    items: list[WallViewImportItem] = Field(max_length=100)


class WallViewImportOut(CamelModel):
    created: int
    updated: int
    skipped: int
    items: list[WallViewOut]
