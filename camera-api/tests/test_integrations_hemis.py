"""HEMIS integratsiyasi: moslashtirish funksiyalari, HTTP mijoz (sahifalash,
qayta urinish, 401), sinxronlash qoidalari va API."""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.config import settings
from app.jobs import hemis_sync as hemis_job
from app.models import Faculty, IntegrationSyncRun, StudentGroup, StudentStaff
from app.services.integrations import hemis
from app.services.integrations.http import set_transport_for_tests
from tests.conftest import TestSessionLocal, auth_headers

BASE = "https://hemis.test/rest"


# ── sof funksiyalar ─────────────────────────────────────────────────────────


def _student(**over):
    item = {
        "id": 1,
        "full_name": "TO‘XTAYEVA MALIKA SHERZOD QIZI",
        "student_id_number": "S-1",
        "passport_pin": "12345678901234",
        "department": {"id": 5, "name": "Davolash ishi fakulteti", "structureType": {"code": "11", "name": "Fakultet"}},
        "group": {"id": 7, "name": "DI-2301"},
        "level": {"code": "12", "name": "2-kurs"},
        "studentStatus": {"code": "11", "name": "O‘qimoqda"},
    }
    item.update(over)
    return item


def test_map_student_basic_fields():
    person = hemis.map_student(_student())
    assert person is not None
    assert person.type == "talaba"
    assert person.hemis_id == "S-1"
    assert person.full_name == "To'xtayeva Malika Sherzod qizi"
    assert person.pinfl == "12345678901234"
    assert person.faculty_name == "Davolash ishi fakulteti"
    assert person.course == 2
    assert person.group_or_position == "2-kurs, DI-2301"
    assert person.active is True


def test_map_student_name_parts_and_bad_pinfl():
    item = _student(full_name=None, second_name="Aliyev", first_name="Vali", third_name="G'ani o'g'li", passport_pin="123")
    person = hemis.map_student(item)
    assert person.full_name == "Aliyev Vali G'ani o'g'li"
    assert person.pinfl is None


def test_map_student_requires_identifier():
    assert hemis.map_student(_student(student_id_number=None)) is None
    assert hemis.map_student(_student(full_name="", first_name=None)) is None


@pytest.mark.parametrize(
    "status, graduate, active",
    [
        ({"code": "11", "name": "O'qimoqda"}, None, True),
        ({"code": "12", "name": "Akademik ta'tilda"}, None, True),
        ({"code": "13", "name": "Chetlashtirilgan"}, None, False),
        ({"code": "14", "name": "Bitirgan"}, None, False),
        ({"code": "14"}, None, False),
        ({"code": "11", "name": "O'qimoqda"}, True, False),
        ({"name": "Отчислен"}, None, False),
    ],
)
def test_student_status(status, graduate, active):
    assert hemis.is_student_active(_student(studentStatus=status, is_graduate=graduate)) is active


def test_parse_course_variants():
    assert hemis.parse_course({"code": "13", "name": "3-kurs"}) == 3
    assert hemis.parse_course({"code": "15"}) == 5
    assert hemis.parse_course("4") == 4
    assert hemis.parse_course(None) is None
    assert hemis.parse_course({"name": "Magistratura"}) is None


def test_structure_kind():
    assert hemis.structure_kind({"structureType": {"code": "11", "name": "Fakultet"}}) == "fakultet"
    assert hemis.structure_kind({"structureType": {"code": "12", "name": "Kafedra"}}) == "kafedra"
    assert hemis.structure_kind({"structureType": {"code": "12"}}) == "kafedra"
    assert hemis.structure_kind({"structureType": {"code": "16", "name": "Bo'lim"}}) is None
    assert hemis.structure_kind(None) is None


