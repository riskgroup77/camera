"""Bo'linmalarni matndan yig'ish, tahlil (KPI, issiqlik xaritasi, reyting,
surunkali ro'yxat), biometrik ro'yxatga olish va devor ekrani.

API testlari tests/situation_world.py dunyosida; xodimlar yozuvlari:
  bugun  — Yusupova keldi 07:55, Karimov kech_keldi 09:20, Rahimov (tasdiq.) yozuvsiz
  kecha  — Yusupova keldi 08:00
"""

import hashlib
import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient

from app.services import situation as svc, situation_analytics as an
from app.services.situation_analytics import DayAgg
from tests.conftest import auth_headers
from tests.situation_world import _person, _record, _situation_settings, world  # noqa: F401 — pytest fikstura

LAVOZIM = "Lavozim bo'yicha (bo'linmasi ko'rsatilmagan)"


@pytest.fixture
async def admin(client: AsyncClient, world):
    return await auth_headers(client, "operator", "operator123")


# ─────────────────────────────────────────── bo'linmalar: sof funksiyalar

@pytest.mark.parametrize(("name", "kind"), [
    ("Normal anatomiya", "kafedra"),
    ("Fiziologiya", "kafedra"),
    ("Endokrinologiya, gematologiya va ftiziatriya kafedrasi", "kafedra"),
    ("Davolash ishi fakulteti", "dekanat"),
    ("Pediatriya fakulteti dekanati", "dekanat"),
    ("Rektorat", "bolim"),
    ("Xisobxona", "bolim"),
    ("Texnik foydalanish va xo'jalik bo'limi", "bolim"),
    ("Texnik foydalanish va xo‘jalik bo‘limi", "bolim"),  # boshqa apostrof
    ("3-talabalar turar joyi", "bolim"),
    ("Axborot-resurs markazi", "bolim"),
    ("Farrosh", "lavozim"),
    ("Assistent", "lavozim"),
    ("  QOROVUL ", "lavozim"),
    ("Katta o'qituvchi", "lavozim"),
    ("Bosh hisobchi", "lavozim"),
    ("", "lavozim"),
    (None, "lavozim"),
])
def test_classify_unit(name, kind):
    assert svc.classify_unit(name) == kind


def test_build_catalog_merges_departments_and_derives_stable_ids():
    dep_id = uuid.uuid4()
    deps = [svc.DepartmentInfo(dep_id, "Normal anatomiya", "Bosh bino")]
    p = [uuid.uuid4() for _ in range(7)]
    staff = [
        (p[0], "normal  ANATOMIYA"), (p[1], "Fiziologiya"), (p[2], " fiziologiya "), (p[3], "Farrosh"),
        (p[4], None), (p[5], "Rektorat"), (p[6], "Davolash ishi fakulteti"),
    ]
    catalog = svc.build_catalog(deps, staff)
    fiz_id = "u-" + hashlib.sha1(b"fiziologiya").hexdigest()[:10]

    # Department nomi mos kelsa uning id si yutadi; matn variantlari birlashadi.
    assert catalog.unit_id("Normal Anatomiya") == str(dep_id)
    assert catalog.units[str(dep_id)].building == "Bosh bino"
    assert catalog.unit_id("FIZIOLOGIYA") == fiz_id == svc.derived_unit_id("fiziologiya")
    assert catalog.units[fiz_id].name == "Fiziologiya"
    # Sof lavozim va bo'sh matn — bitta soxta bo'linma.
    assert catalog.unit_id("Farrosh") == catalog.unit_id(None) == svc.UNASSIGNED_KAFEDRA_ID
    assert catalog.units[svc.UNASSIGNED_KAFEDRA_ID].name == LAVOZIM

    # Tartib: kafedra (nom bo'yicha), dekanat, bo'lim, lavozim oxirida.
    assert [(u.name, u.kind) for u in catalog.units.values()] == [
        ("Fiziologiya", "kafedra"), ("Normal anatomiya", "kafedra"), ("Davolash ishi fakulteti", "dekanat"),
        ("Rektorat", "bolim"), (LAVOZIM, "lavozim"),
    ]
    assert set(catalog.staff_ids(fiz_id)) == {p[1], p[2]}
    assert set(catalog.staff_ids(svc.UNASSIGNED_KAFEDRA_ID)) == {p[3], p[4]}
    # Id barqaror — qayta qurilganda ham o'zgarmaydi.
    assert svc.build_catalog(deps, list(reversed(staff))).unit_id("fiziologiya") == fiz_id


