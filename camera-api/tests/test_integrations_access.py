"""Turniket / kirish nazorati: normallashtirish, idempotent qabul qilish,
davomat (kechikish, check_out), Hikvision ISAPI so'rovi, webhook va API."""

import json
from datetime import date, datetime, time, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.config import settings
from app.crypto import decrypt, encrypt
from app.jobs import access_poll
from app.models import AccessDevice, AccessEvent, AttendanceRecord, StudentStaff
from app.services.integrations import access_control, hikvision_acs
from app.services.integrations.http import set_transport_for_tests
from app.timezone import INSTITUTE_TZ
from tests.conftest import TestSessionLocal, auth_headers


def _local(hour: int, minute: int = 0, day: date | None = None) -> datetime:
    day = day or datetime.now(INSTITUTE_TZ).date()
    return datetime.combine(day, time(hour, minute), tzinfo=INSTITUTE_TZ)


@pytest.fixture(autouse=True)
def _attendance_settings(monkeypatch):
    monkeypatch.setattr(settings, "attendance_ai_late_cutoff", "09:00")
    monkeypatch.setattr(settings, "attendance_late_window_end", "12:00")
    monkeypatch.setattr(settings, "attendance_arrival_only", False)
    monkeypatch.setattr(settings, "access_control_enabled", True)
    yield
    set_transport_for_tests(None)


@pytest.fixture
def notifications(monkeypatch):
    calls = {"attendance": [], "denied": [], "broadcast": []}

    async def fake_attendance(record, person, camera):
        calls["attendance"].append((record.student_staff_id, camera))

    async def fake_denied(device_name, person_name, card_number, occurred_at):
        calls["denied"].append((device_name, person_name, card_number))

    async def fake_broadcast(message):
        calls["broadcast"].append(message)

    monkeypatch.setattr(access_control, "notify_attendance", fake_attendance)
    monkeypatch.setattr(access_control, "notify_access_denied", fake_denied)
    monkeypatch.setattr(access_control.manager, "broadcast", fake_broadcast)
    return calls


async def _person(db, name="Aliyev Vali", card=None, hemis_id=None, pinfl=None, active=True, ptype="talaba"):
    person = StudentStaff(
        full_name=name,
        type=ptype,
        group_or_position="2-kurs, DI-1",
        biometrics_status="yoq",
        card_number=card,
        hemis_id=hemis_id,
        pinfl=pinfl,
        active=active,
    )
    db.add(person)
    await db.commit()
    return person


async def _device(db, **over):
    values = dict(name="Asosiy turniket", kind="webhook", direction="kirish", marks_attendance=True, enabled=True)
    values.update(over)
    device = AccessDevice(**values)
    db.add(device)
    await db.commit()
    return device


# ── sof funksiyalar ─────────────────────────────────────────────────────────


def test_normalize_webhook_event_generic_and_zk_aliases():
    event = access_control.normalize_webhook_event(
        {"id": 17, "time": "2026-09-19T08:15:00+05:00", "cardNo": "00123", "direction": "in", "granted": True}
    )
    assert event.external_id == "17" and event.card_number == "00123"
    assert event.direction == "kirish" and event.granted is True
    assert event.occurred_at == datetime(2026, 9, 19, 3, 15, tzinfo=timezone.utc)

    zk = access_control.normalize_webhook_event({"pin": "E-7", "checktime": "2026-09-19 18:01:02", "punch": 1})
    assert zk.employee_no == "E-7" and zk.direction == "chiqish"
    assert zk.occurred_at.tzinfo is not None and zk.occurred_at.hour == 18
    assert zk.external_id.startswith("E-7@")

    denied = access_control.normalize_webhook_event({"id": "x", "time": 1_758_250_000_000, "employeeNo": "5", "granted": "denied"})
    assert denied.granted is False

    with pytest.raises(ValueError):
        access_control.normalize_webhook_event({"id": 1, "time": "2026-09-19T08:00:00"})
    with pytest.raises(ValueError):
        access_control.normalize_webhook_event({"id": 1, "cardNo": "1"})


def test_parse_zkteco_attlog():
    body = "101\t2026-09-19 08:01:02\t0\t1\t0\n102\t2026-09-19 18:30:00\t1\t15\t0\nbroken line\n"
    events = access_control.parse_zkteco_attlog(body)
    assert [(e.employee_no, e.direction) for e in events] == [("101", "kirish"), ("102", "chiqish")]


