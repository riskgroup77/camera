"""P0 tests — lesson CSV import defaults and non-blocking PPE detection."""

import numpy as np
import pytest
from httpx import AsyncClient

from app.services import ppe_detection
from tests.conftest import auth_headers


class TestPpeDetectionAsync:
    async def test_detect_ppe_runs_off_event_loop(self, monkeypatch):
        calls: list[str] = []

        def fake_sync(image, face_bbox):
            calls.append("sync")
            return True

        async def fake_to_thread(fn, *args):
            calls.append("thread")
            return fn(*args)

        monkeypatch.setattr(ppe_detection, "detect_ppe_sync", fake_sync)
        monkeypatch.setattr(ppe_detection.asyncio, "to_thread", fake_to_thread)

        image = np.zeros((64, 64, 3), dtype=np.uint8)
        result = await ppe_detection.detect_ppe(image, (0.0, 0.0, 10.0, 10.0))

        assert result is True
        assert calls == ["thread", "sync"]


@pytest.mark.usefixtures("seeded")
class TestLessonImportDefaults:
    async def test_csv_import_sets_required_score_columns(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        csv_body = (
            "date,group,faculty,subject\n"
            "2026-10-01,201-guruh,Davolash ishi,Patologiya\n"
        ).encode("utf-8")
        resp = await client.post(
            "/api/lesson-sessions/import",
            headers=headers,
            files={"file": ("lessons.csv", csv_body, "text/csv")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["imported"] == 1
        assert body["errors"] == []

        listed = await client.get("/api/lesson-sessions", headers=headers)
        assert listed.status_code == 200
        row = next(item for item in listed.json()["items"] if item["subject"] == "Patologiya")
        assert row["attentionScore"] == 50
        assert row["teacherActivityScore"] == 50