def test_map_employee_faculty_via_parent_and_dedupe():
    units = {
        "5": hemis.HemisUnit("5", "Pediatriya fakulteti", "fakultet", None),
        "9": hemis.HemisUnit("9", "Anatomiya kafedrasi", "kafedra", "5"),
    }
    base = {
        "full_name": "QAYUMOV G'ANISHER",
        "employee_id_number": "E-1",
        "department": {"id": 9, "name": "Anatomiya kafedrasi", "structureType": {"code": "12", "name": "Kafedra"}},
        "staffPosition": {"name": "Dotsent"},
        "employeeStatus": {"code": "11", "name": "Ishlamoqda"},
    }
    main = hemis.map_employee({**base, "employmentForm": {"name": "Asosiy"}}, units)
    part = hemis.map_employee({**base, "employmentForm": {"name": "O'rindoshlik"}, "staffPosition": {"name": "Katta o'qituvchi"}}, units)
    assert main.faculty_name == "Pediatriya fakulteti"
    assert main.group_or_position == "Anatomiya kafedrasi"
    assert main.full_name == "Qayumov G'anisher"
    assert part.main_employment is False
    people, duplicates = hemis.dedupe_people([part, main])
    assert duplicates == 1 and len(people) == 1 and people[0].position == "Dotsent"
    fired = hemis.map_employee({**base, "employeeStatus": {"name": "Ishdan bo'shagan"}}, units)
    assert fired.active is False


def test_faculty_key_matches_short_and_long_names():
    assert hemis.faculty_key("Davolash ishi fakulteti") == hemis.faculty_key("Davolash  ishi")


def test_parse_page_errors_and_shape():
    page = hemis.parse_page({"success": True, "data": {"items": [{"a": 1}], "pagination": {"page": 2, "pageCount": 5, "totalCount": 99}}})
    assert (page.page, page.page_count, page.total_count, len(page.items)) == (2, 5, 99, 1)
    with pytest.raises(hemis.HemisError, match="token expired"):
        hemis.parse_page({"success": False, "error": "token expired"})
    with pytest.raises(hemis.HemisError):
        hemis.parse_page({"success": True})


# ── HTTP mijoz ──────────────────────────────────────────────────────────────


@pytest.fixture
def hemis_settings(monkeypatch):
    monkeypatch.setattr(settings, "hemis_base_url", BASE)
    monkeypatch.setattr(settings, "hemis_api_token", "secret-token")
    monkeypatch.setattr(settings, "hemis_page_size", 2)
    monkeypatch.setattr(settings, "hemis_deactivate_missing", False)
    monkeypatch.setattr(hemis, "session_factory", TestSessionLocal)
    yield
    set_transport_for_tests(None)


def _page(items, page, page_count):
    return {
        "success": True,
        "data": {"items": items, "pagination": {"page": page, "pageCount": page_count, "totalCount": 99}},
    }


def _paged_handler(datasets: dict[str, list[dict]], page_size: int = 2, calls: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret-token"
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if calls is not None:
            calls.append((endpoint, dict(request.url.params)))
        items = datasets.get(endpoint, [])
        page = int(request.url.params.get("page", 1))
        limit = int(request.url.params.get("limit", page_size))
        page_count = max(1, -(-len(items) // limit))
        chunk = items[(page - 1) * limit : page * limit]
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {"items": chunk, "pagination": {"page": page, "pageCount": page_count, "totalCount": len(items)}},
            },
        )

    return handler


async def _no_sleep(_seconds):
    return None


async def test_client_paginates(hemis_settings):
    calls = []
    items = [{"n": i} for i in range(5)]
    set_transport_for_tests(httpx.MockTransport(_paged_handler({"student-list": items}, calls=calls)))
    async with hemis.HemisClient(sleep=_no_sleep) as client:
        result = await client.fetch_all("student-list")
    assert [i["n"] for i in result] == [0, 1, 2, 3, 4]
    assert [c[1]["page"] for c in calls] == ["1", "2", "3"]
    assert all(c[1]["limit"] == "2" for c in calls)
    assert calls[0][0] == "student-list"


async def test_client_retries_5xx_and_timeouts(hemis_settings):
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(502)
        if attempts["n"] == 2:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json=_page([{"x": 1}], 1, 1))

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    set_transport_for_tests(httpx.MockTransport(handler))
    async with hemis.HemisClient(sleep=fake_sleep) as client:
        page = await client.fetch_page("group-list")
    assert page.items == [{"x": 1}]
    assert attempts["n"] == 3
    assert sleeps == [1.0, 3.0]