def test_attendance_changes_rules():
    record = AttendanceRecord(status="keldi", check_in=time(8, 30), check_out=None)
    assert access_control._attendance_changes(record, time(8, 0), "kirish", False) == {
        "status": "keldi", "check_in": time(8, 0), "source": "turniket"
    }
    assert access_control._attendance_changes(record, time(9, 0), "kirish", False) == {}
    assert access_control._attendance_changes(record, time(17, 0), "chiqish", False) == {"check_out": time(17, 0)}
    assert access_control._attendance_changes(record, time(17, 0), None, False) == {"check_out": time(17, 0)}
    # ATTENDANCE_ARRIVAL_ONLY + track_last_seen: oxirgi ko'rinish check_out ga.
    assert access_control._attendance_changes(record, time(17, 0), "chiqish", True) == {"check_out": time(17, 0)}
    absent = AttendanceRecord(status="kelmadi", check_in=None, check_out=None)
    assert access_control._attendance_changes(absent, time(9, 30), "kirish", False)["status"] == "kech_keldi"
    off = AttendanceRecord(status="dam_olish", check_in=None, check_out=None)
    assert access_control._attendance_changes(off, time(9, 30), "kirish", False) == {}


def test_attendance_changes_arrival_only_follows_policy(monkeypatch):
    """ATTENDANCE_ARRIVAL_ONLY: turniket ham attendance_policy bo'yicha —
    09:00 chegarasi emas, 08:00 + 10 daqiqa; birinchi hodisa yo'nalishidan
    qat'i nazar kelish."""
    from app.services import attendance_policy

    monkeypatch.setattr(settings, "attendance_arrival_only", True)
    monkeypatch.setattr(attendance_policy, "_cached", attendance_policy.Policy(student_start=time(8, 30)))
    monkeypatch.setattr(attendance_policy, "_loaded_at", 1e12)  # keshni DB bosmasin
    absent = AttendanceRecord(status="kelmadi", check_in=None, check_out=None)
    assert access_control._attendance_changes(absent, time(8, 20), "chiqish", True) == {
        "status": "kech_keldi", "check_in": time(8, 20), "source": "turniket"
    }
    record = AttendanceRecord(status="keldi", check_in=time(8, 0), check_out=time(12, 0))
    assert access_control._attendance_changes(record, time(11, 0), "kirish", True) == {}
    assert access_control._attendance_changes(record, time(7, 50), "chiqish", True)["check_in"] == time(7, 50)


async def test_turnstile_student_uses_student_start(db_session, notifications, monkeypatch):
    from app.services import attendance_policy

    monkeypatch.setattr(settings, "attendance_arrival_only", True)
    monkeypatch.setattr(
        attendance_policy, "_cached", attendance_policy.Policy(staff_start=time(8, 0), student_start=time(9, 0))
    )
    monkeypatch.setattr(attendance_policy, "_loaded_at", 1e12)
    person = await _person(db_session, card="555", ptype="talaba")
    device = await _device(db_session)
    day = date(2026, 9, 21)  # dushanba
    result = await access_control.ingest_access_event(
        db_session, device, "s-1", _local(8, 30, day), "555", None, "kirish", True, None
    )
    assert result.attendance.status == "keldi" and result.attendance.check_in == time(8, 30)
    staff = await _person(db_session, name="Xodim", card="556", ptype="xodim")
    result = await access_control.ingest_access_event(
        db_session, device, "s-2", _local(8, 30, day), "556", None, "kirish", True, None
    )
    assert staff.id == result.attendance.student_staff_id and result.attendance.status == "kech_keldi"


def test_api_key_hashing():
    key = access_control.generate_api_key()
    assert key.startswith("ak_") and len(key) > 30
    stored = access_control.hash_api_key(key)
    assert stored != key
    assert access_control.verify_api_key(key, stored)
    assert not access_control.verify_api_key(key + "x", stored)
    assert not access_control.verify_api_key(None, stored)