# ─────────────────────────────────────────── tahlil: sof funksiyalar

def test_period_kpis_and_comparison():
    cur = [DayAgg(present=8, late=2, absent=2, arrival_sum=8 * 480, arrival_n=8),
           DayAgg(present=6, late=0, absent=0, not_yet=4, arrival_sum=6 * 490, arrival_n=6),
           DayAgg()]  # yozuvsiz kun — davrga kirmaydi
    prev = [DayAgg(present=9, late=3, absent=1, arrival_sum=9 * 470, arrival_n=9)]
    c, p = an.period_kpis(cur), an.period_kpis(prev)
    assert c == {"rate": 70.0, "avg_arrival": "08:04", "avg_arrival_minutes": 484, "present": 14, "late": 2,
                 "absent": 2, "punctual_pct": 85.7, "days_covered": 2}
    assert p["rate"] == 90.0 and p["avg_arrival"] == "07:50" and p["punctual_pct"] == 66.7
    assert an.compare(c, p) == {"rate": -20.0, "avg_arrival_minutes": 14, "late": -1, "absent": 1,
                                "punctual_pct": 19.0}
    empty = an.period_kpis([])
    assert empty["rate"] is None and empty["avg_arrival"] is None
    assert an.compare(c, empty)["rate"] is None


def test_previous_period_same_length():
    from datetime import date
    assert an.previous_period(date(2026, 9, 1), date(2026, 9, 30)) == (date(2026, 8, 2), date(2026, 8, 31))
    assert an.previous_period(date(2026, 9, 19), date(2026, 9, 19)) == (date(2026, 9, 18), date(2026, 9, 18))


@pytest.mark.parametrize(("statuses", "expected"), [
    ([], (0, None)),
    (["keldi", "kelmadi"], (0, None)),
    (["kelmadi", "kelmadi", "keldi", "kelmadi"], (2, "kelmadi")),
    (["kech_keldi", "dam_olish", "kech_keldi", "keldi"], (2, "kech_keldi")),
    (["kelmadi", "kech_keldi"], (2, "aralash")),
])
def test_current_streak(statuses, expected):
    assert an.current_streak(statuses) == expected


def test_heatmap_buckets():
    out = an.heatmap_buckets(
        [(1, 8, 5), (1, 9, 2), (6, 20, 1), (7, 9, 4), (2, 5, 3), (3, 21, 1)],
        [(1, 7, 2), (6, 1, 0)],
    )
    assert out["hours"] == list(range(6, 21))
    assert [w["label"] for w in out["weekdays"]] == ["Du", "Se", "Cho", "Pa", "Ju", "Sha"]
    mon, sat = out["weekdays"][0], out["weekdays"][5]
    assert mon["counts"][8 - 6] == 5 and mon["counts"][9 - 6] == 2 and mon["total"] == 7
    assert (mon["present"], mon["late"], mon["late_rate"]) == (7, 2, 28.6)
    assert sat["counts"][-1] == 1 and sat["late_rate"] == 0.0
    assert out["weekdays"][1]["late_rate"] is None
    # yakshanba (4) + 05 soat (3) + 21 soat (1)
    assert out["outside"] == 8 and out["max"] == 5


# ─────────────────────────────────────────── API: bo'linmalar

@pytest.fixture
async def units_world(world, db_session):
    extra = [
        _person("Normatov A", "xodim", "Normal anatomiya"),
        _person("Nazarova B", "xodim", " normal  ANATOMIYA"),
        _person("Rustamov C", "xodim", "Rektorat"),
        _person("Dekanov D", "xodim", "Davolash ishi fakulteti"),
        _person("Farroshova E", "xodim", "Farrosh", enrolled=False),
    ]
    db_session.add_all(extra)
    await db_session.flush()
    db_session.add(_record(extra[0], world.today, "keldi", "08:10"))
    await db_session.commit()
    return extra