async def test_client_gives_up_after_max_attempts(hemis_settings):
    set_transport_for_tests(httpx.MockTransport(lambda r: httpx.Response(503)))
    async with hemis.HemisClient(sleep=_no_sleep) as client:
        with pytest.raises(hemis.HemisError, match="503"):
            await client.fetch_page("group-list")


async def test_client_401_is_clear_and_not_retried(hemis_settings):
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        return httpx.Response(401, json={"success": False})

    set_transport_for_tests(httpx.MockTransport(handler))
    async with hemis.HemisClient(sleep=_no_sleep) as client:
        with pytest.raises(hemis.HemisAuthError, match="401"):
            await client.fetch_page("student-list")
    assert attempts["n"] == 1


# ── sinxronlash ─────────────────────────────────────────────────────────────

DEPARTMENTS = [
    {"id": 5, "name": "Davolash ishi fakulteti", "structureType": {"code": "11", "name": "Fakultet"}},
    {"id": 6, "name": "Pediatriya fakulteti", "structureType": {"code": "11", "name": "Fakultet"}},
    {"id": 9, "name": "Anatomiya kafedrasi", "structureType": {"code": "12", "name": "Kafedra"}, "parent": 6},
    {"id": 10, "name": "Buxgalteriya", "structureType": {"code": "16", "name": "Bo'lim"}},
]
FAC_DAVOLASH = {"id": 5, "name": "Davolash ishi fakulteti", "structureType": {"code": "11", "name": "Fakultet"}}


def _hemis_student(sid, name, pinfl=None, group="DI-2301", level="2-kurs", status="O'qimoqda"):
    return {
        "student_id_number": sid,
        "full_name": name,
        "passport_pin": pinfl,
        "department": FAC_DAVOLASH,
        "group": {"name": group},
        "level": {"name": level},
        "studentStatus": {"name": status},
    }


async def _seed_people(db):
    faculty = Faculty(name="Davolash ishi", course_count=0, student_count=0)
    db.add(faculty)
    await db.flush()
    by_pinfl = StudentStaff(
        full_name="Eski Ism",
        type="talaba",
        pinfl="11111111111111",
        group_or_position="1-kurs, OLD",
        biometrics_status="tasdiqlangan",
        biometric_photo_key="faces/a.jpg",
        biometric_embedding="[0.1, 0.2]",
        card_number="CARD-1",
    )
    by_name = StudentStaff(full_name="Karimov Anvar", type="talaba", group_or_position="x", biometrics_status="yoq")
    twin_a = StudentStaff(full_name="Umarov Bek", type="talaba", group_or_position="a", biometrics_status="yoq")
    twin_b = StudentStaff(full_name="Umarov Bek", type="talaba", group_or_position="b", biometrics_status="yoq")
    staff_same_pinfl = StudentStaff(full_name="Ordinator Xodim", type="xodim", pinfl="22222222222222", group_or_position="Klinika", biometrics_status="yoq")
    graduating = StudentStaff(full_name="Bitiruvchi Talaba", type="talaba", hemis_id="S-GRAD", group_or_position="6-kurs", biometrics_status="yoq")
    missing = StudentStaff(full_name="Yo'qolgan Talaba", type="talaba", hemis_id="S-GONE", group_or_position="3-kurs", biometrics_status="yoq")
    db.add_all([by_pinfl, by_name, twin_a, twin_b, staff_same_pinfl, graduating, missing])
    await db.commit()
    return {"faculty": faculty, "by_pinfl": by_pinfl, "by_name": by_name, "missing": missing}