def test_classify_minor_and_parse_acs_info():
    assert hikvision_acs.classify_minor(1) is True
    assert hikvision_acs.classify_minor(75) is True
    assert hikvision_acs.classify_minor(76) is False
    assert hikvision_acs.classify_minor(9) is False
    assert hikvision_acs.classify_minor(21) is None  # eshik holati — odam hodisasi emas
    event = hikvision_acs.parse_acs_info(
        {"major": 5, "minor": 75, "time": "2026-09-19T08:10:00+05:00", "serialNo": 42,
         "employeeNoString": "E-1", "attendanceStatus": "checkIn"}
    )
    assert event.granted is True and event.employee_no == "E-1" and event.direction == "kirish"
    assert event.external_id.startswith("42@")
    assert hikvision_acs.parse_acs_info({"major": 5, "minor": 22, "time": "2026-09-19T08:10:00+05:00"}) is None
    assert hikvision_acs.parse_acs_info({"major": 2, "minor": 1, "time": "2026-09-19T08:10:00+05:00"}) is None


def test_poll_start_time():
    now = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)
    fresh = AccessDevice(name="d", kind="hikvision", poll_cursor=None, last_event_at=None)
    start = hikvision_acs.poll_start_time(fresh, now)
    assert start.astimezone(INSTITUTE_TZ).time() == time(0, 0)
    cursor = AccessDevice(name="d", kind="hikvision", poll_cursor="2026-09-19T14:00:00+05:00")
    assert hikvision_acs.poll_start_time(cursor, now) == datetime(2026, 9, 19, 8, 59, tzinfo=timezone.utc)
    old = AccessDevice(name="d", kind="hikvision", poll_cursor="2026-01-01T00:00:00+05:00")
    assert hikvision_acs.poll_start_time(old, now) == now - hikvision_acs.MAX_BACKFILL


# ── qabul qilish va davomat ─────────────────────────────────────────────────


async def test_ingest_first_arrival_idempotent_and_checkout(notifications):
    async with TestSessionLocal() as db:
        person = await _person(db, card="0012345")
        entrance = await _device(db, name="Kirish", direction="kirish")
        exit_device = await _device(db, name="Chiqish", direction="chiqish")

        result = await access_control.ingest_access_event(
            db, entrance, "e1", _local(8, 40), "12345", None, None, True, {"k": 1}
        )
        assert not result.duplicate and result.attendance_created
        assert result.person.id == person.id  # boshidagi nollarsiz ham topildi
        record = result.attendance
        assert record.status == "keldi" and record.check_in == time(8, 40) and record.source == "turniket"

        again = await access_control.ingest_access_event(
            db, entrance, "e1", _local(8, 40), "12345", None, None, True, {"k": 1}
        )
        assert again.duplicate

        out = await access_control.ingest_access_event(
            db, exit_device, "x1", _local(17, 5), "0012345", None, None, True, None
        )
        assert not out.attendance_created
        assert out.attendance.check_out == time(17, 5)
        assert out.attendance.check_in == time(8, 40)

        events = (await db.execute(select(AccessEvent))).scalars().all()
        assert len(events) == 2
        assert all(e.student_staff_id == person.id for e in events)
        await db.refresh(entrance)
        assert entrance.last_event_at == _local(8, 40)

    assert len(notifications["attendance"]) == 1
    assert notifications["attendance"][0] == (person.id, None)
    assert len(notifications["broadcast"]) == 1
    message = notifications["broadcast"][0]
    assert message["kind"] == "attendance_recorded" and message["camera"] == "Kirish" and message["checkIn"] == "08:40"


async def test_ingest_late_arrival_by_employee_no(notifications):
    async with TestSessionLocal() as db:
        person = await _person(db, hemis_id="E-77", ptype="xodim")
        device = await _device(db, direction="kirish")
        result = await access_control.ingest_access_event(db, device, "a", _local(9, 25), None, "E-77", None, True, None)
        assert result.person.id == person.id
        assert result.attendance.status == "kech_keldi" and result.attendance.check_in == time(9, 25)

        # Kechikib so'ralgan, lekin undan oldingi kirish — turniket vaqti ustun.
        earlier = await access_control.ingest_access_event(db, device, "b", _local(8, 50), None, "E-77", None, True, None)
        assert earlier.attendance.status == "keldi" and earlier.attendance.check_in == time(8, 50)


