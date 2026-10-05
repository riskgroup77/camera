"""Talabalar kesimi: fakultet -> kurs -> guruh, guruhlar ro'yxati va guruh sahifasi."""

from datetime import timedelta

import pytest
from httpx import AsyncClient

from app.services.situation import hm
from tests.conftest import auth_headers
from tests.situation_world import _situation_settings, world  # noqa: F401 — pytest fikstura


@pytest.fixture
async def admin(client: AsyncClient, world):
    return await auth_headers(client, "operator", "operator123")


def _stats(row):
    return {k: row[k] for k in ("total", "enrolled", "present", "late", "absent", "notYet", "noData", "rate")}


class TestFacultyDetail:
    async def test_courses_and_groups_with_rates(self, client, world, admin):
        body = (await client.get(f"/api/situation/faculties/{world.di.id}", headers=admin)).json()
        assert body["name"] == "Davolash ishi" and body["id"] == str(world.di.id)
        assert body["totals"]["total"] == 8 and body["totals"]["present"] == 5

        courses = {c["course"]: c for c in body["courses"]}
        assert [c["course"] for c in body["courses"]] == [2, 3, 4]
        assert courses[2]["label"] == "2-kurs"

        groups = {g["name"]: g for g in courses[2]["groups"]}
        assert list(groups) == ["DI-2301", "DI-2302", "DI-2303"]
        assert _stats(groups["DI-2301"]) == {
            "total": 5, "enrolled": 4, "present": 2, "late": 1, "absent": 1, "notYet": 1, "noData": 1, "rate": 50.0,
        }
        assert groups["DI-2301"]["curator"] is None
        assert groups["DI-2301"]["facultyId"] == str(world.di.id)
        assert groups["DI-2302"]["rate"] == 100.0
        # Faqat StudentGroup jadvalida bor, talabasi yo'q guruh ham ko'rinadi.
        assert groups["DI-2303"]["total"] == 0 and groups["DI-2303"]["rate"] is None
        assert _stats(courses[2]["totals"])["rate"] == 60.0
        assert courses[2]["totals"]["total"] == 6

        # "4-kurs" (guruhsiz) talaba kurs jamida bor, guruh sifatida emas.
        assert courses[4]["groups"] == [] and courses[4]["totals"]["present"] == 1
        # Boshqa fakultetdagi "XDI-2301" bu yerga tushmaydi.
        assert all(g["name"] != "XDI-2301" for c in body["courses"] for g in c["groups"])

    async def test_unknown_faculty_is_404(self, client, world, admin):
        assert (await client.get("/api/situation/faculties/not-a-uuid", headers=admin)).status_code == 404
        missing = "00000000-0000-0000-0000-000000000000"
        assert (await client.get(f"/api/situation/faculties/{missing}", headers=admin)).status_code == 404


class TestGroupsList:
    async def test_flat_list_sorted_by_name(self, client, world, admin):
        rows = (await client.get("/api/situation/groups", headers=admin)).json()
        assert [r["name"] for r in rows] == ["DI-2101", "DI-2301", "DI-2302", "DI-2303", "PE-2501", "XDI-2301", "XX-1"]
        by_name = {r["name"]: r for r in rows}
        assert by_name["PE-2501"]["faculty"] == "Pediatriya" and by_name["PE-2501"]["course"] == 1
        assert by_name["XX-1"]["facultyId"] is None
        assert by_name["DI-2101"]["course"] == 3

    async def test_filters(self, client, world, admin):
        async def names(**params):
            resp = await client.get("/api/situation/groups", params=params, headers=admin)
            assert resp.status_code == 200
            return [r["name"] for r in resp.json()]

        assert await names(facultyId=str(world.di.id)) == ["DI-2101", "DI-2301", "DI-2302", "DI-2303"]
        assert await names(course=2) == ["DI-2301", "DI-2302", "DI-2303", "XDI-2301"]
        assert await names(search="2301") == ["DI-2301", "XDI-2301"]
        assert await names(search="pe-25") == ["PE-2501"]
        assert await names(facultyId=str(world.pe.id), course=1) == ["PE-2501"]


