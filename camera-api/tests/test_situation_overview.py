"""GET /api/situation/overview — institut bo'yicha bir kunning holati.

Sonlar tests/situation_world.py izohidagi dunyodan qo'lda hisoblangan.
"""

from datetime import time

import pytest
from httpx import AsyncClient

from app.models import AttendanceRecord, User
from app.security import hash_password
from app.services import situation
from tests.conftest import auth_headers
from tests.situation_world import _situation_settings, world  # noqa: F401 — pytest fikstura

URL = "/api/situation/overview"


@pytest.fixture
async def admin(client: AsyncClient, world):
    return await auth_headers(client, "operator", "operator123")


async def test_student_and_staff_counts_are_honest_about_enrollment(client, world, admin):
    body = (await client.get(URL, headers=admin)).json()
    assert body["date"] == world.today.isoformat()
    assert body["isToday"] is True

    # Faol talabalar 12 (nofaol hisobga kirmaydi); 9 tasining yuzi tasdiqlangan.
    assert body["students"] == {
        "total": 12, "enrolled": 9, "present": 6, "late": 1, "absent": 2, "dayOff": 0,
        "notYet": 1, "noData": 3, "rate": 66.7,
    }
    # Qodirova (tasdiqlanmagan) — "hali kelmagan" emas, "ma'lumot yo'q".
    assert body["staff"] == {
        "total": 4, "enrolled": 3, "present": 2, "late": 1, "absent": 0, "dayOff": 0,
        "notYet": 1, "noData": 1, "rate": 66.7,
    }


async def test_teachers_lessons_cameras_events(client, world, admin):
    body = (await client.get(URL, headers=admin)).json()
    # Yusupova — o'z vaqtida; Karimov — kechikdi (L4); Rahimov — kelmadi (L6);
    # "Soatov B." (teacher_id yo'q, tekshirilmagan) — noma'lum.
    assert body["teachers"] == {"scheduled": 4, "onTime": 1, "late": 1, "absent": 1, "unknown": 1}
    assert body["lessons"] == {"total": 6, "finished": 4, "ongoing": 1, "upcoming": 1, "avgAttention": 70.0}
    assert body["cameras"] == {"total": 3, "active": 2, "online": 2, "videoFlowing": 1}
    # Sinov signali hisobga kirmaydi; rad etilgani ochiq emas, lekin bugungi.
    assert body["events"] == {"open": 2, "today": 3, "highOpen": 1, "overdue": 1}


async def test_by_faculty_includes_empty_faculties_and_no_faculty_row_last(client, world, admin):
    rows = (await client.get(URL, headers=admin)).json()["byFaculty"]
    by_name = {r["name"]: r for r in rows}
    assert rows[-1]["name"] == "Fakultetsiz" and rows[-1]["id"] is None
    assert by_name["Fakultetsiz"]["total"] == 1 and by_name["Fakultetsiz"]["noData"] == 1

    di = by_name["Davolash ishi"]
    assert di["id"] == str(world.di.id)
    assert (di["total"], di["enrolled"], di["present"], di["late"], di["absent"], di["notYet"], di["noData"]) == (
        8, 7, 5, 1, 1, 1, 1,
    )
    assert di["rate"] == 71.4
    pe = by_name["Pediatriya"]
    assert (pe["total"], pe["present"], pe["absent"], pe["rate"]) == (3, 1, 1, 50.0)
    # Talabasi yo'q fakultet ham ko'rinadi, foizi esa None (0 emas).
    assert by_name["Farmatsiya"]["total"] == 0 and by_name["Farmatsiya"]["rate"] is None


