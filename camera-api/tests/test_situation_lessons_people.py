"""Darslar ro'yxati (filtrlar, holat, sahifalash) va shaxs sahifasi."""

from datetime import timedelta

import pytest

from app.services.attendance_policy import current_policy
from httpx import AsyncClient

from app.services.situation import hm
from tests.conftest import auth_headers
from tests.situation_world import _situation_settings, world  # noqa: F401 — pytest fikstura

LESSONS = "/api/situation/lessons"


@pytest.fixture
async def admin(client: AsyncClient, world):
    return await auth_headers(client, "operator", "operator123")


async def _ids(client, headers, **params):
    resp = await client.get(LESSONS, params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return [item["id"] for item in resp.json()["items"]]


class TestLessons:
    async def test_all_lessons_of_the_day_by_start_time(self, client, world, admin):
        body = (await client.get(LESSONS, headers=admin)).json()
        order = [world.l6, world.l4, world.l5, world.l1, world.l2, world.l3]
        assert [i["id"] for i in body["items"]] == [str(l.id) for l in order]
        assert body["total"] == 6 and body["date"] == world.today.isoformat()
        assert body["counts"] == {"upcoming": 1, "ongoing": 1, "finished": 4}
        assert [i["teacherStatus"] for i in body["items"]] == [
            "kelmadi", "kechikdi", "nomalum", "oz_vaqtida", "kechikdi", "kutilmoqda",
        ]

    async def test_late_teacher_arrival_comes_from_room_visit(self, client, world, admin):
        items = (await client.get(LESSONS, params={"teacherId": str(world.people.karimov.id)}, headers=admin)).json()["items"]
        assert [i["id"] for i in items] == [str(world.l4.id), str(world.l3.id)]
        l4 = items[0]
        assert l4["teacherArrivedAt"] == hm(world.l4.scheduled_start_time + timedelta(minutes=15))
        assert l4["teacherOnTime"] is None and l4["teacherStatus"] == "kechikdi"
        assert l4["faculty"] == "Pediatriya" and l4["expected"] == 2
        assert (l4["present"], l4["absent"], l4["finalized"]) == (0, None, False)
        assert l4["attentionScore"] == 60

    async def test_filters(self, client, world, admin):
        ids = lambda *ls: [str(l.id) for l in ls]  # noqa: E731
        assert await _ids(client, admin, status="finished") == ids(world.l6, world.l4, world.l5, world.l1)
        assert await _ids(client, admin, status="ongoing") == ids(world.l2)
        assert await _ids(client, admin, status="upcoming") == ids(world.l3)
        assert await _ids(client, admin, facultyId=str(world.pe.id)) == ids(world.l4)
        assert await _ids(client, admin, group="DI-2301") == ids(world.l1, world.l2)
        assert await _ids(client, admin, departmentId=str(world.anatomy.id)) == ids(world.l4, world.l1, world.l3)
        assert await _ids(client, admin, departmentId=str(world.physiology.id), status="finished") == ids(world.l6)
        assert await _ids(client, admin, departmentId="unassigned") == []
        assert await _ids(client, admin, date=world.yesterday.isoformat()) == ids(world.ly)

    async def test_pagination(self, client, world, admin):
        body = (await client.get(LESSONS, params={"page": 2, "pageSize": 4}, headers=admin)).json()
        assert (body["total"], body["page"], body["pageSize"], body["totalPages"]) == (6, 2, 4, 2)
        assert [i["id"] for i in body["items"]] == [str(world.l2.id), str(world.l3.id)]

    async def test_lessons_page_is_open_to_lesson_managers(self, client, world, admin):
        assert (await client.get(LESSONS, params={"status": "later"}, headers=admin)).status_code == 422
        assert (await client.get(LESSONS, params={"facultyId": "x"}, headers=admin)).status_code == 404


class TestPerson:
    async def test_student_profile(self, client, world, admin):
        body = (await client.get(f"/api/situation/people/{world.people.aliyev.id}", headers=admin)).json()
        person = body["person"]
        assert person["fullName"] == "Aliyev Anvar" and person["type"] == "talaba"
        assert (person["group"], person["course"], person["faculty"]) == ("DI-2301", 2, "Davolash ishi")
        assert person["facultyId"] == str(world.di.id) and person["unit"] == "2-kurs, DI-2301"
        assert person["photoUrl"] and person["initials"] == "AA"
        assert person["department"] is None and person["parentNotify"] is False and person["active"] is True

        assert body["dateTo"] == world.today.isoformat()
        calendar = body["calendar"]
        assert len(calendar) == 30
        assert calendar[-1] == {"date": world.today.isoformat(), "status": "keldi", "checkIn": "08:05", "checkOut": None}
        assert calendar[-2]["status"] == "keldi" and calendar[-2]["checkIn"] == "08:15"
        # Yozuvsiz kunlar: ish kuni — "ma'lumot yo'q", yakshanba (ish kuni emas) — "dam olish".
        first = world.today - timedelta(days=29)
        policy = current_policy()
        assert calendar[0]["status"] == ("malumot_yoq" if policy.is_work_day(first) else "dam_olish")
        sundays = sum(1 for i in range(28) if not policy.is_work_day(first + timedelta(days=i)))
        assert body["totals"] == {
            "days": 30, "present": 2, "late": 0, "absent": 0, "dayOff": sundays, "noData": 28 - sundays,
            "rate": 100.0, "avgArrival": "08:10",
        }

        lessons = body["lessons"]
        assert [l["id"] for l in lessons] == [str(world.l2.id), str(world.l1.id), str(world.ly.id)]
        assert lessons[0]["attendanceStatus"] is None
        assert lessons[0]["firstSeen"] == hm(world.l2.scheduled_start_time + timedelta(minutes=1))
        assert lessons[1]["attendanceStatus"] == "keldi"
        assert lessons[2]["attendanceStatus"] is None

        (visit,) = body["recentVisits"]
        assert visit["camera"] == "Kirish-1" and visit["zone"] == "Asosiy kirish"
        assert (visit["date"], visit["firstSeen"], visit["lastSeen"], visit["durationMinutes"]) == (
            world.today.isoformat(), "08:05", "08:07", 2,
        )

    async def test_recent_visits_stay_inside_the_selected_range(self, client, world, admin):
        """Tashriflar "tanlangan davrda qayerda ko'ringan" deb ko'rsatiladi —
        davrdan oldingi tashrif ro'yxatga tushmasligi kerak (ilgari faqat
        yuqori chegara qo'yilgani uchun tushib qolardi)."""
        after = (world.today + timedelta(days=1)).isoformat()
        body = (
            await client.get(f"/api/situation/people/{world.people.aliyev.id}",
                             params={"from": after, "to": after}, headers=admin)
        ).json()
        assert body["recentVisits"] == []

        day = world.today.isoformat()
        same_day = (
            await client.get(f"/api/situation/people/{world.people.aliyev.id}",
                             params={"from": day, "to": day}, headers=admin)
        ).json()
        assert [v["firstSeen"] for v in same_day["recentVisits"]] == ["08:05"]

    async def test_late_and_absent_totals(self, client, world, admin):
        body = (
            await client.get(f"/api/situation/people/{world.people.botirova.id}",
                             params={"from": world.yesterday.isoformat(), "to": world.today.isoformat()},
                             headers=admin)
        ).json()
        assert [d["status"] for d in body["calendar"]] == ["kelmadi", "kech_keldi"]
        totals = body["totals"]
        assert (totals["present"], totals["late"], totals["absent"], totals["rate"]) == (1, 1, 1, 50.0)
        assert body["lessons"][1]["attendanceStatus"] == "kech_keldi"

    async def test_waiting_status_today_only_for_enrolled(self, client, world, admin):
        day = world.today.isoformat()
        waiting = (await client.get(f"/api/situation/people/{world.people.davronov.id}",
                                    params={"from": day, "to": day}, headers=admin)).json()
        assert waiting["calendar"][0]["status"] == "kutilmoqda"
        unknown = (await client.get(f"/api/situation/people/{world.people.ergasheva.id}",
                                    params={"from": day, "to": day}, headers=admin)).json()
        assert unknown["calendar"][0]["status"] == "malumot_yoq"

    async def test_teacher_profile(self, client, world, admin):
        body = (await client.get(f"/api/situation/people/{world.people.karimov.id}", headers=admin)).json()
        person = body["person"]
        assert person["type"] == "xodim" and person["group"] is None and person["course"] is None
        assert (person["departmentId"], person["department"]) == (str(world.anatomy.id), "Anatomiya kafedrasi")
        assert person["faculty"] is None

        lessons = body["lessons"]
        assert [l["id"] for l in lessons] == [str(world.l3.id), str(world.l4.id)]
        assert [l["teacherStatus"] for l in lessons] == ["kutilmoqda", "kechikdi"]
        assert all(l["attendanceStatus"] is None for l in lessons)

        (visit,) = body["recentVisits"]
        assert visit["camera"] == "205-xona" and visit["building"] == world.building.name
        assert visit["durationMinutes"] == 45 and visit["sightings"] == 20

    async def test_errors(self, client, world, admin):
        pid = world.people.aliyev.id
        assert (await client.get("/api/situation/people/nope", headers=admin)).status_code == 404
        missing = "00000000-0000-0000-0000-000000000000"
        assert (await client.get(f"/api/situation/people/{missing}", headers=admin)).status_code == 404
        too_long = {"from": (world.today - timedelta(days=400)).isoformat(), "to": world.today.isoformat()}
        assert (await client.get(f"/api/situation/people/{pid}", params=too_long, headers=admin)).status_code == 422
        reversed_ = {"from": world.today.isoformat(), "to": world.yesterday.isoformat()}
        assert (await client.get(f"/api/situation/people/{pid}", params=reversed_, headers=admin)).status_code == 422