class TestUnits:
    async def test_kafedras_derived_units_with_kind_filter(self, client, world, admin, units_world):
        rows = (await client.get("/api/situation/kafedras", headers=admin)).json()
        assert [(r["name"], r["kind"]) for r in rows] == [
            ("Anatomiya kafedrasi", "kafedra"), ("Fiziologiya kafedrasi", "kafedra"), ("Normal anatomiya", "kafedra"),
            ("Davolash ishi fakulteti", "dekanat"), ("Rektorat", "bolim"), (LAVOZIM, "lavozim"),
        ]
        normal = rows[2]
        assert normal["id"] == svc.derived_unit_id("normal anatomiya")
        assert (normal["staffTotal"], normal["present"], normal["notYet"]) == (2, 1, 1)
        assert rows[-1]["staffTotal"] == 2  # Qodirova ("Bosh hisobchi") + Farroshova

        bolim = (await client.get("/api/situation/kafedras?kind=bolim", headers=admin)).json()
        assert [r["name"] for r in bolim] == ["Rektorat"]
        assert (await client.get("/api/situation/kafedras?kind=nimadir", headers=admin)).status_code == 422

    async def test_kafedra_detail_accepts_derived_id(self, client, world, admin, units_world):
        unit_id = svc.derived_unit_id("normal anatomiya")
        body = (await client.get(f"/api/situation/kafedras/{unit_id}", headers=admin)).json()
        assert body["id"] == unit_id and body["kind"] == "kafedra" and body["unassigned"] is False
        assert [t["fullName"] for t in body["teachers"]] == ["Nazarova B", "Normatov A"]
        assert (await client.get("/api/situation/kafedras/u-0000000000", headers=admin)).status_code == 404

    async def test_person_profile_links_derived_unit(self, client, world, admin, units_world):
        body = (await client.get(f"/api/situation/people/{units_world[2].id}", headers=admin)).json()
        assert body["person"]["departmentId"] == svc.derived_unit_id("rektorat")
        assert body["person"]["department"] == "Rektorat"


# ─────────────────────────────────────────── API: tahlil

