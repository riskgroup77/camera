"""Operator ko'radigan signallar doirasi (app/services/event_scope.py).

Devordagi signal paneli avtomatik o'chirilgan kameraning eski
signallarini, navbat va statistika esa olib tashlangan kriteriyalarning
(#25 va h.k.) signallarini ko'rsatib kelardi.
"""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Building, Camera, Event, ModuleCameraSuppression
from tests.conftest import auth_headers

RETIRED_MODULE = 25  # olib tashlangan kriteriya — AIModuleConfig'da yo'q


@pytest.fixture
async def world(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    noisy = Camera(name="Shovqinli kamera", ip="10.0.3.1", building_id=building.id, zone="Hovli",
                   resolution="1080p", status="faol")
    quiet = Camera(name="Tinch kamera", ip="10.0.3.2", building_id=building.id, zone="Kirish",
                   resolution="1080p", status="faol")
    db_session.add_all([noisy, quiet])
    await db_session.commit()
    db_session.add(ModuleCameraSuppression(camera_id=noisy.id, module_code=21, reason="aniqlik past"))

    def event(camera, code, **extra):
        return Event(camera_id=camera.id, camera_name=camera.name, building=building.name, module_code=code,
                     module_name=f"#{code}", group="D", confidence=80, severity="yuqori", **extra)

    db_session.add_all([
        event(noisy, 21),  # o'chirilgan juftlik
        event(noisy, 1),  # shu kamera, boshqa modul — ko'rinadi
        event(quiet, 21),  # boshqa kamera, shu modul — ko'rinadi
        event(quiet, RETIRED_MODULE),  # olib tashlangan kriteriya
        event(quiet, 17, is_trial=True),  # sinov signali
    ])
    await db_session.commit()
    return noisy, quiet


def _pairs(page: dict) -> set[tuple[str, int]]:
    return {(item["cameraName"], item["moduleCode"]) for item in page["items"]}


class TestWallAlarms:
    async def test_the_suppressed_pair_is_left_out_on_request(self, client: AsyncClient, world):
        headers = await auth_headers(client, "admin", "admin123")

        wall = await client.get("/api/events", headers=headers, params={"severity": "yuqori", "excludeSuppressed": "true"})
        journal = await client.get("/api/events", headers=headers, params={"severity": "yuqori"})

        assert _pairs(wall.json()) == {("Shovqinli kamera", 1), ("Tinch kamera", 21)}
        # Hodisalar jurnalida tarix to'liq qoladi.
        assert _pairs(journal.json()) == {("Shovqinli kamera", 21), ("Shovqinli kamera", 1), ("Tinch kamera", 21)}

    async def test_a_restored_pair_shows_again(self, client: AsyncClient, db_session, world):
        suppression = (await db_session.execute(select(ModuleCameraSuppression))).scalar_one()
        suppression.restored_at = datetime.now(timezone.utc)
        await db_session.commit()
        headers = await auth_headers(client, "admin", "admin123")

        wall = await client.get("/api/events", headers=headers, params={"severity": "yuqori", "excludeSuppressed": "true"})

        assert ("Shovqinli kamera", 21) in _pairs(wall.json())

    async def test_retired_criteria_never_reach_the_queue(self, client: AsyncClient, world):
        headers = await auth_headers(client, "admin", "admin123")
        page = await client.get("/api/events", headers=headers, params={"pageSize": 50})
        assert RETIRED_MODULE not in {item["moduleCode"] for item in page.json()["items"]}

    async def test_the_wall_header_counts_the_same_signals(self, client: AsyncClient, world):
        headers = await auth_headers(client, "admin", "admin123")
        stats = await client.get("/api/public/stats", headers=headers)
        assert stats.status_code == 200, stats.text
        # 5 ta yozuvdan: o'chirilgan juftlik, olib tashlangan kriteriya va sinov signali sanalmaydi.
        assert stats.json()["violations"] == 2
