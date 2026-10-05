"""GET /api/situation/people-status — sanoq ortidagi odamlar ro'yxati.

Dunyo: tests/situation_world.py (overview testidagi sanoqlar bilan bir xil).
"""

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers
from tests.situation_world import _situation_settings, world  # noqa: F401 — pytest fikstura

URL = "/api/situation/people-status"


@pytest.fixture
async def admin(client: AsyncClient, world):
    return await auth_headers(client, "operator", "operator123")


async def test_counts_match_overview_and_lists_match_counts(client, world, admin):
    body = (await client.get(URL, headers=admin)).json()
    counts = body["counts"]
    # overview: talabalar 12, kelgan 6 (1 kech), kelmadi 2, kutilmoqda 1, yuzsiz 3
    assert counts["hammasi"] == 12 and counts["kelgan"] == 6 and counts["kechKeldi"] == 1
    assert counts["kelmadi"] == 2 and counts["kutilmoqda"] == 1 and counts["yuzsiz"] == 3
    assert body["total"] == 12
    for status, key in (("kelgan", "kelgan"), ("kech_keldi", "kechKeldi"), ("kelmadi", "kelmadi"), ("yuzsiz", "yuzsiz")):
        listing = (await client.get(URL, params={"status": status}, headers=admin)).json()
        assert listing["total"] == counts[key], status
        if status == "kech_keldi":
            assert all(p["status"] == "kech_keldi" for p in listing["items"])
        if status == "yuzsiz":
            assert all(p["biometricsStatus"] != "tasdiqlangan" for p in listing["items"])


async def test_arrival_hour_lists_the_bar_people(client, world, admin):
    """Kelish grafigidagi ustun bosilganda: aynan o'sha soatda kelganlar —
    soni grafikdagi ustun bilan bir xil (overview.arrivalsByHour)."""
    overview = (await client.get("/api/situation/overview", headers=admin)).json()
    hours = {b["hour"]: b for b in overview["arrivalsByHour"]}
    for hour in (8, 9):
        body = (await client.get(URL, params={"status": "kelgan", "arrivalHour": hour}, headers=admin)).json()
        assert body["total"] == hours[hour]["students"]
        assert all(p["checkIn"].startswith(f"{hour:02d}:") for p in body["items"])
    late = (await client.get(URL, params={"status": "kech_keldi", "arrivalHour": 9}, headers=admin)).json()
    assert [p["fullName"] for p in late["items"]] == ["Botirova Nigora"]
    staff = (await client.get(URL, params={"type": "xodim", "status": "kelgan", "arrivalHour": 7}, headers=admin)).json()
    assert staff["total"] == hours[7]["staff"] == 1
    assert (await client.get(URL, params={"arrivalHour": 24}, headers=admin)).status_code == 422
    pdf = await client.get("/api/situation/pdf/people", params={"status": "kelgan", "arrivalHour": 9}, headers=admin)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


async def test_staff_and_pagination(client, world, admin):
    staff = (await client.get(URL, params={"type": "xodim"}, headers=admin)).json()
    assert staff["counts"]["hammasi"] == 4 and staff["counts"]["kelgan"] == 2
    page = (await client.get(URL, params={"pageSize": 5, "page": 2}, headers=admin)).json()
    assert page["total"] == 12 and len(page["items"]) == 5


async def test_requires_permission(client: AsyncClient):
    assert (await client.get(URL)).status_code in (401, 403)


async def test_staff_filtered_by_department(client, world, admin):
    units = (await client.get("/api/situation/kafedras", params={"kind": "all"}, headers=admin)).json()
    anatomy = next(u for u in units if u["name"] == "Anatomiya kafedrasi")
    body = (await client.get(URL, params={"type": "xodim", "departmentId": anatomy["id"]}, headers=admin)).json()
    names = [p["fullName"] for p in body["items"]]
    assert names and any("Yusupova" in n for n in names)
    assert body["counts"]["hammasi"] == len(names)
    assert (await client.get(URL, params={"type": "xodim", "departmentId": "yoq"}, headers=admin)).status_code == 404


