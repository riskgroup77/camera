import math
from typing import Generic, TypeVar

from fastapi import Query
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.base import CamelModel

T = TypeVar("T")


class PageParams:
    """Shared pagination query params — mirrors the frontend's usePagination
    hook shape (page / totalPages / total) so a future paginated fetch on
    the frontend needs no reshaping. Query aliases are camelCase to match
    every other query/body param this API exposes."""

    def __init__(
        self,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=500, alias="pageSize"),
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Page(CamelModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int


async def paginate(db: AsyncSession, stmt: Select, params: PageParams) -> tuple[list, int]:
    """Runs a count query and a page-limited query for the given SELECT
    statement, returning (rows, total). The caller maps rows to DTOs.

    The count is computed by wrapping the (filtered, possibly joined)
    statement as a subquery — with_only_columns(func.count()) silently
    drops the FROM clause and always returns 1, which is the wrong kind of
    bug to ship (it doesn't error, it just lies).
    """
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    page_stmt = stmt.limit(params.page_size).offset(params.offset)
    rows = (await db.execute(page_stmt)).scalars().all()
    return list(rows), total


def build_page(items: list[T], total: int, params: PageParams) -> Page[T]:
    total_pages = max(1, math.ceil(total / params.page_size))
    return Page[T](items=items, total=total, page=params.page, page_size=params.page_size, total_pages=total_pages)
