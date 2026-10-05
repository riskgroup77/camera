import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Event, StudentStaff
from app.services.inference_gate import PRIORITY_BACKGROUND, PRIORITY_LIVE, PriorityInferenceGate
from tests.conftest import auth_headers


class TestInferencePriorityGate:
    async def test_high_priority_jumps_queue(self):
        gate = PriorityInferenceGate(1)
        order: list[str] = []
        gate_open = asyncio.Event()

        async def holder():
            async with gate.slot(priority=PRIORITY_BACKGROUND):
                order.append("holder_start")
                await gate_open.wait()
                order.append("holder_end")

        async def low():
            async with gate.slot(priority=PRIORITY_BACKGROUND):
                order.append("low")

        async def high():
            async with gate.slot(priority=PRIORITY_LIVE):
                order.append("high")

        holder_task = asyncio.create_task(holder())
        await asyncio.sleep(0.02)
        low_task = asyncio.create_task(low())
        high_task = asyncio.create_task(high())
        await asyncio.sleep(0.02)
        gate_open.set()
        await asyncio.gather(holder_task, low_task, high_task)
        assert order.index("high") < order.index("low")


@pytest.mark.usefixtures("seeded")
class TestStudentStaffImport:
    async def test_csv_import_creates_rows(self, client: AsyncClient, db_session):
        headers = await auth_headers(client, "admin", "admin123")
        faculty = "Davolash ishi"
        csv_body = (
            "full_name,type,faculty,group_or_position\n"
            f"Import Test Talaba,talaba,{faculty},101-guruh\n"
            f"Import Test Xodim,xodim,{faculty},Assistent\n"
        ).encode("utf-8")
        resp = await client.post(
            "/api/students-staff/import",
            headers=headers,
            files={"file": ("people.csv", csv_body, "text/csv")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["imported"] == 2
        assert body["skipped"] == 0
        assert body["errors"] == []

        names = (
            await db_session.execute(
                select(StudentStaff.full_name).where(StudentStaff.full_name.like("Import Test%"))
            )
        ).scalars().all()
        assert len(names) == 2

    async def test_csv_import_skips_duplicate(self, client: AsyncClient, db_session):
        headers = await auth_headers(client, "admin", "admin123")
        faculty = "Davolash ishi"
        csv_body = (
            "full_name,type,faculty,group_or_position\n"
            f"Duplicate Person,talaba,{faculty},102-guruh\n"
        ).encode("utf-8")
        await client.post(
            "/api/students-staff/import",
            headers=headers,
            files={"file": ("people.csv", csv_body, "text/csv")},
        )
        resp = await client.post(
            "/api/students-staff/import",
            headers=headers,
            files={"file": ("people.csv", csv_body, "text/csv")},
        )
        assert resp.json()["imported"] == 0
        assert resp.json()["skipped"] == 1


@pytest.mark.usefixtures("seeded")
class TestEventRetention:
    async def test_cleanup_deletes_old_events(self, db_session):
        from datetime import datetime, timedelta, timezone

        from app.jobs.cleanup import run_cleanup_once
        from app.models import Building, Camera

        building = (await db_session.execute(select(Building))).scalars().first()
        camera = Camera(
            name="Eski hodisa kamerasi",
            ip="10.0.0.77",
            building_id=building.id,
            zone="Z",
            resolution="1080p",
            status="faol",
        )
        db_session.add(camera)
        await db_session.flush()
        old = Event(
            camera_id=camera.id,
            camera_name=camera.name,
            building=building.name,
            module_code=17,
            module_name="Test",
            group="D",
            confidence=50,
            severity="past",
            status="yangi",
            occurred_at=datetime.now(timezone.utc) - timedelta(days=400),
        )
        db_session.add(old)
        await db_session.commit()

        counts = await run_cleanup_once(db_session)
        assert counts["events"] >= 1

        remaining = (
            await db_session.execute(select(Event).where(Event.module_code == 17))
        ).scalars().all()
        assert remaining == []