async def test_ingest_pinfl_match_and_unmatched(notifications):
    async with TestSessionLocal() as db:
        person = await _person(db, pinfl="12345678901234")
        device = await _device(db)
        matched = await access_control.ingest_access_event(db, device, "p", _local(8), None, "12345678901234", None, True, None)
        assert matched.person.id == person.id
        unknown = await access_control.ingest_access_event(db, device, "u", _local(8), "999", None, None, True, None)
        assert unknown.person is None and unknown.attendance is None
        event = (await db.execute(select(AccessEvent).where(AccessEvent.external_id == "u"))).scalar_one()
        assert event.student_staff_id is None and event.card_number == "999"


async def test_ingest_denied_notifies_without_attendance(notifications):
    async with TestSessionLocal() as db:
        await _person(db, name="Rad Etilgan", card="C-1")
        device = await _device(db, name="Turniket 2")
        now = datetime.now(timezone.utc)
        result = await access_control.ingest_access_event(db, device, "d1", now, "C-1", None, None, False, None)
        assert result.attendance is None
        # Eski rad etilish (qurilma tarixni kechikib bergan) — signal yo'q.
        await access_control.ingest_access_event(db, device, "d2", now - timedelta(hours=3), "C-1", None, None, False, None)
        records = (await db.execute(select(AttendanceRecord))).scalars().all()
        assert records == []
    assert notifications["denied"] == [("Turniket 2", "Rad Etilgan", "C-1")]
    assert notifications["attendance"] == []


async def test_ingest_respects_marks_attendance_and_inactive(notifications):
    async with TestSessionLocal() as db:
        await _person(db, name="Faol Emas", card="IN-1", active=False)
        await _person(db, name="Jurnal Faqat", card="LOG-1")
        log_only = await _device(db, marks_attendance=False)
        normal = await _device(db, name="Normal")
        r1 = await access_control.ingest_access_event(db, log_only, "1", _local(8), "LOG-1", None, None, True, None)
        r2 = await access_control.ingest_access_event(db, normal, "2", _local(8), "IN-1", None, None, True, None)
        assert r1.person is not None and r1.attendance is None
        assert r2.person is not None and r2.attendance is None


async def test_ingest_both_directions_device_and_absent_fix(notifications):
    async with TestSessionLocal() as db:
        person = await _person(db, card="B-1")
        device = await _device(db, direction="ikkalasi")
        db.add(AttendanceRecord(student_staff_id=person.id, date=_local(8).date(), status="kelmadi"))
        await db.commit()
        first = await access_control.ingest_access_event(db, device, "1", _local(8, 20), "B-1", None, None, True, None)
        assert first.attendance.status == "keldi" and first.attendance.check_in == time(8, 20)
        assert not first.attendance_created
        second = await access_control.ingest_access_event(db, device, "2", _local(16, 0), "B-1", None, None, True, None)
        assert second.attendance.check_out == time(16, 0)
        # Hodisaning o'z yo'nalishi qurilmanikidan ustun.
        third = await access_control.ingest_access_event(db, device, "3", _local(7, 55), "B-1", None, "in", True, None)
        assert third.attendance.check_in == time(7, 55)


# ── Hikvision ISAPI ─────────────────────────────────────────────────────────


def _acs_response(infos, status="OK"):
    return {"AcsEvent": {"searchID": "x", "responseStatusStrg": status, "numOfMatches": len(infos), "totalMatches": 3, "InfoList": infos}}


