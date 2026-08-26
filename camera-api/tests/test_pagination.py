"""Regression tests for app/pagination.py.

The first version of paginate() built its count query with
`stmt.with_only_columns(func.count())`, which silently drops the FROM
clause — SQLAlchemy can't infer it from a bare func.count() with no column
reference. That query still executes without error; it just always
returns 1, which is worse than crashing because nothing looks wrong until
someone notices page 2 of a 50-row table doesn't exist. These tests pin
the fix (counting via a wrapped subquery) so it can't regress silently.
"""

import pytest
from sqlalchemy import select

from app.models import Faculty
from app.pagination import PageParams, paginate


@pytest.fixture
async def ten_faculties(db_session):
    faculties = [Faculty(name=f"Fakultet {i}", course_count=1, student_count=0) for i in range(10)]
    db_session.add_all(faculties)
    await db_session.commit()
    return faculties


class TestPaginationCount:
    async def test_total_matches_actual_row_count(self, db_session, ten_faculties):
        stmt = select(Faculty).order_by(Faculty.name)
        _, total = await paginate(db_session, stmt, PageParams(page=1, page_size=3))
        assert total == 10

    async def test_page_size_limits_returned_rows(self, db_session, ten_faculties):
        stmt = select(Faculty).order_by(Faculty.name)
        rows, _ = await paginate(db_session, stmt, PageParams(page=1, page_size=3))
        assert len(rows) == 3

    async def test_second_page_returns_different_rows(self, db_session, ten_faculties):
        stmt = select(Faculty).order_by(Faculty.name)
        page1, _ = await paginate(db_session, stmt, PageParams(page=1, page_size=4))
        page2, _ = await paginate(db_session, stmt, PageParams(page=2, page_size=4))
        assert {r.id for r in page1}.isdisjoint({r.id for r in page2})

    async def test_count_is_correct_with_a_filter_applied(self, db_session, ten_faculties):
        stmt = select(Faculty).where(Faculty.name.in_(["Fakultet 0", "Fakultet 1"])).order_by(Faculty.name)
        _, total = await paginate(db_session, stmt, PageParams(page=1, page_size=20))
        assert total == 2

    async def test_empty_result_set_reports_zero_total(self, db_session, ten_faculties):
        stmt = select(Faculty).where(Faculty.name == "Yo'q bunday").order_by(Faculty.name)
        rows, total = await paginate(db_session, stmt, PageParams(page=1, page_size=20))
        assert total == 0
        assert rows == []

    async def test_page_size_up_to_500_is_accepted(self, db_session, ten_faculties):
        stmt = select(Faculty).order_by(Faculty.name)
        rows, total = await paginate(db_session, stmt, PageParams(page=1, page_size=500))
        assert total == 10
        assert len(rows) == 10