class TestAnalytics:
    async def test_summary_with_previous_period(self, client, world, admin):
        q = f"from={world.yesterday}&to={world.today}"
        body = (await client.get(f"/api/situation/analytics/summary?{q}", headers=admin)).json()
        assert body["type"] == "xodim"
        assert body["previousTo"] == (world.yesterday - timedelta(days=1)).isoformat()
        # 3 kelish (1 kech), bugun Rahimov kutilmoqda: 3 / (3 + 0 + 1).
        # O'rtacha kelish: (07:55 + 09:20 + 08:00) / 3 = 08:25.
        assert body["current"] == {"rate": 75.0, "avgArrival": "08:25", "avgArrivalMinutes": 505, "present": 3,
                                   "late": 1, "absent": 0, "punctualPct": 66.7, "daysCovered": 2}
        assert body["previous"]["rate"] is None and body["previous"]["daysCovered"] == 0
        assert body["delta"] == {"rate": None, "avgArrivalMinutes": None, "late": 1, "absent": 0,
                                 "punctualPct": None}
        assert body["daily"] == [
            {"date": world.yesterday.isoformat(), "present": 1, "late": 0, "absent": 0, "expected": 1,
             "rate": 100.0, "avgArrival": "08:00"},
            {"date": world.today.isoformat(), "present": 2, "late": 1, "absent": 0, "expected": 3,
             "rate": 66.7, "avgArrival": "08:38"},
        ]

    async def test_summary_students_and_default_period(self, client, world, admin):
        body = (await client.get("/api/situation/analytics/summary?type=talaba", headers=admin)).json()
        assert body["dateTo"] == world.today.isoformat() and len(body["daily"]) == 30
        # Talabalar bugun: 6 kelgan (1 kech), 2 kelmagan, Davronov kutilmoqda; kecha 1 kelgan, 2 kelmagan.
        assert (body["current"]["present"], body["current"]["absent"], body["current"]["late"]) == (7, 4, 1)
        assert body["current"]["rate"] == round(7 * 100 / 12, 1)

    async def test_heatmap(self, client, world, admin):
        q = f"from={world.yesterday}&to={world.today}"
        body = (await client.get(f"/api/situation/analytics/heatmap?{q}", headers=admin)).json()
        cells = {}
        for w in body["weekdays"]:
            for hour, n in zip(body["hours"], w["counts"]):
                if n:
                    cells[(w["weekday"], hour)] = n
        expected = {}
        for day, hour in ((world.today, 7), (world.today, 9), (world.yesterday, 8)):
            if day.isoweekday() <= 6:
                expected[(day.isoweekday(), hour)] = expected.get((day.isoweekday(), hour), 0) + 1
        assert cells == expected
        assert body["outside"] == 3 - sum(expected.values())
        if world.today.isoweekday() <= 6:
            today_row = body["weekdays"][world.today.isoweekday() - 1]
            assert today_row["late"] == 1 and today_row["present"] >= 2

    async def test_units_ranking_and_trend(self, client, world, admin):
        rows = (await client.get("/api/situation/analytics/units", headers=admin)).json()
        by_name = {r["name"]: r for r in rows}
        anatomy = by_name["Anatomiya kafedrasi"]
        assert anatomy["id"] == str(world.anatomy.id) and anatomy["kind"] == "kafedra"
        assert (anatomy["headcount"], anatomy["enrolled"], anatomy["presentDays"], anatomy["lateDays"]) == (2, 2, 3, 1)
        assert anatomy["rate"] == 100.0 and anatomy["punctualPct"] == 66.7 and anatomy["avgArrival"] == "08:25"
        assert anatomy["previousRate"] is None and anatomy["trend"] is None
        assert by_name["Fiziologiya kafedrasi"]["rate"] is None
        assert rows[0]["name"] == "Anatomiya kafedrasi"  # rate desc, null oxirida
        assert by_name[LAVOZIM]["headcount"] == 1

        only = (await client.get("/api/situation/analytics/units?kind=bolim", headers=admin)).json()
        assert only == []
        groups = (await client.get("/api/situation/analytics/units?type=talaba&sort=absent", headers=admin)).json()
        assert groups[0]["id"] == "DI-2301" and groups[0]["kind"] == "guruh" and groups[0]["absentDays"] == 3

    async def test_units_trend_against_previous_period(self, client, world, admin, db_session):
        # Oldingi davrda (kecha) Karimov kelmagan edi: 0% -> bugun 100%.
        db_session.add(_record(world.people.karimov, world.yesterday, "kelmadi"))
        await db_session.commit()
        q = f"from={world.today}&to={world.today}"
        rows = (await client.get(f"/api/situation/analytics/units?{q}&sort=trend", headers=admin)).json()
        anatomy = next(r for r in rows if r["name"] == "Anatomiya kafedrasi")
        assert (anatomy["rate"], anatomy["previousRate"], anatomy["trend"]) == (100.0, 50.0, 50.0)

    async def test_people_ranking_streak_and_unit_filter(self, client, world, admin):
        rows = (await client.get("/api/situation/analytics/people?sort=late", headers=admin)).json()
        assert [r["fullName"] for r in rows] == ["Karimov Aziz Olimovich", "Yusupova Dilnoza Anvarovna"]
        karimov, yusupova = rows
        assert (karimov["lateDays"], karimov["streak"], karimov["streakKind"]) == (1, 1, "kech_keldi")
        assert karimov["lastSeen"] == world.today.isoformat() and karimov["unitId"] == str(world.anatomy.id)
        assert (yusupova["presentDays"], yusupova["streak"], yusupova["streakKind"]) == (2, 0, None)
        assert yusupova["photoUrl"] and yusupova["avgArrival"] == "07:58"

        by_arrival = (await client.get("/api/situation/analytics/people?sort=arrival&limit=1", headers=admin)).json()
        assert [r["fullName"] for r in by_arrival] == ["Karimov Aziz Olimovich"]
        none = (await client.get(f"/api/situation/analytics/people?unitId={world.physiology.id}", headers=admin))
        assert none.json() == []
        students = (await client.get("/api/situation/analytics/people?type=talaba&sort=absent&unitId=DI-2301",
                                     headers=admin)).json()
        assert [r["fullName"] for r in students][:2] == ["Choriyev Sardor", "Botirova Nigora"]
        assert (students[0]["absentDays"], students[0]["streak"], students[0]["streakKind"]) == (2, 2, "kelmadi")

    async def test_chronic(self, client, world, admin, db_session):
        rahimov = world.people.rahimov
        days = [world.today - timedelta(days=n) for n in (2, 3, 4)]
        db_session.add_all([_record(rahimov, d, "kelmadi") for d in days])
        await db_session.commit()
        rows = (await client.get("/api/situation/analytics/chronic", headers=admin)).json()
        assert [r["fullName"] for r in rows] == ["Rahimov Bobur"]
        assert rows[0]["absentDates"] == sorted(d.isoformat() for d in days)
        assert rows[0]["reasons"] == ["kelmadi"] and rows[0]["unit"] == "Fiziologiya kafedrasi"

        both = (await client.get("/api/situation/analytics/chronic?minLate=1", headers=admin)).json()
        assert [r["fullName"] for r in both] == ["Rahimov Bobur", "Karimov Aziz Olimovich"]
        assert both[1]["lateDates"] == [world.today.isoformat()] and both[1]["reasons"] == ["kech_keldi"]

        people = (await client.get("/api/situation/analytics/people?sort=absent", headers=admin)).json()
        assert (people[0]["fullName"], people[0]["streak"], people[0]["streakKind"]) == ("Rahimov Bobur", 3, "kelmadi")

    async def test_invalid_period_and_permissions(self, client, world, admin):
        bad = await client.get(f"/api/situation/analytics/summary?from={world.today}&to={world.yesterday}",
                               headers=admin)
        assert bad.status_code == 422
        assert (await client.get("/api/situation/analytics/summary")).status_code == 401


