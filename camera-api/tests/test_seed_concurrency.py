import asyncio

import pytest
from sqlalchemy import func, select

from app.models import Building, Faculty
from app.seed import seed_all
from tests.conftest import TestSessionLocal


class TestSeedConcurrency:
    """Multi-worker uvicorn (app/main.py's --workers flag) means every
    worker process calls seed_all() independently at boot against the
    same empty database — this simulates that race with two real,
    concurrent DB sessions instead of the single shared db_session fixture
    other tests use, since the race only exists across separate
    connections."""

    async def test_concurrent_seed_from_two_sessions_does_not_raise_and_seeds_once(self):
        async def seed_in_new_session():
            async with TestSessionLocal() as session:
                await seed_all(session)

        await asyncio.gather(seed_in_new_session(), seed_in_new_session())

        async with TestSessionLocal() as session:
            faculty_count = await session.scalar(select(func.count()).select_from(Faculty))
            building_count = await session.scalar(select(func.count()).select_from(Building))

        assert faculty_count == 4  # len(DEFAULT_FACULTIES)
        assert building_count == 3  # len(DEFAULT_BUILDINGS)


class TestModuleDocsFollowTheCode:
    """Productionda 7 ta modul tavsifida kodda yo'q texnologiya yozilgan edi —
    seed faqat bo'sh jadvalni to'ldirgani uchun tuzatishlar yetib bormagan."""

    async def test_stale_docs_are_replaced_but_admin_settings_are_kept(self, db_session):
        from sqlalchemy import select

        from app.models import AIModuleConfig
        from app.seed import DEFAULT_AI_MODULES, seed_all

        await seed_all(db_session)
        row = (await db_session.execute(select(AIModuleConfig).where(AIModuleConfig.code == 6))).scalar_one()
        row.method = "YOLOv8-face + ArcFace, mahalliy GPU"
        row.description = "eski matn"
        row.threshold = 91
        row.active = False
        row.mode = "sinov"
        await db_session.commit()

        await seed_all(db_session)
        await db_session.refresh(row)

        expected = next(m for m in DEFAULT_AI_MODULES if m["code"] == 6)
        assert row.method == expected["method"]
        assert row.description == expected["description"]
        assert (row.threshold, row.active, row.mode) == (91, False, "sinov")


async def test_seed_holds_exactly_the_customer_criteria(db_session):
    """2026-10-04 buyurtmachi ro'yxati: 9 ta kriteriya, 10 va 15 sinov rejimida."""
    from sqlalchemy import select

    from app.models import AIModuleConfig
    from app.seed import seed_all

    await seed_all(db_session)
    rows = {row.code: row for row in (await db_session.execute(select(AIModuleConfig))).scalars()}
    assert set(rows) == {6, 7, 8, 9, 10, 15, 19, 21, 22}
    assert all(row.active for row in rows.values())
    assert {code for code, row in rows.items() if row.mode == "sinov"} == {10, 15, 19, 21}