class TestGroupDetail:
    async def test_face_grid_statuses(self, client, world, admin):
        body = (await client.get("/api/situation/groups/DI-2301", headers=admin)).json()
        group = body["group"]
        assert group["name"] == "DI-2301" and group["course"] == 2
        assert group["facultyId"] == str(world.di.id) and group["faculty"] == "Davolash ishi"
        assert _stats(group["totals"])["rate"] == 50.0

        students = body["students"]
        # Nofaol talaba va "XDI-2301" dagi Komilov ro'yxatda yo'q.
        assert [s["fullName"] for s in students] == [
            "Aliyev Anvar", "Botirova Nigora", "Choriyev Sardor", "Davronov Jasur", "Ergasheva Laylo",
        ]
        assert [s["status"] for s in students] == ["keldi", "kech_keldi", "kelmadi", "kutilmoqda", "malumot_yoq"]
        assert students[0]["checkIn"] == "08:05" and students[0]["initials"] == "AA"
        assert students[0]["photoUrl"] and students[1]["photoUrl"] is None
        assert students[4]["biometricsStatus"] == "yoq"

    async def test_lessons_today(self, client, world, admin):
        lessons = (await client.get("/api/situation/groups/DI-2301", headers=admin)).json()["lessons"]
        assert [l["id"] for l in lessons] == [str(world.l1.id), str(world.l2.id)]
        l1, l2 = lessons

        assert l1["state"] == "finished" and l1["finalized"] is True
        assert (l1["expected"], l1["present"], l1["late"], l1["absent"]) == (4, 2, 1, 2)
        assert l1["teacherStatus"] == "oz_vaqtida" and l1["teacherOnTime"] is True
        assert l1["teacherId"] == str(world.people.yusupova.id) and l1["teacherPhotoUrl"]
        assert l1["room"] == "205-xona" and l1["building"] == world.building.name
        assert l1["startsAt"] == hm(world.l1.scheduled_start_time)
        assert l1["endsAt"] == hm(world.l1.scheduled_start_time + timedelta(minutes=80))
        assert (l1["attentionScore"], l1["activityScore"]) == (80, 70)

        # Davom etayotgan dars: faqat ishonchli ko'ringanlar (>= 3 marta),
        # "kelmadi" hali noma'lum.
        assert l2["state"] == "ongoing" and l2["finalized"] is False
        assert (l2["present"], l2["late"], l2["absent"], l2["seen"]) == (2, 1, None, 2)
        assert l2["teacherStatus"] == "kechikdi"
        assert l2["attentionScore"] is None  # o'lchanmagan — 0 emas

    async def test_fourteen_day_trend(self, client, world, admin):
        trend = (await client.get("/api/situation/groups/DI-2301", headers=admin)).json()["trend"]
        assert len(trend) == 14
        assert trend[-1] == {"date": world.today.isoformat(), "rate": 50.0, "present": 2, "late": 1, "absent": 1}
        assert trend[-2] == {"date": world.yesterday.isoformat(), "rate": 33.3, "present": 1, "late": 0, "absent": 2}
        assert all(p["rate"] is None for p in trend[:-2])

    async def test_group_known_only_from_registry(self, client, world, admin):
        body = (await client.get("/api/situation/groups/DI-2303", headers=admin)).json()
        assert body["students"] == [] and body["group"]["course"] == 2
        assert body["group"]["faculty"] == "Davolash ishi"

    async def test_past_date_and_unknown_group(self, client, world, admin):
        body = (
            await client.get("/api/situation/groups/DI-2301", params={"date": world.yesterday.isoformat()}, headers=admin)
        ).json()
        assert [s["status"] for s in body["students"]] == ["keldi", "kelmadi", "kelmadi", "malumot_yoq", "malumot_yoq"]
        assert [l["id"] for l in body["lessons"]] == [str(world.ly.id)]
        assert body["lessons"][0]["teacherStatus"] == "kelmadi"

        assert (await client.get("/api/situation/groups/NOPE-1", headers=admin)).status_code == 404