def _datasets():
    return {
        "department-list": DEPARTMENTS,
        "group-list": [
            {"id": 1, "name": "DI-2301", "department": FAC_DAVOLASH},
            {"id": 2, "name": "DI-9999", "department": FAC_DAVOLASH, "level": {"name": "4-kurs"}},
            {"id": 3, "name": "NOFAC-1"},
        ],
        "student-list": [
            _hemis_student("S-1", "YANGI ISM", pinfl="11111111111111"),
            _hemis_student("S-2", "KARIMOV ANVAR"),
            _hemis_student("S-3", "UMAROV BEK"),
            _hemis_student("S-4", "ORDINATOR TALABA", pinfl="22222222222222"),
            _hemis_student("S-GRAD", "BITIRUVCHI TALABA", status="Bitirgan"),
            _hemis_student("S-NEWGRAD", "BOSHQA BITIRUVCHI", status="Bitirgan"),
            _hemis_student("S-5", "YANGI TALABA", pinfl="33333333333333", group="DI-2301", level="2-kurs"),
        ],
        "employee-list": [
            {
                "employee_id_number": "E-1",
                "full_name": "QAYUMOV G'ANISHER",
                "department": {"id": 9, "name": "Anatomiya kafedrasi", "structureType": {"code": "12", "name": "Kafedra"}},
                "staffPosition": {"name": "Dotsent"},
                "employmentForm": {"name": "Asosiy"},
            },
            {
                "employee_id_number": "E-1",
                "full_name": "QAYUMOV G'ANISHER",
                "department": {"id": 9, "name": "Anatomiya kafedrasi"},
                "staffPosition": {"name": "Katta o'qituvchi"},
                "employmentForm": {"name": "O'rindoshlik"},
            },
        ],
    }


async def _run_sync(triggered_by="test") -> IntegrationSyncRun:
    async with TestSessionLocal() as db:
        run = await hemis.start_run(db, triggered_by)
    assert run is not None
    await hemis.run_sync(run.id, TestSessionLocal)
    async with TestSessionLocal() as db:
        return await db.get(IntegrationSyncRun, run.id)


