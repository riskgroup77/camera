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
