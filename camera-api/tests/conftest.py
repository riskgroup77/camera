from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import get_db
from app.main import app
from app.models import Base
from app.rate_limit import limiter
from app.seed import seed_all

TEST_DATABASE_URL = settings.database_url.rsplit("/", 1)[0] + "/camera_api_test"

test_engine = create_async_engine(TEST_DATABASE_URL)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _setup_schema():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await test_engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables():
    """Truncates every table before each test so tests don't see each
    other's data, without paying for a schema drop/recreate per test."""
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    limiter.reset()  # slowapi's in-memory bucket is a module-level singleton
    from app.jobs.camera_health import reset_camera_health_state_for_tests
    from app.jobs.disorder_ai import reset_motion_history_for_tests
    from app.services.face_matching import invalidate_candidate_matrix_cache

    invalidate_candidate_matrix_cache()
    reset_camera_health_state_for_tests()
    reset_motion_history_for_tests()
    yield
    invalidate_candidate_matrix_cache()
    reset_camera_health_state_for_tests()
    reset_motion_history_for_tests()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> None:
    """Same seed data the real app boots with — demo users, default
    permission matrix, starting faculties/buildings."""
    await seed_all(db_session)


async def login(client: AsyncClient, login_name: str, password: str) -> str:
    resp = await client.post("/api/auth/login", json={"login": login_name, "password": password})
    resp.raise_for_status()
    return resp.json()["token"]


async def auth_headers(client: AsyncClient, login_name: str, password: str) -> dict[str, str]:
    token = await login(client, login_name, password)
    return {"Authorization": f"Bearer {token}"}