async def test_full_sync_matching_rules(hemis_settings, monkeypatch):
    monkeypatch.setattr(settings, "hemis_deactivate_missing", True)
    async with TestSessionLocal() as db:
        seeded = await _seed_people(db)
    set_transport_for_tests(httpx.MockTransport(_paged_handler(_datasets())))

    run = await _run_sync()
    assert run.status == "muvaffaqiyatli", run.error
    stats = run.stats
    assert stats["students"]["fetched"] == 7

    async with TestSessionLocal() as db:
        people = {p.full_name: p for p in (await db.execute(select(StudentStaff))).scalars().all()}
        # 1) JSHSHIR bo'yicha topildi — ism yangilandi, biometrika va karta joyida.
        p1 = await db.get(StudentStaff, seeded["by_pinfl"].id)
        assert p1.hemis_id == "S-1" and p1.full_name == "Yangi Ism"
        assert p1.biometrics_status == "tasdiqlangan"
        assert p1.biometric_embedding == "[0.1, 0.2]"
        assert p1.biometric_photo_key == "faces/a.jpg"
        assert p1.card_number == "CARD-1"
        assert p1.group_or_position == "2-kurs, DI-2301"
        # 2) Yagona ism bo'yicha topildi.
        p2 = await db.get(StudentStaff, seeded["by_name"].id)
        assert p2.hemis_id == "S-2"
        # 3) Bazada ikkita "Umarov Bek" — taxmin qilinmaydi, yangisi yaratiladi.
        umarovs = (await db.execute(select(StudentStaff).where(StudentStaff.full_name == "Umarov Bek"))).scalars().all()
        assert len(umarovs) == 3
        assert sum(1 for u in umarovs if u.hemis_id == "S-3") == 1
        # 4) JSHSHIR xodimga tegishli — talaba qilib yozilmadi.
        staff = people["Ordinator Xodim"]
        assert staff.type == "xodim" and staff.hemis_id is None
        assert "Ordinator Talaba" not in people
        # 5) Bitirgan — faolsizlantirildi; yangi bitirgan yaratilmadi.
        grad = people["Bitiruvchi Talaba"]
        assert grad.active is False and grad.deactivated_at is not None
        assert "Boshqa Bitiruvchi" not in people
        # 6) HEMIS'da yo'q — hemis_deactivate_missing bilan faolsizlantirildi.
        gone = await db.get(StudentStaff, seeded["missing"].id)
        assert gone.active is False
        # 7) Yangi talaba — fakultet mavjud qisqa nom bilan moslandi.
        new = people["Yangi Talaba"]
        assert new.faculty_id == seeded["faculty"].id and new.pinfl == "33333333333333"
        # 8) Xodim: bir nechta lavozim — bitta qator, asosiy ish joyi.
        employee = people["Qayumov G'anisher"]
        assert employee.type == "xodim" and employee.group_or_position == "Anatomiya kafedrasi"
        employee_faculty = await db.get(Faculty, employee.faculty_id)
        assert employee_faculty.name == "Pediatriya fakulteti"
        # Guruhlar: kurs talabalardan, fakultetsiz guruh o'tkazildi.
        groups = {g.name: g for g in (await db.execute(select(StudentGroup))).scalars().all()}
        assert groups["DI-2301"].course == 2 and groups["DI-2301"].student_count == 5
        assert groups["DI-9999"].course == 4
        assert "NOFAC-1" not in groups
        faculties = {f.name for f in (await db.execute(select(Faculty))).scalars().all()}
        assert "Pediatriya fakulteti" in faculties
        assert "Davolash ishi fakulteti" not in faculties  # mavjud "Davolash ishi" ishlatildi

    assert stats["students"]["created"] == 2  # S-3, S-5
    assert stats["students"]["updated"] == 2  # S-1, S-2
    assert stats["students"]["deactivated"] == 2  # S-GRAD, S-GONE
    assert stats["students"]["skipped"] == 2  # S-4 (xodim JSHSHIRi), S-NEWGRAD
    assert stats["employees"]["created"] == 1
    assert stats["departments"]["created"] == 1
    assert stats["groups"]["skipped"] == 1
    assert stats["messages"]

    # Qayta ishga tushirish — idempotent.
    run2 = await _run_sync()
    assert run2.status == "muvaffaqiyatli"
    assert run2.stats["students"]["created"] == 0
    assert run2.stats["students"]["updated"] == 0
    assert run2.stats["employees"]["created"] == 0
    assert run2.stats["departments"]["created"] == 0


async def test_sync_auth_error_marks_run_failed(hemis_settings):
    set_transport_for_tests(httpx.MockTransport(lambda r: httpx.Response(401)))
    run = await _run_sync()
    assert run.status == "xato"
    assert "401" in run.error
    assert run.finished_at is not None


async def test_sync_partial_failure_keeps_other_entities(hemis_settings, monkeypatch):
    monkeypatch.setattr(hemis, "BACKOFF_SECONDS", (0.0, 0.0, 0.0))
    data = _datasets()
    ok = _paged_handler(data)

    def handler(request):
        if request.url.path.endswith("group-list"):
            return httpx.Response(500)
        return ok(request)

    set_transport_for_tests(httpx.MockTransport(handler))
    run = await _run_sync()
    assert run.status == "xato"
    assert "Guruhlar" in run.error
    assert run.stats["groups"]["errors"] == 1
    assert run.stats["employees"]["created"] == 1


