import os

import pytest
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

# TEST_DATABASE_URL — bir nechta test jarayoni parallel ishlaganda har biri
# o'z bazasini oladi (aks holda drop_all/create_all bir-birini buzadi).
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or (
    settings.database_url.rsplit("/", 1)[0] + "/camera_api_test"
)

# Testlar demo hisoblar (admin/admin123, operator/operator123) bilan
# ishlaydi. Production'da ular standart bo'yicha yaratilmaydi.
settings.seed_demo_users = True

test_engine = create_async_engine(TEST_DATABASE_URL)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _setup_schema():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await test_engine.dispose()


@pytest.fixture(autouse=True)
def _behaviour_hours_off():
    """Takes the wall clock out of the test suite.

    The behaviour-hours gate (app/jobs/module_status.py) switches modules
    5/16/17/20 off outside working hours, so without this every sweep
    test for those modules passed by day and failed by night — which is
    exactly how it was found: three of them broke on an evening run and
    nothing about the code had changed since the morning.

    The gate has its own tests, which set the window and the clock
    explicitly rather than inheriting whatever time it happens to be.
    """
    from app.config import settings

    original = settings.behaviour_hours_enabled
    original_sleep = settings.sleep_only_during_lessons
    settings.behaviour_hours_enabled = False
    # Uyqu testlari dars jadvalini yaratmaydi; darvozaning o'z testi
    # (test_unified_face_sweep.py) uni ataylab yoqadi.
    settings.sleep_only_during_lessons = False
    yield
    settings.behaviour_hours_enabled = original
    settings.sleep_only_during_lessons = original_sleep


@pytest.fixture(autouse=True)
def _fresh_live_focus():
    """Jonli skaner holati (app/services/live_focus.py) testlar orasida
    bo'lishilmasin; API kuzatuvchi natijasini kutmaydi (testda kuzatuvchi
    yo'q) — eski yo'l darhol ishlaydi. Kutishning o'z testlari uni yoqadi."""
    from app.config import settings
    from app.routers import public
    from app.services import live_focus

    original = settings.live_result_first_wait_seconds
    settings.live_result_first_wait_seconds = 0.0
    live_focus.reset_for_tests()
    public._no_watcher_until.clear()
    yield
    settings.live_result_first_wait_seconds = original
    live_focus.reset_for_tests()
    public._no_watcher_until.clear()


@pytest.fixture(autouse=True)
def _fresh_inference_cache():
    """Kadr natijalari keshi (app/services/inference_cache.py) testlar
    orasida bo'lishilmasin: ko'p test bir xil soxta kadr baytlarini
    ishlatadi, lekin modelni har xil soxtalashtiradi."""
    from app.services.inference_cache import inference_cache

    from app.jobs.lesson_quality_ai import reset_sampling_for_tests

    from app.services import face_gallery, face_zoom, static_faces, stream_promotion
    from app.services.face_tracks import track_store

    inference_cache.clear()
    reset_sampling_for_tests()
    track_store.clear()
    face_gallery.reset_for_tests()
    stream_promotion.reset_for_tests()
    face_zoom.zoom_limiter.reset()
    static_faces.reset_for_tests()
    yield
    inference_cache.clear()
    reset_sampling_for_tests()
    track_store.clear()
    face_gallery.reset_for_tests()
    stream_promotion.reset_for_tests()
    face_zoom.zoom_limiter.reset()
    static_faces.reset_for_tests()


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables():
    """Truncates every table before each test so tests don't see each
    other's data, without paying for a schema drop/recreate per test."""
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    limiter.reset()  # slowapi's in-memory bucket is a module-level singleton
    from app.jobs.camera_health import reset_camera_health_state_for_tests
    from app.services.face_matching import invalidate_candidate_matrix_cache

    from app.jobs import attendance_ai
    from app.services import situation as situation_svc

    # Umumiy (foydalanuvchiga bog'liq bo'lmagan) 15 s keshlar oldingi testdan qolmasin.
    situation_svc.clear_cache()
    invalidate_candidate_matrix_cache()
    reset_camera_health_state_for_tests()
    attendance_ai._off_hours_raised.clear()
    yield
    invalidate_candidate_matrix_cache()
    reset_camera_health_state_for_tests()


#: Testlardagi ro'yxatdan o'tish kodi.
#
#: Ochiq ro'yxatdan o'tish endi guruh kodini talab qiladi
#: (app/services/enrollment_code.py). Har bir test o'ziga guruh kodi
#: yaratib o'tirmasligi uchun bu yerda institut bo'yicha ZAXIRA
#: ('umumiy') kod yaratiladi: u o'z kodi bo'lmagan yozuvlarga qo'llanadi,
#: ya'ni guruh kodini ataylab tekshiradigan testlar o'z kodini yaratib,
#: shu zaxirani o'zi bosib o'tadi.
ENROLL_CODE = "K7M2XR"