async def test_hikvision_poll_paginates_and_ingests(notifications):
    requests = []
    day = datetime.now(INSTITUTE_TZ).date().isoformat()
    pages = [
        _acs_response(
            [
                {"major": 5, "minor": 75, "time": f"{day}T08:10:00+05:00", "serialNo": 1, "employeeNoString": "E-1"},
                {"major": 5, "minor": 21, "time": f"{day}T08:10:01+05:00", "serialNo": 2},
            ],
            "MORE",
        ),
        _acs_response(
            [{"major": 5, "minor": 9, "time": f"{day}T08:12:00+05:00", "serialNo": 3, "cardNo": "777"}], "OK"
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ISAPI/AccessControl/AcsEvent"
        body = json.loads(request.content)
        requests.append(body["AcsEventCond"])
        return httpx.Response(200, json=pages[len(requests) - 1])

    set_transport_for_tests(httpx.MockTransport(handler))
    async with TestSessionLocal() as db:
        person = await _person(db, hemis_id="E-1", ptype="xodim")
        device = await _device(
            db, kind="hikvision", ip="10.0.0.5", port=80, username=encrypt("admin"), password=encrypt("pw")
        )
        result = await hikvision_acs.poll_device(db, device)
        assert result.error is None
        assert result.fetched == 2 and result.accepted == 2
        assert requests[0]["searchResultPosition"] == 0 and requests[1]["searchResultPosition"] == 2
        assert requests[0]["major"] == 5 and requests[0]["minor"] == 0
        assert requests[0]["searchID"] == requests[1]["searchID"]
        await db.refresh(device)
        assert device.last_error is None and device.last_poll_at is not None
        assert device.poll_cursor.endswith("08:12:00+05:00")
        record = (await db.execute(select(AttendanceRecord))).scalar_one()
        assert record.student_staff_id == person.id and record.check_in == time(8, 10)
        denied = (await db.execute(select(AccessEvent).where(AccessEvent.card_number == "777"))).scalar_one()
        assert denied.granted is False

        # Qayta so'rov — shu hodisalar takror yozilmaydi.
        requests.clear()
        pages[:] = [_acs_response([{"major": 5, "minor": 75, "time": f"{day}T08:10:00+05:00", "serialNo": 1, "employeeNoString": "E-1"}])]
        again = await hikvision_acs.poll_device(db, device)
        assert again.duplicates == 1 and again.accepted == 0
        assert requests[0]["startTime"].endswith("08:11:00+05:00")


async def test_hikvision_poll_records_auth_error(notifications):
    set_transport_for_tests(httpx.MockTransport(lambda r: httpx.Response(401)))
    async with TestSessionLocal() as db:
        device = await _device(db, kind="hikvision", ip="10.0.0.6", username=encrypt("admin"), password=encrypt("bad"))
        result = await hikvision_acs.poll_device(db, device)
        assert "401" in result.error
        await db.refresh(device)
        assert "401" in device.last_error and device.last_poll_at is not None


async def test_access_poll_loop_iteration(notifications, monkeypatch):
    set_transport_for_tests(httpx.MockTransport(lambda r: httpx.Response(200, json=_acs_response([]))))
    async with TestSessionLocal() as db:
        await _device(db, kind="hikvision", ip="10.0.0.7", username=encrypt("a"), password=encrypt("b"))
        await _device(db, kind="hikvision", ip="10.0.0.8", username=encrypt("a"), password=encrypt("b"), enabled=False)
        await _device(db, kind="webhook")
    assert await access_poll.run_access_poll_once(TestSessionLocal) == 1
    monkeypatch.setattr(settings, "access_control_enabled", False)
    assert await access_poll.run_access_poll_once(TestSessionLocal) == 0


# ── API ─────────────────────────────────────────────────────────────────────


async def test_device_api_permissions(client, seeded):
    operator = await auth_headers(client, "operator", "operator123")
    for method, path in (
        ("get", "/api/access/devices"),
        ("get", "/api/access/events"),
        ("get", "/api/access/unmatched"),
        ("get", "/api/access/summary"),
    ):
        assert (await getattr(client, method)(path, headers=operator)).status_code == 403
        assert (await getattr(client, method)(path)).status_code == 401
    resp = await client.post("/api/access/devices", json={"name": "x", "kind": "webhook"}, headers=operator)
    assert resp.status_code == 403


async def test_device_crud_and_secrets(client, seeded, db_session):
    admin = await auth_headers(client, "admin", "admin123")
    bad = await client.post("/api/access/devices", json={"name": "H", "kind": "hikvision"}, headers=admin)
    assert bad.status_code == 422

    created = await client.post(
        "/api/access/devices",
        json={"name": "Hik 1", "kind": "hikvision", "ip": "10.0.0.9", "port": 80, "username": "admin", "password": "S3cret!"},
        headers=admin,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["apiKey"] is None and body["hasPassword"] is True and body["username"] == "admin"
    assert "S3cret!" not in json.dumps(body)
    device = await db_session.get(AccessDevice, body["id"])
    assert device.password != "S3cret!" and decrypt(device.password) == "S3cret!"

    patched = await client.patch(
        f"/api/access/devices/{body['id']}", json={"name": "Hik asosiy", "direction": "ikkalasi"}, headers=admin
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Hik asosiy" and patched.json()["hasPassword"] is True
    await db_session.refresh(device)
    assert decrypt(device.password) == "S3cret!"

    listed = await client.get("/api/access/devices", headers=admin)
    assert [d["name"] for d in listed.json()] == ["Hik asosiy"]
    assert "password" not in listed.json()[0]

    assert (await client.post(f"/api/access/devices/{body['id']}/rotate-key", headers=admin)).status_code == 400
    assert (await client.delete(f"/api/access/devices/{body['id']}", headers=admin)).status_code == 204
    assert (await client.get("/api/access/devices", headers=admin)).json() == []


async def test_device_test_endpoint_hikvision(client, seeded, db_session):
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><DeviceInfo xmlns="http://www.hikvision.com/ver20/XMLSchema">'
        "<deviceName>Kirish</deviceName><model>DS-K1T671M</model><serialNumber>ABC123</serialNumber>"
        "<firmwareVersion>V3.2.30</firmwareVersion></DeviceInfo>"
    )
    set_transport_for_tests(
        httpx.MockTransport(
            lambda r: httpx.Response(200, text=xml) if r.url.path == "/ISAPI/System/deviceInfo" else httpx.Response(404)
        )
    )
    admin = await auth_headers(client, "admin", "admin123")
    created = await client.post(
        "/api/access/devices",
        json={"name": "Hik", "kind": "hikvision", "ip": "10.0.0.10", "username": "admin", "password": "x"},
        headers=admin,
    )
    resp = await client.post(f"/api/access/devices/{created.json()['id']}/test", headers=admin)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["info"]["model"] == "DS-K1T671M"

    set_transport_for_tests(httpx.MockTransport(lambda r: httpx.Response(401)))
    failed = await client.post(f"/api/access/devices/{created.json()['id']}/test", headers=admin)
    assert failed.json()["ok"] is False and "401" in failed.json()["message"]


async def test_webhook_flow(client, seeded, db_session, notifications):
    admin = await auth_headers(client, "admin", "admin123")
    person = await _person(db_session, name="Webhook Talaba", card="W-1")
    created = await client.post(
        "/api/access/devices", json={"name": "Oraliq dastur", "kind": "webhook", "direction": "kirish"}, headers=admin
    )
    assert created.status_code == 201
    device = created.json()
    key = device["apiKey"]
    assert key and device["webhookPath"] == f"/api/access/webhook/{device['id']}"
    stored = await db_session.get(AccessDevice, device["id"])
    assert stored.api_key_hash and key not in stored.api_key_hash
    listed = (await client.get("/api/access/devices", headers=admin)).json()
    assert "apiKey" not in listed[0] and listed[0]["hasApiKey"] is True

    url = device["webhookPath"]
    payload = {
        "events": [
            {"id": "1", "time": _local(8, 5).isoformat(), "cardNo": "W-1"},
            {"id": "2", "time": _local(8, 6).isoformat(), "cardNo": "NOPE"},
            {"id": "3", "time": "bad"},
        ]
    }
    assert (await client.post(url, json=payload)).status_code == 401
    assert (await client.post(url, json=payload, headers={"X-Api-Key": "ak_wrong"})).status_code == 401
    assert (await client.post("/api/access/webhook/not-a-uuid", json=payload, headers={"X-Api-Key": key})).status_code == 401

    ok = await client.post(url, json=payload, headers={"X-Api-Key": key})
    assert ok.status_code == 200
    assert ok.json()["accepted"] == 2 and ok.json()["matched"] == 1 and ok.json()["attendance"] == 1
    assert ok.json()["rejected"][0]["index"] == 2
    replay = await client.post(url, json=payload, headers={"X-Api-Key": key})
    assert replay.json()["duplicates"] == 2 and replay.json()["accepted"] == 0

    record = (
        await db_session.execute(select(AttendanceRecord).where(AttendanceRecord.student_staff_id == person.id))
    ).scalar_one()
    assert record.source == "turniket" and record.check_in == time(8, 5)

    # ZKTeco ATTLOG matni.
    zk = await client.post(
        url,
        content=f"W-9\t{_local(9, 0).strftime('%Y-%m-%d %H:%M:%S')}\t0\t1\n",
        headers={"X-Api-Key": key, "Content-Type": "text/plain"},
    )
    assert zk.status_code == 200 and zk.json()["accepted"] == 1

    # Kalit almashtirildi — eskisi ishlamaydi.
    rotated = await client.post(f"/api/access/devices/{device['id']}/rotate-key", headers=admin)
    new_key = rotated.json()["apiKey"]
    assert new_key != key
    assert (await client.post(url, json=payload, headers={"X-Api-Key": key})).status_code == 401
    assert (await client.post(url, json=payload, headers={"X-Api-Key": new_key})).status_code == 200

    # O'chirilgan qurilma — 403.
    await client.patch(f"/api/access/devices/{device['id']}", json={"enabled": False}, headers=admin)
    assert (await client.post(url, json=payload, headers={"X-Api-Key": new_key})).status_code == 403

    # Jurnal va biriktirilmagan kartalar.
    events = await client.get("/api/access/events?pageSize=50", headers=admin)
    assert events.json()["total"] == 3
    names = {e["cardNumber"]: e["personName"] for e in events.json()["items"]}
    assert names["W-1"] == "Webhook Talaba" and names["NOPE"] is None
    filtered = await client.get(f"/api/access/events?personId={person.id}", headers=admin)
    assert filtered.json()["total"] == 1
    searched = await client.get("/api/access/events?search=Webhook", headers=admin)
    assert searched.json()["total"] == 1
    unmatched_only = await client.get("/api/access/events?matched=false", headers=admin)
    assert unmatched_only.json()["total"] == 2

    unmatched = (await client.get("/api/access/unmatched", headers=admin)).json()
    assert {(u["cardNumber"], u["employeeNo"]) for u in unmatched} == {("NOPE", None), (None, "W-9")}
    assert unmatched[0]["lastDeviceName"] == "Oraliq dastur"

    # Karta keyinroq biriktirildi — ro'yxatdan chiqadi.
    await _person(db_session, name="Kartasi Yangi", card="NOPE")
    unmatched = (await client.get("/api/access/unmatched", headers=admin)).json()
    assert [(u["cardNumber"], u["employeeNo"]) for u in unmatched] == [(None, "W-9")]


async def test_webhook_rejects_non_push_device(client, seeded, db_session):
    device = await _device(db_session, kind="hikvision", ip="1.2.3.4", api_key_hash=access_control.hash_api_key("ak_x"))
    resp = await client.post(f"/api/access/webhook/{device.id}", json={"events": []}, headers={"X-Api-Key": "ak_x"})
    assert resp.status_code == 401


async def test_events_direction_filter_and_summary(client, seeded, db_session):
    admin = await auth_headers(client, "admin", "admin123")
    device = await _device(db_session)
    other = await _device(db_session, name="Ikkinchi")
    person = await _person(db_session, card="C-1")
    today = datetime.now(INSTITUTE_TZ).date()
    rows = [
        ("e1", device.id, _local(8, 0), "kirish", True, person.id),
        ("e2", device.id, _local(17, 0), "chiqish", True, person.id),
        ("e3", device.id, _local(9, 0), "kirish", False, None),
        ("e4", other.id, _local(10, 0), "kirish", True, None),
        ("e5", device.id, _local(8, 0, today - timedelta(days=1)), "kirish", True, person.id),
    ]
    for ext, dev, when, direction, granted, pid in rows:
        db_session.add(
            AccessEvent(
                external_id=ext, device_id=dev, occurred_at=when, direction=direction, granted=granted,
                student_staff_id=pid, card_number="C-1" if pid else "X",
            )
        )
    await db_session.commit()

    day = today.isoformat()
    exits = (await client.get(f"/api/access/events?direction=chiqish&from={day}&to={day}", headers=admin)).json()
    assert [e["id"] for e in exits["items"]] and exits["total"] == 1
    entries = await client.get(f"/api/access/events?direction=kirish&from={day}&to={day}", headers=admin)
    assert entries.json()["total"] == 3
    assert (await client.get("/api/access/events?direction=boshqa", headers=admin)).status_code == 422

    summary = (await client.get("/api/access/summary", headers=admin)).json()
    assert summary == {
        "date": day, "total": 4, "entries": 3, "exits": 1, "denied": 1, "unmatched": 2, "people": 1,
    }
    by_device = (await client.get(f"/api/access/summary?deviceId={other.id}&date={day}", headers=admin)).json()
    assert by_device["total"] == 1 and by_device["people"] == 0