"""AIModuleConfig.threshold used to be write-only: the admin panel saved
it, the admin panel read it back, and no detection code ever consulted
it. The production audit that prompted this found every event of modules
1, 5, 17 and 25 sitting BELOW its own module's threshold (134/134,
28/28, 84/84, 4/4) — arithmetically impossible if the setting did
anything.

These tests pin the setting to actually gating events, and pin the two
directions an operator depends on: raise it to silence a noisy module,
lower it to hear one again.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models import AIModuleConfig, Building, Camera, Event
from app.services.event_bus import raise_event


@pytest.fixture
async def camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    cam = Camera(
        name="Chegara test kamerasi",
        ip="10.0.0.77",
        building_id=building.id,
        zone="Z",
        resolution="1080p",
        status="faol",
        last_seen_at=datetime.now(timezone.utc),
    )
    db_session.add(cam)
    await db_session.commit()
    await db_session.refresh(cam, ["building"])
    return cam


async def _set_threshold(db_session, code: int, value: int) -> None:
    module = (
        await db_session.execute(select(AIModuleConfig).where(AIModuleConfig.code == code))
    ).scalar_one()
    module.threshold = value
    await db_session.commit()


async def _fire(db_session, camera, confidence: int):
    return await raise_event(
        db_session,
        camera=camera,
        module_code=17,
        module_name="Tartib-intizom buzilishi",
        group="D",
        confidence=confidence,
        severity="past",
    )


async def _event_count(db_session) -> int:
    return len((await db_session.execute(select(Event))).scalars().all())


@pytest.mark.usefixtures("seeded")
class TestModuleThresholdGatesEvents:
    async def test_detection_below_threshold_is_dropped(self, db_session, camera):
        await _set_threshold(db_session, 17, 65)
        assert await _fire(db_session, camera, 55) is None
        assert await _event_count(db_session) == 0

    async def test_detection_at_threshold_is_kept(self, db_session, camera):
        """Boundary matters: an operator who sets 70 and gets a 70 back
        expects to see it. The comparison is `<`, not `<=`."""
        await _set_threshold(db_session, 17, 70)
        assert await _fire(db_session, camera, 70) is not None
        assert await _event_count(db_session) == 1

    async def test_detection_above_threshold_is_kept(self, db_session, camera):
        await _set_threshold(db_session, 17, 50)
        assert await _fire(db_session, camera, 55) is not None
        assert await _event_count(db_session) == 1

    async def test_raising_the_threshold_silences_a_constant_confidence_module(
        self, db_session, camera
    ):
        """Several modules report a fixed confidence (55 here — a coarse
        whole-frame motion heuristic). For those the threshold is an
        on/off switch, not a dial, and that is exactly how an operator
        drowning in one module's noise will use it."""
        await _set_threshold(db_session, 17, 50)
        assert await _fire(db_session, camera, 55) is not None
        await _set_threshold(db_session, 17, 56)
        assert await _fire(db_session, camera, 55) is None
        assert await _event_count(db_session) == 1

    async def test_unknown_module_code_is_not_silently_swallowed(self, db_session, camera):
        """A module with no config row must not become a black hole —
        failing open is right here: losing a detection is worse than
        showing one the operator has not configured yet."""
        event = await raise_event(
            db_session,
            camera=camera,
            module_code=999,
            module_name="Ro'yxatda yo'q modul",
            group="D",
            confidence=1,
            severity="past",
        )
        assert event is not None
