"""Xodimlar kesimi: kafedralar ro'yxati va kafedra sahifasi (o'qituvchilar)."""

from datetime import timedelta

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers
from tests.situation_world import _situation_settings, world  # noqa: F401 — pytest fikstura


@pytest.fixture
async def admin(client: AsyncClient, world):
    return await auth_headers(client, "operator", "operator123")


class TestKafedras:
    async def test_staff_matched_by_name_case_and_space_insensitive(self, client, world, admin):
        rows = (await client.get("/api/situation/kafedras", headers=admin)).json()
        assert [r["name"] for r in rows] == [
            "Anatomiya kafedrasi", "Fiziologiya kafedrasi", "Lavozim bo'yicha (bo'linmasi ko'rsatilmagan)",
        ]
        assert [r["kind"] for r in rows] == ["kafedra", "kafedra", "lavozim"]
        anatomy, physiology, unassigned = rows

        # Karimov "  anatomiya   KAFEDRASI " deb yozilgan — baribir Anatomiyada.
        # Nofaol xodim hisobga kirmaydi.
        assert anatomy["id"] == str(world.anatomy.id) and anatomy["building"] == world.building.name
        assert (anatomy["staffTotal"], anatomy["enrolled"], anatomy["present"], anatomy["late"]) == (2, 2, 2, 1)
        assert anatomy["rate"] == 100.0
        # L1 (Yusupova), L3 va L4 (Karimov); L5 ning teacher_id si yo'q.
        assert (anatomy["lessonsToday"], anatomy["teacherLateLessons"], anatomy["teacherMissedLessons"]) == (3, 1, 0)
        assert anatomy["unassigned"] is False

        assert physiology["building"] is None
        assert (physiology["staffTotal"], physiology["notYet"], physiology["rate"]) == (1, 1, 0.0)
        assert (physiology["lessonsToday"], physiology["teacherLateLessons"], physiology["teacherMissedLessons"]) == (
            2, 1, 1,
        )

        assert unassigned["id"] == "unassigned" and unassigned["unassigned"] is True
        assert (unassigned["staffTotal"], unassigned["enrolled"], unassigned["noData"], unassigned["rate"]) == (
            1, 0, 1, None,
        )

    async def test_no_unassigned_row_when_everyone_matches(self, client, world, admin, db_session):
        world.people.qodirova.active = False
        await db_session.commit()
        rows = (await client.get("/api/situation/kafedras", headers=admin)).json()
        assert [r["id"] for r in rows] == [str(world.anatomy.id), str(world.physiology.id)]


class TestKafedraDetail:
    async def test_teachers_today_and_period(self, client, world, admin):
        body = (await client.get(f"/api/situation/kafedras/{world.anatomy.id}", headers=admin)).json()
        assert body["name"] == "Anatomiya kafedrasi" and body["unassigned"] is False
        assert body["today"]["total"] == 2 and body["today"]["rate"] == 100.0

        karimov, yusupova = body["teachers"]
        assert karimov["fullName"] == "Karimov Aziz Olimovich"
        assert karimov["position"] == "  anatomiya   KAFEDRASI "
        assert (karimov["status"], karimov["checkIn"]) == ("kech_keldi", "09:20")
        # L3 hali boshlanmagan, L4 ga kechikdi.
        assert (karimov["lessonsScheduled"], karimov["lessonsOnTime"], karimov["lessonsLate"],
                karimov["lessonsMissed"]) == (2, 0, 1, 0)
        assert karimov["onTimeRate"] == 0.0 and karimov["avgActivityScore"] is None
        assert (karimov["periodPresentDays"], karimov["periodLateDays"]) == (1, 1)

        assert (yusupova["status"], yusupova["checkIn"], yusupova["checkOut"]) == ("keldi", "07:55", "17:00")
        assert yusupova["photoUrl"] and yusupova["initials"] == "YD"
        assert (yusupova["lessonsScheduled"], yusupova["lessonsOnTime"]) == (1, 1)
        # Davr: bugungi L1 (o'z vaqtida) + kechagi LY (kelmadi).
        assert (yusupova["periodLessons"], yusupova["periodOnTime"], yusupova["periodMissed"]) == (2, 1, 1)
        assert yusupova["onTimeRate"] == 50.0 and yusupova["avgActivityScore"] == 70.0
        assert yusupova["periodPresentDays"] == 2

        period = body["period"]
        assert period["dateTo"] == world.today.isoformat()
        assert period["dateFrom"] == (world.today - timedelta(days=29)).isoformat()
        assert {k: period[k] for k in ("lessons", "onTime", "late", "missed", "unknown", "onTimeRate")} == {
            "lessons": 4, "onTime": 1, "late": 1, "missed": 1, "unknown": 1, "onTimeRate": 33.3,
        }
        assert (period["presentDays"], period["lateDays"], period["absentDays"]) == (3, 1, 0)

    async def test_custom_period(self, client, world, admin):
        day = world.yesterday.isoformat()
        body = (
            await client.get(f"/api/situation/kafedras/{world.anatomy.id}",
                             params={"date": day, "from": day, "to": day}, headers=admin)
        ).json()
        yusupova = next(t for t in body["teachers"] if t["fullName"].startswith("Yusupova"))
        assert (yusupova["status"], yusupova["checkIn"]) == ("keldi", "08:00")
        assert (yusupova["periodLessons"], yusupova["periodMissed"], yusupova["onTimeRate"]) == (1, 1, 0.0)
        karimov = next(t for t in body["teachers"] if t["fullName"].startswith("Karimov"))
        assert karimov["status"] == "malumot_yoq" and karimov["periodLessons"] == 0

    async def test_unassigned_pseudo_kafedra(self, client, world, admin):
        body = (await client.get("/api/situation/kafedras/unassigned", headers=admin)).json()
        assert body["id"] == "unassigned" and body["unassigned"] is True
        assert body["name"] == "Lavozim bo'yicha (bo'linmasi ko'rsatilmagan)" and body["kind"] == "lavozim"
        assert [(t["fullName"], t["status"]) for t in body["teachers"]] == [("Qodirova Malika", "malumot_yoq")]

    async def test_errors(self, client, world, admin):
        assert (await client.get("/api/situation/kafedras/xyz", headers=admin)).status_code == 404
        missing = "00000000-0000-0000-0000-000000000000"
        assert (await client.get(f"/api/situation/kafedras/{missing}", headers=admin)).status_code == 404
        resp = await client.get(f"/api/situation/kafedras/{world.anatomy.id}",
                                params={"from": world.today.isoformat(), "to": world.yesterday.isoformat()},
                                headers=admin)
        assert resp.status_code == 422