# ─────────────────────────────────────────── API: ro'yxatga olish

class TestEnrollment:
    async def test_institute_and_faculties(self, client, world, admin):
        body = (await client.get("/api/situation/enrollment", headers=admin)).json()
        assert body["students"] == {"total": 12, "confirmed": 9, "pending": 0, "none": 3, "pct": 75.0}
        assert body["staff"] == {"total": 4, "confirmed": 3, "pending": 0, "none": 1, "pct": 75.0}
        assert body["studentsDataAvailable"] is True
        by_name = {r["name"]: r for r in body["byFaculty"]}
        assert (by_name["Davolash ishi"]["total"], by_name["Davolash ishi"]["confirmed"]) == (8, 7)
        assert (by_name["Pediatriya"]["total"], by_name["Pediatriya"]["confirmed"]) == (3, 2)
        assert body["byFaculty"][-1]["name"] == "Fakultetsiz" and body["byFaculty"][-1]["total"] == 1

    async def test_groups_sorted_by_pct(self, client, world, admin):
        rows = (await client.get("/api/situation/enrollment/groups", headers=admin)).json()
        assert [(r["name"], r["pct"]) for r in rows] == [
            ("XDI-2301", 0.0), ("XX-1", 0.0), ("DI-2301", 80.0), ("DI-2101", 100.0), ("DI-2302", 100.0),
            ("PE-2501", 100.0), ("DI-2303", None),
        ]
        di = (await client.get(f"/api/situation/enrollment/groups?facultyId={world.di.id}&course=2",
                               headers=admin)).json()
        assert [r["name"] for r in di] == ["DI-2301", "DI-2302", "DI-2303"]
        assert di[0] == {"name": "DI-2301", "facultyId": str(world.di.id), "faculty": "Davolash ishi", "course": 2,
                         "total": 5, "confirmed": 4, "pending": 0, "pct": 80.0}

    async def test_missing_with_enroll_url(self, client, world, admin, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "frontend_base_url", "https://cam.example.uz/")
        body = (await client.get("/api/situation/enrollment/groups/DI-2301/missing", headers=admin)).json()
        assert body["total"] == 5
        assert [m["fullName"] for m in body["missing"]] == ["Ergasheva Laylo"]
        assert body["missing"][0]["initials"] == "EL" and body["missing"][0]["biometricsStatus"] == "yoq"
        # Guruh kodi tizimi olib tashlangan: havola faqat guruhni oldindan to'ldiradi,
        # shaxs JSHSHIR bilan aniqlanadi.
        assert body["enrollCode"] == ""
        assert body["enrollUrl"].startswith("https://cam.example.uz/royxatdan-otish?guruh=DI-2301")

        empty = (await client.get("/api/situation/enrollment/groups/DI-2303/missing", headers=admin)).json()
        assert empty["total"] == 0 and empty["missing"] == []
        assert (await client.get("/api/situation/enrollment/groups/YOQ-1/missing", headers=admin)).status_code == 404


# ─────────────────────────────────────────── API: devor va overview bayrog'i