async def _org(db_session, world):
    """Pediatriya fakulteti -> Anatomiya kafedrasi; Rektorat. Yusupova va Karimov
    — Anatomiyada (dotsent/farrosh), Rahimov — rektoratda, Qodirova bog'lanmagan."""
    from app.models import OrgUnit

    fac = OrgUnit(name="Pediatriya fakulteti", kind="fakultet")
    rek = OrgUnit(name="Rektorat", kind="rektorat")
    db_session.add_all([fac, rek])
    await db_session.flush()
    kaf = OrgUnit(name="Anatomiya", kind="kafedra", parent_id=fac.id)
    db_session.add(kaf)
    await db_session.flush()
    world.people.yusupova.org_unit_id, world.people.yusupova.position = kaf.id, "Dotsent"
    world.people.karimov.org_unit_id, world.people.karimov.position = kaf.id, "Farrosh"
    world.people.rahimov.org_unit_id, world.people.rahimov.position = rek.id, "Prorektor"
    ids = {"fac": str(fac.id), "kaf": str(kaf.id), "rek": str(rek.id)}
    await db_session.commit()
    return ids


async def test_org_tree_counts_roll_up_to_faculty(client, world, admin, db_session):
    ids = await _org(db_session, world)
    body = (await client.get("/api/situation/tuzilma", headers=admin)).json()
    units = {u["id"]: u for u in body["units"]}
    # Yusupova keldi, Karimov kech keldi — ikkalasi kelgan; fakultetga yig'iladi.
    assert (units[ids["kaf"]]["present"], units[ids["kaf"]]["total"], units[ids["kaf"]]["depth"]) == (2, 2, 1)
    assert units[ids["fac"]]["present"] == 2 and units[ids["fac"]]["kindLabel"] == "Fakultetlar"
    assert [u["kind"] for u in body["units"]][:2] == ["rektorat", "fakultet"]  # rahbariyat birinchi
    assert units["yoq"]["total"] == 1  # Qodirova
    assert body["positionGroups"]["texnik"] == 1 and body["positionGroups"]["oqituvchi"] == 1


async def test_people_filtered_by_org_unit_and_position_group(client, world, admin, db_session):
    ids = await _org(db_session, world)
    base = {"type": "xodim"}
    fac = (await client.get(URL, params={**base, "orgUnitId": ids["fac"]}, headers=admin)).json()
    assert sorted(p["position"] for p in fac["items"]) == ["Dotsent", "Farrosh"]
    assert all(p["unit"] == "Anatomiya" for p in fac["items"])
    tech = (await client.get(URL, params={**base, "positionGroup": "texnik"}, headers=admin)).json()
    assert [p["position"] for p in tech["items"]] == ["Farrosh"]
    loose = (await client.get(URL, params={**base, "orgUnitId": "yoq"}, headers=admin)).json()
    assert [p["fullName"] for p in loose["items"]] == ["Qodirova Malika"]



async def test_pdf_exports_follow_the_filters(client, world, admin, db_session):
    """Har PDF: haqiqiy PDF fayl, yuklab olish sarlavhasi bilan; filtr natijasi hujjatga tushadi."""
    ids = await _org(db_session, world)
    cases = [
        ("/api/situation/pdf/people", {"status": "kech_keldi"}),
        ("/api/situation/pdf/people", {"type": "xodim", "orgUnitId": ids["fac"], "positionGroup": "texnik"}),
        ("/api/situation/pdf/groups", {}),
        ("/api/situation/pdf/group", {"name": "DI-2301", "status": "kelmadi"}),
        ("/api/situation/pdf/tuzilma", {}),
    ]
    for path, params in cases:
        res = await client.get(path, params=params, headers=admin)
        assert res.status_code == 200, (path, res.text[:300])
        assert res.headers["content-type"] == "application/pdf"
        assert res.content[:4] == b"%PDF" and len(res.content) > 1000
        assert "attachment" in res.headers["content-disposition"] and ".pdf" in res.headers["content-disposition"]
    assert (await client.get("/api/situation/pdf/people")).status_code in (401, 403)