async def test_arrivals_by_hour_and_last_arrivals(client, world, admin):
    body = (await client.get(URL, headers=admin)).json()
    hours = {b["hour"]: b for b in body["arrivalsByHour"]}
    assert min(hours) == 7 and max(hours) == 19 and len(hours) == 13
    assert hours[7] == {"hour": 7, "students": 0, "staff": 1, "studentsLate": 0, "staffLate": 0}
    # nofaol talabaning 08:00 i kirmaydi
    assert hours[8] == {"hour": 8, "students": 5, "staff": 0, "studentsLate": 0, "staffLate": 0}
    # 09:15 Botirova va 09:20 Karimov — "kech_keldi" yozuvlari: kech qismi alohida
    assert hours[9] == {"hour": 9, "students": 1, "staff": 1, "studentsLate": 1, "staffLate": 1}
    assert hours[12] == {"hour": 12, "students": 0, "staff": 0, "studentsLate": 0, "staffLate": 0}
    # Grafikdagi kechikish chizig'i — ish vaqti sozlamasidan (08:00 + 10 daqiqa).
    assert body["lateAfterStudents"] == "08:10" and body["lateAfterStaff"] == "08:10"

    last = body["lastArrivals"]
    assert [a["time"] for a in last] == ["09:20", "09:15", "08:45", "08:30", "08:20", "08:10", "08:05", "07:55"]
    first = last[0]
    assert first["fullName"] == "Karimov Aziz Olimovich" and first["type"] == "xodim"
    assert first["status"] == "kech_keldi" and first["initials"] == "KA"
    aliyev = next(a for a in last if a["fullName"] == "Aliyev Anvar")
    assert aliyev["unit"] == "DI-2301"  # talaba uchun — guruh, kurssiz
    assert aliyev["faculty"] == "Davolash ishi"
    assert aliyev["photoUrl"] and "faces/aliyev.jpg" in aliyev["photoUrl"]
    assert next(a for a in last if a["fullName"] == "Botirova Nigora")["photoUrl"] is None


async def test_untimed_arrivals_are_counted_apart_from_the_hours(client, world, admin, db_session):
    """HEMIS davomati (source=hemis) kelish vaqtisiz: soatlik ustunlarga
    tushmaydi, lekin grafik ularni alohida sanaydi — ustunlar + vaqtsizlar =
    kelganlar."""
    db_session.add(AttendanceRecord(student_staff_id=world.people.davronov.id, date=world.today, status="keldi",
                                    source="hemis"))
    await db_session.commit()
    body = (await client.get(URL, headers=admin)).json()
    assert body["arrivalsUntimedStudents"] == 1 and body["arrivalsUntimedStaff"] == 0
    assert sum(b["students"] for b in body["arrivalsByHour"]) == 6  # faqat vaqti borlar


async def test_past_date_has_no_waiting_people(client, world, admin):
    body = (await client.get(URL, params={"date": world.yesterday.isoformat()}, headers=admin)).json()
    assert body["isToday"] is False
    # Kecha: Aliyev keldi, Botirova va Choriyev kelmadi; qolganlar — ma'lumot yo'q.
    assert body["students"]["present"] == 1
    assert body["students"]["absent"] == 2
    assert body["students"]["notYet"] == 0
    assert body["students"]["noData"] == 9
    assert body["students"]["rate"] == 33.3
    assert body["lessons"]["total"] == 1
    assert body["teachers"] == {"scheduled": 1, "onTime": 0, "late": 0, "absent": 1, "unknown": 0}
    assert body["lastArrivals"][0]["time"] == "08:15"


async def test_response_is_cached_briefly_per_date(client, world, admin, db_session):
    first = (await client.get(URL, headers=admin)).json()
    db_session.add(AttendanceRecord(student_staff_id=world.people.davronov.id, date=world.today,
                                    status="keldi", check_in=time(10, 0)))
    await db_session.commit()

    cached = (await client.get(URL, headers=admin)).json()
    assert cached["students"]["present"] == first["students"]["present"]

    situation.clear_cache()
    fresh = (await client.get(URL, headers=admin)).json()
    assert fresh["students"]["present"] == first["students"]["present"] + 1
    assert fresh["students"]["notYet"] == 0


async def test_bad_date_is_422(client, world, admin):
    resp = await client.get(URL, params={"date": "19-09-2026"}, headers=admin)
    assert resp.status_code == 422


async def test_requires_attendance_or_reports_permission(client, world, db_session):
    assert (await client.get(URL)).status_code == 401
    db_session.add(User(login="kamera1", password_hash=hash_password("kamera-parol-123"),
                        full_name="Kamera Mas'uli", role="kamera-masuli"))
    await db_session.commit()
    headers = await auth_headers(client, "kamera1", "kamera-parol-123")
    for url in (URL, "/api/situation/groups", "/api/situation/kafedras", "/api/situation/lessons",
                f"/api/situation/people/{world.people.aliyev.id}"):
        assert (await client.get(url, headers=headers)).status_code == 403, url
