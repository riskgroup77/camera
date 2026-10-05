"""Hodisa ko'rsatmasi (SOP): standart matn, administrator o'zgartirishi,
hodisa javobida qadamlar ro'yxati."""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import AIModuleConfig, AuditLog, Building, Camera, Event, User
from app.security import hash_password
from app.services.sop import DEFAULT_SOP, default_steps, parse_steps, resolve_steps
from tests.conftest import auth_headers

REMOVED_MODULES = {10, 13, 14, 15, 17, 23}


class TestParsing:
    def test_numbering_bullets_and_blank_lines_are_dropped(self):
        assert parse_steps("1. Birinchi\n\n - Ikkinchi\n• Uchinchi\n  ") == ["Birinchi", "Ikkinchi", "Uchinchi"]

    def test_empty_custom_text_falls_back_to_default(self):
        assert resolve_steps(1, None) == default_steps(1)
        assert resolve_steps(1, "  \n ") == default_steps(1)
        assert resolve_steps(1, "Faqat shu") == ["Faqat shu"]

    def test_defaults_are_short_checklists(self):
        for code, text in DEFAULT_SOP.items():
            steps = parse_steps(text)
            assert 3 <= len(steps) <= 5, code
        assert not REMOVED_MODULES & DEFAULT_SOP.keys()
        for code in (1, 2, 3, 20, 22, 26):
            assert code in DEFAULT_SOP

    def test_unknown_module_gets_generic_steps(self):
        assert len(default_steps(999)) >= 3


@pytest.fixture
async def camera(db_session, seeded) -> Camera:
    building = (await db_session.execute(select(Building))).scalars().first()
    row = Camera(name="Koridor-SOP", ip="10.9.0.7", building_id=building.id, zone="Z", resolution="1080p")
    db_session.add(row)
    await db_session.commit()
    return row


async def _event(db_session, camera, module_code: int = 1) -> str:
    event = Event(
        occurred_at=datetime.now(timezone.utc),
        camera_id=camera.id,
        camera_name=camera.name,
        building="1-bino",
        module_code=module_code,
        module_name="Notanish/begona shaxsni aniqlash",
        group="A",
        confidence=80,
        severity="yuqori",
        status="yangi",
    )
    db_session.add(event)
    await db_session.commit()
    return str(event.id)


@pytest.mark.usefixtures("seeded")
class TestApi:
    async def test_event_carries_default_steps(self, client: AsyncClient, db_session, camera):
        event_id = await _event(db_session, camera)
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get(f"/api/events/{event_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["sop"] == default_steps(1)

        listed = await client.get("/api/events", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["items"][0]["sop"] == default_steps(1)

    async def test_admin_edits_and_resets_sop(self, client: AsyncClient, db_session, camera):
        event_id = await _event(db_session, camera)
        headers = await auth_headers(client, "admin", "admin123")

        resp = await client.put("/api/ai-modules/1/sop", headers=headers, json={"steps": ["Kadrni ko'ring", " ", "Qo'riqchini chaqiring"]})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["steps"] == ["Kadrni ko'ring", "Qo'riqchini chaqiring"]
        assert body["custom"] is True
        assert body["defaultSteps"] == default_steps(1)

        module = (await db_session.execute(select(AIModuleConfig).where(AIModuleConfig.code == 1))).scalar_one()
        await db_session.refresh(module)
        assert module.sop == "Kadrni ko'ring\nQo'riqchini chaqiring"

        event = await client.get(f"/api/events/{event_id}", headers=headers)
        assert event.json()["sop"] == ["Kadrni ko'ring", "Qo'riqchini chaqiring"]

        actions = (await db_session.execute(select(AuditLog.action))).scalars().all()
        assert any("ko'rsatmasini o'zgartirdi" in a for a in actions)

        reset = await client.put("/api/ai-modules/1/sop", headers=headers, json={"steps": []})
        assert reset.status_code == 200
        assert reset.json()["custom"] is False
        await db_session.refresh(module)
        assert module.sop is None

    async def test_camera_steward_cannot_edit(self, client: AsyncClient, db_session):
        db_session.add(
            User(login="kamera-sop", password_hash=hash_password("kamera-parol-123"), full_name="K M", role="kamera-masuli")
        )
        await db_session.commit()
        headers = await auth_headers(client, "kamera-sop", "kamera-parol-123")
        resp = await client.put("/api/ai-modules/20/sop", headers=headers, json={"steps": ["x"]})
        assert resp.status_code == 403

    async def test_live_broadcast_carries_custom_steps(self, db_session, camera, monkeypatch):
        from app.services import event_bus

        sent: list[dict] = []

        async def capture(message: dict) -> None:
            sent.append(message)

        async def no_notify(event) -> None:
            return None

        monkeypatch.setattr(event_bus.manager, "broadcast", capture)
        monkeypatch.setattr(event_bus, "notify_event", no_notify)
        module = (await db_session.execute(select(AIModuleConfig).where(AIModuleConfig.code == 2))).scalar_one()
        module.sop = "Zonani tekshiring\nQo'riqchini yuboring"
        module.mode = "ishchi"
        await db_session.commit()
        loaded = (
            await db_session.execute(select(Camera).options(selectinload(Camera.building)).where(Camera.id == camera.id))
        ).scalar_one()

        event = await event_bus.raise_event(
            db_session,
            camera=loaded,
            module_code=2,
            module_name="Taqiqlangan zonaga kirish",
            group="A",
            confidence=99,
            severity="yuqori",
            person_name="Karimov Aziz",
        )
        assert event is not None
        assert sent and sent[0]["sop"] == ["Zonani tekshiring", "Qo'riqchini yuboring"]

    async def test_limits_and_unknown_module(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        too_many = await client.put("/api/ai-modules/1/sop", headers=headers, json={"steps": ["a"] * 11})
        assert too_many.status_code == 422
        assert (await client.get("/api/ai-modules/424242/sop", headers=headers)).status_code == 404