@pytest_asyncio.fixture(autouse=True)
async def _enrollment_code(_clean_tables) -> AsyncGenerator[str, None]:
    # _clean_tables jadvallarni tozalagandan KEYIN yozilishi shart —
    # aks holda kod o'sha tozalashda o'chib ketardi.
    from app.models import EnrollmentCode

    async with TestSessionLocal() as session:
        session.add(EnrollmentCode(scope="umumiy", unit_key="", unit_name="Butun institut", code=ENROLL_CODE))
        await session.commit()
    yield ENROLL_CODE


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
async def seeded(request, db_session: AsyncSession) -> None:
    """Same seed data the real app boots with — demo users, default
    permission matrix, starting faculties/buildings.

    Real vaqt rejimi testlari uchun (``daily_mode`` belgisi yo'q) eski
    kriteriyalar (3, 20, 26) ham qo'shiladi — tests/legacy_modules.py."""
    await seed_all(db_session)
    if not request.node.get_closest_marker("daily_mode"):
        await seed_legacy_modules(db_session)


async def seed_legacy_modules(db: AsyncSession) -> None:
    from sqlalchemy import select

    from app.models import AIModuleConfig
    from tests.legacy_modules import LEGACY_AI_MODULES, LEGACY_TRIAL_CODES

    existing = set((await db.execute(select(AIModuleConfig.code))).scalars().all())
    for module in LEGACY_AI_MODULES:
        if module["code"] not in existing:
            db.add(AIModuleConfig(**module, mode="sinov" if module["code"] in LEGACY_TRIAL_CODES else "ishchi"))
    await db.commit()


async def login(client: AsyncClient, login_name: str, password: str) -> str:
    resp = await client.post("/api/auth/login", json={"login": login_name, "password": password})
    resp.raise_for_status()
    return resp.json()["token"]


async def auth_headers(client: AsyncClient, login_name: str, password: str) -> dict[str, str]:
    token = await login(client, login_name, password)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _calendar_day_is_the_business_day(request, monkeypatch):
    """Ish kuni 06:00 da boshlanadi: 00:00–05:59 da "bugun" ikki xil —
    business_today() kechagi, local_now().date() esa bugungi kalendar
    sanasi. Testlar ikkalasini aralash ishlatadi va to'plam faqat tunda
    yiqilardi. Shu oraliqda test uchun kun chegarasi 00:00 ga suriladi —
    ikkala sana bir xil bo'ladi.

    06:00 chegarasining o'zini tekshiradigan testlar (`six_am_day`)
    doim haqiqiy 06:00 bilan ishlaydi: ular aniq sanalar bilan yozilgan,
    joriy soatga bog'liq emas."""
    from app.config import settings
    from app.timezone import business_today, local_now

    if request.node.get_closest_marker("six_am_day"):
        monkeypatch.setattr(settings, "day_start_hour", 6)
        return
    if business_today() != local_now().date():
        monkeypatch.setattr(settings, "day_start_hour", 0)


@pytest.fixture(autouse=True)
def _today_is_a_work_day(request, _calendar_day_is_the_business_day):
    """Ko'p testlar "bugun"ni ish kuni deb kutadi (kutilmoqda, kech keldi).
    Standart qoidada yakshanba — dam olish, shuning uchun yakshanba kuni
    ishga tushirilgan to'plam tasodifan yiqilardi. Bugun ish kuni bo'lmasa —
    test davomida hamma kun ish kuni.

    `default_policy` belgili testlar standart qoidaning o'zini (yakshanba —
    dam olish) tekshiradi — ularga tegilmaydi."""
    from app.services import attendance_policy as ap
    from app.services.attendance_policy import Policy, set_cached
    from app.timezone import business_today

    # Har test toza keshdan boshlanadi: oldingi test o'rnatgan (yoki bazadan
    # yuklagan) qoida keyingisiga o'tib, natija testlar tartibiga bog'liq
    # bo'lib qolmasin. _loaded_at=0 — kerak bo'lsa load_policy bazadan o'qiydi.
    ap._cached, ap._loaded_at = Policy(), 0.0
    if request.node.get_closest_marker("default_policy"):
        # Aynan standart qoida — bazadagi qator ham o'qilmaydi.
        set_cached(Policy())
    elif not Policy().is_work_day(business_today()):
        set_cached(Policy(work_days=(1, 2, 3, 4, 5, 6, 7)))
    yield
    ap._cached, ap._loaded_at = Policy(), 0.0


@pytest.fixture(autouse=True)
def _no_hemis_identity_check(monkeypatch):
    """Shaxsni HEMIS surati bilan tekshirish tashqi HEMIS serverini so'raydi —
    testlarda standart bo'yicha o'chiq; test_identity_check.py uni o'zi yoqadi."""
    from app.config import settings

    monkeypatch.setattr(settings, "self_enrollment_identity_check", False)


@pytest.fixture(autouse=True)
def _admin_2fa_optional(monkeypatch):
    """Test hisoblari (admin/admin123) 2FA siz — majburiy 2FA faqat
    test_admin_2fa.py da yoqiladi."""
    from app.config import settings

    monkeypatch.setattr(settings, "admin_2fa_required", False)


@pytest.fixture(autouse=True)
def _realtime_mode_for_legacy_tests(request, monkeypatch):
    """Standart rejim endi kunlik video tahlil (settings.analysis_mode).
    Eski testlar real vaqt yo'lini (jonli ramka, sweeplar) tekshiradi —
    ular uchun rejim "realtime". `daily_mode` belgili testlar kunlik
    rejimning o'zini tekshiradi."""
    from app.config import settings

    if request.node.get_closest_marker("daily_mode"):
        monkeypatch.setattr(settings, "analysis_mode", "kunlik")
    else:
        monkeypatch.setattr(settings, "analysis_mode", "realtime")
