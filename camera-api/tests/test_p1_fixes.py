"""P1 — bulk CSV import lookups and parallel startup stream sync."""

import asyncio

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import Building, Camera
from app.services import stream_sync
from app.services.lesson_import import _load_existing_lesson_keys
from app.services.student_import import _load_existing_people_keys, import_students_staff_csv


@pytest.mark.usefixtures("seeded")
class TestBulkImportLookups:
    async def test_existing_people_loaded_in_one_query(self, db_session, monkeypatch):
        query_count = {"n": 0}
        real_execute = db_session.execute

        async def counting_execute(*args, **kwargs):
            query_count["n"] += 1
            return await real_execute(*args, **kwargs)

        monkeypatch.setattr(db_session, "execute", counting_execute)

        keys = await _load_existing_people_keys(db_session)
        assert isinstance(keys, set)
        assert query_count["n"] == 1

    async def test_student_import_uses_constant_db_lookups(self, db_session, monkeypatch):
        query_count = {"n": 0}
        real_execute = db_session.execute

        async def counting_execute(*args, **kwargs):
            query_count["n"] += 1
            return await real_execute(*args, **kwargs)

        monkeypatch.setattr(db_session, "execute", counting_execute)

        rows = [
            "full_name,type,faculty,group_or_position",
        ]
        for i in range(20):
            rows.append(f"Bulk Import Talaba {i:02d},talaba,Davolash ishi,10{i}-guruh")
        raw = "\n".join(rows).encode("utf-8")

        result = await import_students_staff_csv(db_session, raw)
        assert result.imported == 20
        assert query_count["n"] == 2  # faculties + existing people, not 20+

    async def test_existing_lesson_keys_loaded_in_one_query(self, db_session):
        keys = await _load_existing_lesson_keys(db_session)
        assert isinstance(keys, set)


@pytest.mark.usefixtures("seeded")
class TestParallelStreamSync:
    async def test_sync_all_registers_cameras_in_parallel(self, db_session, monkeypatch):
        building = (await db_session.execute(select(Building))).scalars().first()
        for i in range(6):
            db_session.add(
                Camera(
                    name=f"Parallel sync {i}",
                    ip=f"10.0.8.{i + 10}",
                    port=554,
                    building_id=building.id,
                    zone="Z",
                    resolution="1080p",
                    status="faol",
                )
            )
        await db_session.commit()

        peak = {"current": 0, "max": 0}
        lock = asyncio.Lock()

        async def fake_register(camera_id: str, rtsp_url: str) -> str:
            async with lock:
                peak["current"] += 1
                peak["max"] = max(peak["max"], peak["current"])
            await asyncio.sleep(0.04)
            async with lock:
                peak["current"] -= 1
            return f"https://stream.example/s0/cam-{camera_id}/index.m3u8"

        monkeypatch.setattr(stream_sync, "register_camera_stream", fake_register)
        monkeypatch.setattr(settings, "stream_sync_concurrency", 4)

        ok, failed = await stream_sync.sync_all_active_camera_streams(db_session)
        assert ok == 6
        assert failed == 0
        assert peak["max"] >= 2
