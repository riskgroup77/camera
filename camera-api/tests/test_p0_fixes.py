"""P0 tests — lesson CSV import defaults."""

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers


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
        # NOT NULL ustunlar to'ldirilgan (import yiqilmaydi), lekin dars hali
        # o'tmagan — ko'rsatkichlar "o'lchanmagan", soxta 50% emas.
        assert row["attentionScore"] is None
        assert row["teacherActivityScore"] is None
        assert row["teacherOnTime"] is None