@pytest.fixture
async def wall_world(world, db_session):
    """Reyting chiqishi uchun bo'linmalarga kamida 3 kishi kerak
    (WALL_MIN_MEASURED) — kichik dunyoga qo'shimcha xodimlar."""
    extra = [
        _person("Anatomchi Kelmadi", "xodim", "Anatomiya kafedrasi"),
        _person("Anatomchi Kutilmoqda", "xodim", "Anatomiya kafedrasi"),
        _person("Fiziolog Bir", "xodim", "Fiziologiya kafedrasi"),
        _person("Fiziolog Ikki", "xodim", "Fiziologiya kafedrasi"),
    ]
    db_session.add_all(extra)
    await db_session.flush()
    db_session.add(_record(extra[0], world.today, "kelmadi"))
    await db_session.commit()
    svc.clear_cache()
    return world


async def test_wall_payload(client, wall_world, admin):
    world = wall_world
    body = (await client.get("/api/situation/wall", headers=admin)).json()
    assert body["date"] == world.today.isoformat()
    assert body["students"]["total"] == 12 and body["staff"]["present"] == 2
    assert body["studentsDataAvailable"] is True
    assert [(u["name"], u["rate"]) for u in body["topUnits"]] == [
        ("Anatomiya kafedrasi", 50.0), ("Fiziologiya kafedrasi", 0.0),
    ]
    assert [u["name"] for u in body["bottomUnits"]] == ["Fiziologiya kafedrasi", "Anatomiya kafedrasi"]
    assert len(body["lastArrivals"]) == 8 and body["lastArrivals"][0]["fullName"] == "Karimov Aziz Olimovich"
    assert [e["status"] for e in body["highEvents"]] == ["yangi"]
    # Ochiq yuqori xavfli hodisalar soni ro'yxat uzunligidan alohida keladi
    # (ro'yxat 5 ta bilan cheklangan).
    assert body["highOpen"] == 1
    # "nofaol" kamera javob bermayotgan emas: maxraj — faol kameralar.
    assert (body["camerasOnline"], body["camerasTotal"]) == (2, 2)
    assert body["enrollment"]["students"]["pct"] == 75.0
    # O'lchangani 3 kishidan kam guruh/bo'linma ekranga chiqmaydi:
    # DI-2101 (1), DI-2302 (1), PE-2501 (2) tushib qoladi.
    assert body["spotlight"] == [
        {"kind": "unit", "id": str(world.anatomy.id), "name": "Anatomiya kafedrasi", "rate": 50.0},
        {"kind": "group", "id": "DI-2301", "name": "DI-2301", "rate": 50.0},
    ]


async def test_wall_hides_units_measured_on_one_or_two_people(client, world, admin):
    """Ikki kishilik kafedraning "0%" yoki "100%" i reyting emas."""
    body = (await client.get("/api/situation/wall", headers=admin)).json()
    assert body["topUnits"] == [] and body["bottomUnits"] == []
    assert [s["kind"] for s in body["spotlight"]] == ["group"]


async def test_wall_drops_group_spotlight_without_student_faces(client, world, admin, db_session):
    """Yuzi tasdiqlangan talaba yetarli bo'lmaganda guruh foizi o'lchov
    emas — devor ekranida guruhlar umuman ko'rsatilmaydi."""
    for person in vars(world.people).values():
        if person.type == "talaba":
            person.biometrics_status = "yoq"
    db_session.add_all([_person(f"Talaba {i}", "talaba", "1-kurs, ZZ-1", enrolled=False) for i in range(10)])
    await db_session.commit()
    svc.clear_cache()
    body = (await client.get("/api/situation/wall", headers=admin)).json()
    assert body["studentsDataAvailable"] is False
    assert [s for s in body["spotlight"] if s["kind"] == "group"] == []


async def test_overview_students_data_flag(client, world, admin, db_session):
    body = (await client.get("/api/situation/overview", headers=admin)).json()
    assert body["studentsDataAvailable"] is True and body["studentsEnrolledPct"] == 75.0

    # Ishlab chiqarishdagidek: talabalarning deyarli hech biri tasdiqlanmagan.
    for person in vars(world.people).values():
        if person.type == "talaba":
            person.biometrics_status = "yoq"
    world.people.aliyev.biometrics_status = "tasdiqlangan"
    db_session.add_all([_person(f"Talaba {i}", "talaba", "1-kurs, ZZ-1", enrolled=False) for i in range(10)])
    await db_session.commit()
    svc.clear_cache()
    body = (await client.get("/api/situation/overview", headers=admin)).json()
    assert body["studentsEnrolledPct"] == round(100 / 22, 1)
    assert body["studentsDataAvailable"] is False