async def test_start_run_guards_overlap(hemis_settings):
    async with TestSessionLocal() as db:
        first = await hemis.start_run(db, "a")
        assert first is not None
        assert await hemis.start_run(db, "b") is None
        # 2 soatdan eski "ishlamoqda" — o'lgan deb hisoblanadi.
        stale = await db.get(IntegrationSyncRun, first.id)
        stale.started_at = datetime.now(timezone.utc) - timedelta(hours=3)
        await db.commit()
        second = await hemis.start_run(db, "c")
        assert second is not None
        await db.refresh(stale)
        assert stale.status == "xato"


async def test_scheduled_sync_due(hemis_settings, monkeypatch):
    monkeypatch.setattr(settings, "hemis_sync_interval_hours", 0)
    async with TestSessionLocal() as db:
        assert await hemis_job.is_sync_due(db) is False
    monkeypatch.setattr(settings, "hemis_sync_interval_hours", 6)
    async with TestSessionLocal() as db:
        assert await hemis_job.is_sync_due(db) is True
        db.add(IntegrationSyncRun(source="hemis", status="muvaffaqiyatli", triggered_by="x", started_at=datetime.now(timezone.utc) - timedelta(hours=2)))
        await db.commit()
        assert await hemis_job.is_sync_due(db) is False
        assert await hemis_job.is_sync_due(db, now=datetime.now(timezone.utc) + timedelta(hours=5)) is True


async def test_scheduled_sync_runs(hemis_settings, monkeypatch):
    monkeypatch.setattr(settings, "hemis_sync_interval_hours", 6)
    set_transport_for_tests(httpx.MockTransport(_paged_handler(_datasets())))
    assert await hemis_job.run_scheduled_sync_once() is True
    assert await hemis_job.run_scheduled_sync_once() is False
    async with TestSessionLocal() as db:
        runs = (await db.execute(select(IntegrationSyncRun))).scalars().all()
    assert len(runs) == 1 and runs[0].status == "muvaffaqiyatli" and runs[0].triggered_by == "tizim (jadval)"


# ── API ─────────────────────────────────────────────────────────────────────


async def test_api_permissions(client, seeded):
    operator = await auth_headers(client, "operator", "operator123")
    for method, path in (
        ("get", "/api/integrations/hemis/status"),
        ("post", "/api/integrations/hemis/test"),
        ("post", "/api/integrations/hemis/sync"),
        ("get", "/api/integrations/runs"),
    ):
        resp = await getattr(client, method)(path, headers=operator)
        assert resp.status_code == 403, path
        resp = await getattr(client, method)(path)
        assert resp.status_code == 401, path


async def test_api_not_configured(client, seeded, monkeypatch):
    monkeypatch.setattr(settings, "hemis_base_url", "")
    admin = await auth_headers(client, "admin", "admin123")
    status = await client.get("/api/integrations/hemis/status", headers=admin)
    assert status.status_code == 200 and status.json()["configured"] is False
    assert (await client.post("/api/integrations/hemis/sync", headers=admin)).status_code == 400
    assert (await client.post("/api/integrations/hemis/test", headers=admin)).status_code == 400


async def test_api_test_sync_and_history(client, seeded, hemis_settings):
    set_transport_for_tests(httpx.MockTransport(_paged_handler(_datasets())))
    admin = await auth_headers(client, "admin", "admin123")

    test = await client.post("/api/integrations/hemis/test", headers=admin)
    assert test.status_code == 200
    body = test.json()
    assert body["ok"] is True
    assert body["entities"]["students"]["total"] == 7
    assert "secret-token" not in json.dumps(body)

    started = await client.post("/api/integrations/hemis/sync", headers=admin)
    assert started.status_code == 202
    run_id = started.json()["runId"]
    # Fon vazifasi ishlayotganda ikkinchisi — 409.
    again = await client.post("/api/integrations/hemis/sync", headers=admin)
    assert again.status_code == 409
    await asyncio.gather(*list(hemis._background_tasks))

    run = await client.get(f"/api/integrations/runs/{run_id}", headers=admin)
    assert run.status_code == 200
    assert run.json()["status"] == "muvaffaqiyatli"
    assert run.json()["triggeredBy"] == "Jamshid Alimov"
    assert run.json()["stats"]["students"]["created"] >= 1

    status = (await client.get("/api/integrations/hemis/status", headers=admin)).json()
    assert status["configured"] is True
    assert status["baseUrl"] == BASE
    assert status["running"] is None
    assert status["lastRun"]["id"] == run_id
    assert status["lastSuccessAt"]
    assert "secret-token" not in json.dumps(status)

    runs = await client.get("/api/integrations/runs?source=hemis", headers=admin)
    assert runs.json()["total"] == 1
    missing = await client.get(f"/api/integrations/runs/{uuid.uuid4()}", headers=admin)
    assert missing.status_code == 404


