"""Bayram va qo'shimcha dam olish kunlari (Sozlamalar → Ish vaqti).

Bayram kuni hech kim "kelmadi" yoki "kech keldi" bo'lmaydi: absence_marker
yozmaydi, kelganlar "keldi", o'tgan sana keyin belgilansa — yozuvlar
tuzatiladi."""

from datetime import date, time, timedelta

import pytest
from httpx import AsyncClient

from app.models import AttendanceRecord, StudentStaff
from app.services import situation as svc
from app.services.attendance_policy import Policy, current_policy, set_cached
from app.timezone import business_today
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _reset_policy():
    yield
    set_cached(Policy())


def test_holiday_is_not_a_work_day():
    day = date(2026, 10, 1)  # payshanba
    policy = Policy(holidays=frozenset({day}))
    assert not policy.is_work_day(day)
    assert policy.is_work_day(day + timedelta(days=1))
    # Bayramda kechikish yo'q.
    assert policy.arrival_status(time(11, 0), "xodim", day) == "keldi"
    assert policy.arrival_status(time(11, 0), "xodim", day + timedelta(days=1)) == "kech_keldi"


def test_off_day_people_are_on_day_off_not_waiting():
    day = business_today()
    set_cached(Policy(holidays=frozenset({day})))
    assert svc.pending_state(day) == svc.OFF_DAY
    assert svc.person_status(None, True, day) == "dam_olish"
    counts = svc.Counts()
    counts.add(True, None, 3, svc.pending_state(day))
    assert counts.day_off == 3 and counts.not_yet == 0 and counts.absent == 0


@pytest.mark.usefixtures("seeded")
async def test_marking_a_past_day_fixes_its_records(client: AsyncClient, db_session):
    day = business_today() - timedelta(days=3)
    absent = StudentStaff(full_name="Kelmagan Xodim", type="xodim", group_or_position="Assistent")
    late = StudentStaff(full_name="Kech Xodim", type="xodim", group_or_position="Assistent")
    db_session.add_all([absent, late])
    await db_session.flush()
    db_session.add_all([
        AttendanceRecord(student_staff_id=absent.id, date=day, status="kelmadi"),
        AttendanceRecord(student_staff_id=late.id, date=day, status="kech_keldi", check_in=time(9, 30)),
    ])
    await db_session.commit()

    headers = await auth_headers(client, "admin", "admin123")
    resp = await client.post(
        "/api/attendance-policy/holidays", json={"date": day.isoformat(), "name": "Qurbon hayiti"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["recomputed"] == 2
    assert not current_policy().is_work_day(day)

    statuses = {r.student_staff_id: r.status for r in (await db_session.execute(
        AttendanceRecord.__table__.select().where(AttendanceRecord.date == day)
    )).all()}
    assert statuses[absent.id] == "dam_olish"
    assert statuses[late.id] == "keldi"

    listed = await client.get("/api/attendance-policy/holidays", params={"year": day.year}, headers=headers)
    assert {"date": day.isoformat(), "name": "Qurbon hayiti"} in listed.json()

    assert (await client.delete(f"/api/attendance-policy/holidays/{day.isoformat()}", headers=headers)).status_code == 204
    assert current_policy().is_work_day(day) == (day.isoweekday() in current_policy().work_days)


@pytest.mark.usefixtures("seeded")
async def test_standard_holidays_are_added_once(client: AsyncClient):
    headers = await auth_headers(client, "admin", "admin123")
    first = await client.post("/api/attendance-policy/holidays/standart", params={"year": 2030}, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["added"] == 7
    again = await client.post("/api/attendance-policy/holidays/standart", params={"year": 2030}, headers=headers)
    assert again.json()["added"] == 0
    names = {h["date"]: h["name"] for h in (await client.get(
        "/api/attendance-policy/holidays", params={"year": 2030}, headers=headers)).json()}
    assert names["2030-03-21"] == "Navro'z bayrami"


async def test_editing_requires_permission(client: AsyncClient):
    resp = await client.post("/api/attendance-policy/holidays", json={"date": "2030-01-02", "name": "x"})
    assert resp.status_code in (401, 403)
