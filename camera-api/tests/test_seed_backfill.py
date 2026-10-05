"""Yangi bazada migratsiyalar huquq va AI modul jadvallariga bir nechta
qatorni o'zlari yozadi. Seed "jadval bo'shmi?" deb tekshirganda qolganlari
hech qachon yaratilmasdi — Super Admin yarim menyuni ko'rardi."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIModuleConfig, Permission
from app.seed import DEFAULT_AI_MODULES, DEFAULT_PERMISSIONS, seed_all


async def test_missing_permissions_are_backfilled_without_touching_existing(db_session: AsyncSession) -> None:
    # Migratsiya yozgan holat: bitta kalit, admin uni o'zgartirgan.
    db_session.add(Permission(key="reviewEvents", super_admin=True, admin=False, camera_steward=True))
    await db_session.commit()

    await seed_all(db_session)

    rows = {p.key: p for p in (await db_session.execute(select(Permission))).scalars()}
    assert set(rows) == set(DEFAULT_PERMISSIONS)
    # Mavjud qator o'zgarmagan.
    assert rows["reviewEvents"].admin is False
    assert rows["reviewEvents"].camera_steward is True
    assert rows["viewLive"].super_admin is True


async def test_missing_ai_modules_are_backfilled_without_touching_existing(db_session: AsyncSession) -> None:
    first = DEFAULT_AI_MODULES[0]
    db_session.add(AIModuleConfig(**{**first, "active": False}, mode="ishchi"))
    await db_session.commit()

    await seed_all(db_session)

    codes = set((await db_session.execute(select(AIModuleConfig.code))).scalars())
    assert codes == {m["code"] for m in DEFAULT_AI_MODULES}
    kept = await db_session.scalar(select(AIModuleConfig).where(AIModuleConfig.code == first["code"]))
    assert kept.active is False