async def test_api_test_reports_auth_error(client, seeded, hemis_settings):
    set_transport_for_tests(httpx.MockTransport(lambda r: httpx.Response(401)))
    admin = await auth_headers(client, "admin", "admin123")
    body = (await client.post("/api/integrations/hemis/test", headers=admin)).json()
    assert body["ok"] is False
    assert "401" in body["error"]


async def test_active_changes_announce_roster_change(hemis_settings, monkeypatch):
    """Faolsizlantirish/qayta faollashtirish — deactivated_at yoziladi/tozalanadi
    va yuz tanish keshi darhol yangilanadi (commit'dan keyin)."""
    announced = []

    async def fake_announce():
        async with TestSessionLocal() as db:
            row = (await db.execute(select(StudentStaff).where(StudentStaff.hemis_id == "S-A"))).scalar_one()
            announced.append(row.active)  # commit'dan keyin chaqirilgani tekshiriladi

    monkeypatch.setattr(hemis, "announce_roster_change", fake_announce)
    async with TestSessionLocal() as db:
        db.add(
            StudentStaff(
                full_name="Faol Talaba", type="talaba", hemis_id="S-A", group_or_position="2-kurs, DI-1",
                biometrics_status="tasdiqlangan", biometric_embedding="[0.3]",
            )
        )
        await db.commit()

    def dataset(status):
        return {"student-list": [_hemis_student("S-A", "FAOL TALABA", group="DI-1", status=status)]}

    set_transport_for_tests(httpx.MockTransport(_paged_handler(dataset("Chetlashtirilgan"))))
    run = await _run_sync()
    assert run.stats["students"]["deactivated"] == 1
    assert announced == [False]
    async with TestSessionLocal() as db:
        row = (await db.execute(select(StudentStaff).where(StudentStaff.hemis_id == "S-A"))).scalar_one()
        assert row.active is False and row.deactivated_at is not None
        assert row.biometric_embedding == "[0.3]"

    set_transport_for_tests(httpx.MockTransport(_paged_handler(dataset("O'qimoqda"))))
    run = await _run_sync()
    assert run.stats["students"]["updated"] == 1
    assert announced == [False, True]
    async with TestSessionLocal() as db:
        row = (await db.execute(select(StudentStaff).where(StudentStaff.hemis_id == "S-A"))).scalar_one()
        assert row.active is True and row.deactivated_at is None

    # Faollik o'zgarmadi — kesh tegilmaydi.
    await _run_sync()
    assert announced == [False, True]


# ── Moslash: JSHSHIRsiz HEMIS (fjsti, 2026-09-25) ──────────────────────────

def _row(full_name, *, pinfl=None, group="", hemis_id=None, type_="talaba"):
    from types import SimpleNamespace

    return SimpleNamespace(full_name=full_name, pinfl=pinfl, group_or_position=group, hemis_id=hemis_id, type=type_, id=full_name)


def _person(full_name, group=None):
    from app.services.integrations.hemis import HemisPerson

    return HemisPerson(type="talaba", hemis_id="H-" + full_name, full_name=full_name, pinfl=None, faculty_name=None,
                       group_name=group, course=None, position=None, department_name=None, active=True)


def _match(person, rows, people=None):
    from collections import Counter, defaultdict

    from app.services.integrations.hemis import _HemisSync, fuzzy_name_key, short_name_key
    from app.services.name_matching import name_key

    people = people or [person]
    by_name, by_fuzzy, by_short = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in rows:
        by_name[name_key(row.full_name)].append(row)
        by_fuzzy[fuzzy_name_key(row.full_name)].append(row)
        by_short[short_name_key(row.full_name)].append(row)
    match, _ = _HemisSync._match(
        person, {}, {}, by_name, Counter(name_key(p.full_name) for p in people),
        by_fuzzy, Counter(fuzzy_name_key(p.full_name) for p in people),
        by_short, Counter(short_name_key(p.full_name) for p in people),
    )
    return match


def test_row_with_pinfl_is_matched_by_name_when_hemis_has_none():
    row = _row("Usarov Barkamol Bahodir o'g'li", pinfl="30101990000011")
    assert _match(_person("USAROV BARKAMOL BAXODIR O‘G‘LI"), [row]) is row


def test_missing_patronymic_matches_a_unique_twin():
    row = _row("Usarov Barkamol", group="1-kurs, 101")
    assert _match(_person("USAROV BARKAMOL BAXODIR O‘G‘LI", group="101"), [row]) is row


def test_different_father_is_not_the_same_student():
    row = _row("Usarov Barkamol Rustamovich")
    assert _match(_person("USAROV BARKAMOL BAXODIR O‘G‘LI"), [row]) is None


def test_namesakes_are_split_by_group_or_left_alone():
    a, b = _row("Aliyev Anvar", group="1-kurs, 101"), _row("Aliyev Anvar", group="2-kurs, 202")
    assert _match(_person("ALIYEV ANVAR KARIM O‘G‘LI", group="202"), [a, b]) is b
    assert _match(_person("ALIYEV ANVAR KARIM O‘G‘LI", group="303"), [a, b]) is None


def test_weak_twin_with_a_different_group_is_rejected():
    row = _row("Usarov Barkamol", group="3-kurs, 305")
    assert _match(_person("USAROV BARKAMOL BAXODIR O‘G‘LI", group="101"), [row]) is None


async def test_sync_builds_org_tree_and_links_staff(hemis_settings):
    from app.models import OrgUnit

    async with TestSessionLocal() as db:
        # HEMIS'da yo'q, avval qo'lda kiritilgan xodim — bo'lim nomi bo'yicha bog'lanadi.
        db.add(StudentStaff(full_name="Qo'lda Kiritilgan", type="xodim", group_or_position="Anatomiya kafedrasi",
                            biometrics_status="yoq"))
        await db.commit()
    set_transport_for_tests(httpx.MockTransport(_paged_handler(_datasets())))
    run = await _run_sync()
    assert run.status == "muvaffaqiyatli", run.error

    async with TestSessionLocal() as db:
        units = {u.name: u for u in (await db.execute(select(OrgUnit))).scalars().all()}
        assert units["Pediatriya fakulteti"].kind == "fakultet"
        assert units["Anatomiya kafedrasi"].kind == "kafedra"
        assert units["Anatomiya kafedrasi"].parent_id == units["Pediatriya fakulteti"].id
        assert units["Buxgalteriya"].kind == "rektorat"  # kod 16
        people = {p.full_name: p for p in (await db.execute(select(StudentStaff))).scalars().all()}
        employee = people["Qayumov G'anisher"]
        assert employee.org_unit_id == units["Anatomiya kafedrasi"].id and employee.position == "Dotsent"
        assert people["Qo'lda Kiritilgan"].org_unit_id == units["Anatomiya kafedrasi"].id

    # Qayta ishga tushirish — bo'linmalar takrorlanmaydi.
    await _run_sync()
    async with TestSessionLocal() as db:
        assert len((await db.execute(select(OrgUnit))).scalars().all()) == len(DEPARTMENTS)
