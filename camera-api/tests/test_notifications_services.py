"""Bildirishnomalar: telefon formati, matnlar, qoida tanlash, Telegram/Eskiz
mijozlari va dispatcher (fondagi yuborish + notification_log)."""

import uuid
from datetime import date, datetime, time, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.config import settings
from app.models import AttendanceRecord, Building, Camera, Event, NotificationLog, NotificationRule, StudentStaff, User
from app.services.notifications import (
    dispatcher,
    messages,
    notify_absences,
    notify_access_denied,
    notify_attendance,
    notify_camera_status,
    notify_event,
    notify_event_overdue,
    notify_user,
    sms,
    telegram,
)
from app.services.notifications.http import set_transport_for_tests
from app.services.notifications.sms import normalize_phone
from app.timezone import local_now
from tests.notify_fakes import TG_TOKEN, apis  # noqa: F401 — fixture

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Sof funksiyalar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+998 90 123-45-67", "+998901234567"),
        ("998901234567", "+998901234567"),
        ("90 123 45 67", "+998901234567"),
        ("8 90 123 45 67", "+998901234567"),
        ("(97) 000-11-22", "+998970001122"),
        ("+7 999 123 45 67", None),
        ("12345", None),
        ("", None),
        (None, None),
    ],
)
async def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def _rule(**kw) -> NotificationRule:
    base = {"name": "r", "enabled": True, "channel": "telegram", "recipients": ["1"], "kinds": ["event"]}
    base.update(kw)
    return NotificationRule(**base)


async def test_rule_matches_filters():
    building = uuid.uuid4()
    assert dispatcher.rule_matches(_rule(), "event", module_code=3, severity="past")
    assert not dispatcher.rule_matches(_rule(enabled=False), "event")
    assert not dispatcher.rule_matches(_rule(), "camera_offline")
    # Modul filtri
    assert dispatcher.rule_matches(_rule(module_codes=[3, 7]), "event", module_code=7)
    assert not dispatcher.rule_matches(_rule(module_codes=[3]), "event", module_code=7)
    # Og'irlik: past < o'rta < yuqori
    strict = _rule(min_severity="o'rta")
    assert not dispatcher.rule_matches(strict, "event", severity="past")
    assert dispatcher.rule_matches(strict, "event", severity="o'rta")
    assert dispatcher.rule_matches(strict, "event", severity="yuqori")
    # Bino filtri — binosi noma'lum signal o'tmaydi
    by_building = _rule(kinds=["event", "camera_offline"], building_ids=[str(building)])
    assert dispatcher.rule_matches(by_building, "camera_offline", building_id=building)
    assert not dispatcher.rule_matches(by_building, "camera_offline", building_id=uuid.uuid4())
    assert not dispatcher.rule_matches(by_building, "event", building_id=None)
    # Modul va og'irlik filtri kamera holatiga taalluqli emas
    cam_rule = _rule(kinds=["camera_online"], module_codes=[1], min_severity="yuqori")
    assert dispatcher.rule_matches(cam_rule, "camera_online")


async def test_event_message_format(monkeypatch):
    monkeypatch.setattr(settings, "frontend_base_url", "https://markaz.example.uz/")
    msg = messages.event_message(
        event_id="abc",
        module_name="Yong'in <aniqlash>",
        camera_name="Kirish-1",
        building="Bosh bino",
        severity="yuqori",
        occurred_at=datetime(2026, 9, 19, 9, 5, 7, tzinfo=timezone.utc),
        person_name=None,
        confidence=91,
    )
    html_text = msg.html()
    assert html_text.startswith("<b>AI hodisa: Yong&#x27;in &lt;aniqlash&gt;</b>")
    assert "Kamera: Kirish-1" in html_text
    assert "Bino: Bosh bino" in html_text
    assert "Daraja: Yuqori" in html_text
    # UTC 09:05 -> Toshkent 14:05
    assert "Vaqt: 19.09.2026 14:05:07" in html_text
    assert '<a href="https://markaz.example.uz/hodisalar?id=abc">Hodisani ochish</a>' in html_text
    assert "Shaxs" not in html_text  # bo'sh qiymat yozilmaydi
    plain = msg.plain()
    assert "<" not in plain.replace("<aniqlash>", "")
    assert plain.endswith("https://markaz.example.uz/hodisalar?id=abc")
    assert msg.sms().startswith(f"{settings.org_name}: AI hodisa: Yong'in <aniqlash>. Kirish-1, Bosh bino, Yuqori")


async def test_parent_texts(monkeypatch):
    monkeypatch.setattr(settings, "org_name", "Farg'ona JSSTI")
    assert (
        messages.parent_arrival_text("Aliyev Vali", time(8, 12))
        == "Farg'ona JSSTI: Farzandingiz Aliyev Vali 08:12 da institutga keldi."
    )
    today = local_now().date()
    assert f"bugun ({today.strftime('%d.%m.%Y')})" in messages.parent_absence_text("Aliyev Vali", today)
    assert "18.09.2026 kuni" in messages.parent_absence_text("Aliyev Vali", date(2026, 9, 18))


# ---------------------------------------------------------------------------
# Telegram mijozi
# ---------------------------------------------------------------------------


async def test_telegram_send_message_html(apis):
    result = await telegram.send_message("42", "<b>Salom</b>")
    assert result.ok
    call = apis.of("sendMessage")[0]
    assert call.body == {"chat_id": "42", "text": "<b>Salom</b>", "disable_web_page_preview": True, "parse_mode": "HTML"}


async def test_telegram_429_retry_after(apis):
    apis.queue("sendMessage", 429, {"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 3}})
    result = await telegram.send_message("42", "x")
    assert result.ok
    assert len(apis.of("sendMessage")) == 2


async def test_telegram_429_too_long_gives_up(apis):
    apis.queue("sendMessage", 429, {"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 600}})
    result = await telegram.send_message("42", "x")
    assert not result.ok
    assert "600" in result.error
    assert len(apis.of("sendMessage")) == 1


async def test_telegram_403_blocked(apis):
    apis.queue("sendMessage", 403, {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"})
    result = await telegram.send_message("42", "x")
    assert not result.ok and result.blocked
    assert len(apis.of("sendMessage")) == 1


async def test_telegram_parse_error_falls_back_to_plain(apis):
    apis.queue("sendMessage", 400, {"ok": False, "error_code": 400, "description": "Bad Request: can't parse entities"})
    result = await telegram.send_message("42", "<b>A &amp; B</b>")
    assert result.ok
    second = apis.of("sendMessage")[1].body
    assert "parse_mode" not in second
    assert second["text"] == "A & B"


async def test_telegram_errors_never_leak_token(apis):
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect to {request.url}")

    set_transport_for_tests(httpx.MockTransport(boom))
    result = await telegram.send_message("42", "x")
    assert not result.ok
    assert TG_TOKEN not in result.error
    assert "***" in result.error


async def test_httpx_request_log_hides_token(apis, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="httpx"):
        await telegram.send_message("42", "x")
    logged = " | ".join(record.getMessage() for record in caplog.records)
    assert "sendMessage" in logged
    assert TG_TOKEN not in logged


async def test_telegram_not_configured(apis, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    result = await telegram.send_message("42", "x")
    assert not result.ok and "sozlanmagan" in result.error
    assert apis.calls == []


async def test_bot_username_from_get_me_is_cached(apis):
    assert await telegram.bot_username() == "situatsion_bot"
    assert await telegram.bot_username() == "situatsion_bot"
    assert len(apis.of("getMe")) == 1


async def test_bot_username_failure_is_cached_briefly(apis):
    apis.queue("getMe", 401, {"ok": False, "error_code": 401, "description": "Unauthorized"})
    assert await telegram.bot_username() is None
    assert await telegram.bot_username() is None
    assert len(apis.of("getMe")) == 1


# ---------------------------------------------------------------------------
# Eskiz SMS
# ---------------------------------------------------------------------------


async def test_eskiz_login_cached_and_payload(apis):
    assert (await sms.send_sms("+998 90 123 45 67", "Salom")).ok
    assert (await sms.send_sms("901234568", "Yana")).ok
    assert len(apis.of("auth/login")) == 1
    login = apis.of("auth/login")[0].body
    assert login == {"email": "ops@example.uz", "password": "eskiz-pw-secret"}
    sends = apis.of("message/sms/send")
    assert [s.body["mobile_phone"] for s in sends] == ["998901234567", "998901234568"]
    assert sends[0].body["from"] == settings.eskiz_sender
    assert sends[0].body["message"] == "Salom"
    assert sends[0].headers["authorization"] == "Bearer eskiz-token-1"


async def test_eskiz_refreshes_token_on_401(apis):
    assert (await sms.send_sms("+998901234567", "1")).ok
    apis.queue("message/sms/send", 401, {"message": "Expired"})
    assert (await sms.send_sms("+998901234567", "2")).ok
    assert len(apis.of("auth/login")) == 2
    assert apis.of("message/sms/send")[-1].headers["authorization"] == "Bearer eskiz-token-2"


async def test_eskiz_rejects_bad_phone_and_reports_errors(apis):
    bad = await sms.send_sms("12345", "x")
    assert not bad.ok and "noto'g'ri" in bad.error
    apis.queue("message/sms/send", 400, {"message": "Insufficient balance", "status": "error"})
    failed = await sms.send_sms("+998901234567", "x")
    assert not failed.ok and "Insufficient balance" in failed.error
    assert "eskiz-pw-secret" not in failed.error


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


async def _camera(db, name="Kirish-1") -> tuple[Building, Camera]:
    building = Building(name=f"Bino {uuid.uuid4().hex[:6]}")
    db.add(building)
    await db.flush()
    camera = Camera(name=name, ip="10.0.0.5", port=554, building_id=building.id, zone="Z", resolution="1080p", status="faol")
    db.add(camera)
    await db.commit()
    return building, camera


def _event(camera: Camera, building: Building, **kw) -> Event:
    base = dict(
        camera_id=camera.id,
        camera_name=camera.name,
        building=building.name,
        module_code=3,
        module_name="Yong'in aniqlash",
        group="Xavfsizlik",
        confidence=90,
        severity="yuqori",
        status="yangi",
        occurred_at=datetime(2026, 9, 19, 4, 0, tzinfo=timezone.utc),
        is_trial=False,
    )
    base.update(kw)
    return Event(**base)


async def _logs(db) -> list[NotificationLog]:
    stmt = select(NotificationLog).order_by(NotificationLog.created_at).execution_options(populate_existing=True)
    return list((await db.execute(stmt)).scalars().all())


async def test_notify_event_sends_to_matching_rules_and_logs(apis, db_session):
    building, camera = await _camera(db_session)
    db_session.add_all(
        [
            NotificationRule(name="Navbatchilar", channel="telegram", recipients=["111", "-100222"], kinds=["event"]),
            NotificationRule(name="Rahbar SMS", channel="sms", recipients=["+998901112233"], kinds=["event"], min_severity="yuqori"),
            NotificationRule(name="Faqat kamera", channel="telegram", recipients=["999"], kinds=["camera_offline"]),
            NotificationRule(name="O'chiq", channel="telegram", recipients=["888"], kinds=["event"], enabled=False),
        ]
    )
    event = _event(camera, building)
    db_session.add(event)
    await db_session.commit()

    await notify_event(event)
    await dispatcher.wait_for_pending()

    tg = apis.of("sendMessage")
    assert sorted(c.body["chat_id"] for c in tg) == ["-100222", "111"]
    assert "AI hodisa: Yong&#x27;in aniqlash" in tg[0].body["text"]
    assert f"/hodisalar?id={event.id}" in tg[0].body["text"]
    assert "Vaqt: 19.09.2026 09:00:00" in tg[0].body["text"]
    sent_sms = apis.of("message/sms/send")
    assert len(sent_sms) == 1 and sent_sms[0].body["mobile_phone"] == "998901112233"

    logs = await _logs(db_session)
    assert len(logs) == 3
    assert {log.status for log in logs} == {"yuborildi"}
    assert {log.ref_id for log in logs} == {str(event.id)}
    assert {log.kind for log in logs} == {"event"}


async def test_notify_event_skips_trial_and_filtered(apis, db_session):
    building, camera = await _camera(db_session)
    db_session.add(NotificationRule(name="Jiddiy", channel="telegram", recipients=["111"], kinds=["event"], min_severity="yuqori"))
    trial = _event(camera, building, is_trial=True)
    minor = _event(camera, building, severity="past")
    db_session.add_all([trial, minor])
    await db_session.commit()

    await notify_event(trial)
    await notify_event(minor)
    await dispatcher.wait_for_pending()
    assert apis.calls == []
    assert await _logs(db_session) == []


async def test_notify_event_building_and_module_filter(apis, db_session):
    building, camera = await _camera(db_session)
    other_building, _ = await _camera(db_session, name="Boshqa")
    db_session.add_all(
        [
            NotificationRule(name="Shu bino", channel="telegram", recipients=["1"], kinds=["event"], building_ids=[str(building.id)]),
            NotificationRule(name="Boshqa bino", channel="telegram", recipients=["2"], kinds=["event"], building_ids=[str(other_building.id)]),
            NotificationRule(name="Boshqa modul", channel="telegram", recipients=["3"], kinds=["event"], module_codes=[99]),
            NotificationRule(name="Shu modul", channel="telegram", recipients=["4"], kinds=["event"], module_codes=[3]),
        ]
    )
    event = _event(camera, building)
    db_session.add(event)
    await db_session.commit()

    await notify_event(event)
    await dispatcher.wait_for_pending()
    assert sorted(c.body["chat_id"] for c in apis.of("sendMessage")) == ["1", "4"]


async def test_notify_event_burst_is_throttled(apis, db_session):
    building, camera = await _camera(db_session)
    db_session.add(NotificationRule(name="Navbatchi", channel="telegram", recipients=["111"], kinds=["event"]))
    first, second = _event(camera, building), _event(camera, building)
    other_module = _event(camera, building, module_code=4, module_name="Tutun")
    db_session.add_all([first, second, other_module])
    await db_session.commit()

    for event in (first, second, other_module):
        await notify_event(event)
        await dispatcher.wait_for_pending()

    assert len(apis.of("sendMessage")) == 2  # birinchisi va boshqa modul
    logs = await _logs(db_session)
    skipped = [log for log in logs if log.status == "otkazildi"]
    assert len(skipped) == 1 and skipped[0].ref_id == str(second.id)
    assert "Takroriy signal" in skipped[0].error


async def test_notify_event_same_recipient_in_two_rules_gets_one_message(apis, db_session):
    building, camera = await _camera(db_session)
    db_session.add_all(
        [
            NotificationRule(name="A", channel="telegram", recipients=["111"], kinds=["event"]),
            NotificationRule(name="B", channel="telegram", recipients=["111", "222"], kinds=["event"]),
        ]
    )
    event = _event(camera, building)
    db_session.add(event)
    await db_session.commit()
    await notify_event(event)
    await dispatcher.wait_for_pending()
    assert sorted(c.body["chat_id"] for c in apis.of("sendMessage")) == ["111", "222"]


async def test_notify_event_with_snapshot_sends_photo(apis, db_session, monkeypatch):
    requested: list[str] = []

    async def fake_snapshot(key: str) -> bytes:
        requested.append(key)
        return b"\xff\xd8JPEGDATA"

    monkeypatch.setattr(dispatcher, "_load_snapshot", fake_snapshot)
    building, camera = await _camera(db_session)
    db_session.add(NotificationRule(name="Rasm", channel="telegram", recipients=["111"], kinds=["event"]))
    event = _event(camera, building, snapshot_key="events/x.jpg")
    db_session.add(event)
    await db_session.commit()

    await notify_event(event)
    await dispatcher.wait_for_pending()
    assert requested == ["events/x.jpg"]
    photos = apis.of("sendPhoto")
    assert len(photos) == 1
    assert b"JPEGDATA" in photos[0].raw and b"111" in photos[0].raw
    assert apis.of("sendMessage") == []


async def test_unconfigured_channel_is_logged_as_skipped(apis, db_session, monkeypatch):
    monkeypatch.setattr(settings, "sms_provider", "none")
    building, camera = await _camera(db_session)
    db_session.add(NotificationRule(name="SMS", channel="sms", recipients=["+998901112233"], kinds=["event"]))
    event = _event(camera, building)
    db_session.add(event)
    await db_session.commit()

    await notify_event(event)
    await dispatcher.wait_for_pending()
    logs = await _logs(db_session)
    assert [(log.status, log.error) for log in logs] == [("otkazildi", "SMS xizmati sozlanmagan")]
    assert apis.calls == []


async def test_failed_send_logged_as_error(apis, db_session):
    building, camera = await _camera(db_session)
    db_session.add(NotificationRule(name="T", channel="telegram", recipients=["111"], kinds=["event"]))
    event = _event(camera, building)
    db_session.add(event)
    await db_session.commit()
    apis.queue("sendMessage", 400, {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"})

    await notify_event(event)
    await dispatcher.wait_for_pending()
    logs = await _logs(db_session)
    assert logs[0].status == "xato"
    assert "chat not found" in logs[0].error


async def test_nothing_configured_does_not_spawn(db_session, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "sms_provider", "none")
    building, camera = await _camera(db_session)
    event = _event(camera, building)
    db_session.add(event)
    await db_session.commit()
    await notify_event(event)
    await notify_camera_status(camera, online=False)
    await notify_user(uuid.uuid4(), "x")
    assert not dispatcher._pending


async def test_notify_camera_status(apis, db_session):
    building, camera = await _camera(db_session)
    db_session.add(
        NotificationRule(name="Kameralar", channel="telegram", recipients=["111"], kinds=["camera_offline", "camera_online"])
    )
    await db_session.commit()

    since = datetime.now(timezone.utc) - timedelta(minutes=12)
    await notify_camera_status(camera, online=False, offline_since=since)
    await dispatcher.wait_for_pending()
    await notify_camera_status(camera, online=True)
    await dispatcher.wait_for_pending()

    texts = [c.body["text"] for c in apis.of("sendMessage")]
    assert texts[0].startswith("<b>Kamera o&#x27;chdi: Kirish-1</b>")
    assert f"Bino: {building.name}" in texts[0]
    assert "Davomiyligi: 12 daqiqa" in texts[0]
    assert texts[1].startswith("<b>Kamera tiklandi: Kirish-1</b>")
    kinds = [log.kind for log in await _logs(db_session)]
    assert sorted(kinds) == ["camera_offline", "camera_online"]


async def test_notify_access_denied(apis, db_session):
    db_session.add(NotificationRule(name="Turniket", channel="telegram", recipients=["111"], kinds=["access_denied"]))
    await db_session.commit()
    moment = datetime.now(timezone.utc)
    await notify_access_denied("Asosiy turniket", None, "00A1B2", moment)
    await dispatcher.wait_for_pending()
    await notify_access_denied("Asosiy turniket", None, "00A1B2", moment)  # takror — 60 s ichida
    await dispatcher.wait_for_pending()
    sent = apis.of("sendMessage")
    assert len(sent) == 1
    assert "Turniket rad etdi: Asosiy turniket" in sent[0].body["text"]
    assert "Shaxs: Noma&#x27;lum shaxs" in sent[0].body["text"]
    assert "Karta: 00A1B2" in sent[0].body["text"]


# --- Foydalanuvchilar ------------------------------------------------------


async def _user(db, **kw) -> User:
    user = User(login=f"u{uuid.uuid4().hex[:8]}", password_hash="x", full_name="Operator Bir", role="admin", **kw)
    db.add(user)
    await db.commit()
    return user


async def test_notify_user_prefers_telegram_then_sms(apis, db_session):
    linked = await _user(db_session, telegram_chat_id="555", phone="+998901112233")
    phone_only = await _user(db_session, phone="+998904445566")
    nothing = await _user(db_session)

    for user in (linked, phone_only, nothing):
        await notify_user(user.id, "Sizga hodisa <tayinlandi>", kind="system", ref_id="r1")
    await dispatcher.wait_for_pending()

    tg = apis.of("sendMessage")
    assert [c.body["chat_id"] for c in tg] == ["555"]
    assert tg[0].body["text"] == "Sizga hodisa &lt;tayinlandi&gt;"
    assert [c.body["mobile_phone"] for c in apis.of("message/sms/send")] == ["998904445566"]
    statuses = sorted(log.status for log in await _logs(db_session))
    assert statuses == ["otkazildi", "yuborildi", "yuborildi"]


async def test_notify_user_blocked_bot_unlinks_and_falls_back_to_sms(apis, db_session):
    user = await _user(db_session, telegram_chat_id="555", phone="+998901112233")
    apis.queue("sendMessage", 403, {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"})
    await notify_user(str(user.id), "Salom")
    await dispatcher.wait_for_pending()

    assert len(apis.of("message/sms/send")) == 1
    refreshed = await db_session.get(User, user.id, populate_existing=True)
    assert refreshed.telegram_chat_id is None
    assert sorted(log.status for log in await _logs(db_session)) == ["xato", "yuborildi"]


async def test_notify_event_overdue_reaches_assignee_and_rules_once(apis, db_session):
    building, camera = await _camera(db_session)
    assignee = await _user(db_session, telegram_chat_id="555")
    db_session.add(NotificationRule(name="SLA", channel="telegram", recipients=["555", "777"], kinds=["event_overdue"]))
    event = _event(
        camera,
        building,
        assigned_to_id=assignee.id,
        due_at=datetime(2026, 9, 19, 4, 15, tzinfo=timezone.utc),
    )
    db_session.add(event)
    await db_session.commit()

    await notify_event_overdue(event)
    await dispatcher.wait_for_pending()
    sent = apis.of("sendMessage")
    assert sorted(c.body["chat_id"] for c in sent) == ["555", "777"]
    assert "Hodisa muddati o&#x27;tdi" in sent[0].body["text"]
    assert "Mas&#x27;ul: Operator Bir" in sent[0].body["text"]
    assert "Muddat: 19.09.2026 09:15:00" in sent[0].body["text"]


# --- Ota-onalar -----------------------------------------------------------


async def _student(db, **kw) -> StudentStaff:
    base = dict(full_name="Aliyev Vali", type="talaba", group_or_position="2-kurs, DI-1625", parent_notify_enabled=True)
    base.update(kw)
    person = StudentStaff(**base)
    db.add(person)
    await db.commit()
    return person


def _record(person: StudentStaff, **kw) -> AttendanceRecord:
    base = dict(student_staff_id=person.id, date=local_now().date(), status="keldi", check_in=time(8, 12), source="kamera")
    base.update(kw)
    return AttendanceRecord(**base)


async def test_notify_attendance_to_parent_telegram(apis, db_session, monkeypatch):
    monkeypatch.setattr(settings, "parent_notify_arrival_enabled", True)
    monkeypatch.setattr(settings, "org_name", "Farg'ona JSSTI")
    person = await _student(db_session, parent_telegram_chat_id="321", parent_phone="+998901112233")
    record = _record(person)

    await notify_attendance(record, person, None)
    await notify_attendance(record, person, None)  # ikkinchi manba (turniket) — takrorlanmaydi
    await dispatcher.wait_for_pending()

    sent = apis.of("sendMessage")
    assert len(sent) == 1
    assert sent[0].body["chat_id"] == "321"
    assert sent[0].body["text"] == "Farg&#x27;ona JSSTI: Farzandingiz Aliyev Vali 08:12 da institutga keldi."
    assert apis.of("message/sms/send") == []
    logs = await _logs(db_session)
    assert [(log.kind, log.status, log.ref_id) for log in logs] == [("parent_arrival", "yuborildi", str(person.id))]


async def test_notify_attendance_respects_flags(apis, db_session, monkeypatch):
    person = await _student(db_session, parent_phone="+998901112233")
    staff = await _student(db_session, full_name="Xodim Bir", type="xodim", parent_phone="+998901112234")
    disabled = await _student(db_session, full_name="Olimov Soli", parent_notify_enabled=False, parent_phone="+998901112235")

    # Umumiy sozlama o'chiq — hech narsa
    monkeypatch.setattr(settings, "parent_notify_arrival_enabled", False)
    await notify_attendance(_record(person), person, None)
    monkeypatch.setattr(settings, "parent_notify_arrival_enabled", True)
    await notify_attendance(_record(staff), staff, None)
    await notify_attendance(_record(disabled), disabled, None)
    await notify_attendance(_record(person, status="kelmadi"), person, None)
    await notify_attendance(_record(person, date=date(2020, 1, 1)), person, None)
    await dispatcher.wait_for_pending()
    assert apis.calls == []

    # Hammasi joyida — SMS (Telegram bog'lanmagan)
    await notify_attendance(_record(person), None, None)
    await dispatcher.wait_for_pending()
    sent = apis.of("message/sms/send")
    assert len(sent) == 1
    assert sent[0].body["mobile_phone"] == "998901112233"
    assert "Farzandingiz Aliyev Vali 08:12 da institutga keldi" in sent[0].body["message"]


async def test_parent_blocked_bot_falls_back_to_sms(apis, db_session, monkeypatch):
    monkeypatch.setattr(settings, "parent_notify_arrival_enabled", True)
    person = await _student(db_session, parent_telegram_chat_id="321", parent_phone="+998901112233")
    apis.queue("sendMessage", 403, {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"})

    await notify_attendance(_record(person), person, None)
    await dispatcher.wait_for_pending()

    assert len(apis.of("message/sms/send")) == 1
    assert (await db_session.get(StudentStaff, person.id, populate_existing=True)).parent_telegram_chat_id is None


async def test_notify_absences_batch(apis, db_session, monkeypatch):
    monkeypatch.setattr(settings, "parent_notify_absence_enabled", True)
    tg = await _student(db_session, full_name="Birinchi Talaba", parent_telegram_chat_id="1001")
    phone = await _student(db_session, full_name="Ikkinchi Talaba", parent_phone="+998901112233")
    off = await _student(db_session, full_name="Uchinchi Talaba", parent_notify_enabled=False, parent_phone="+998901112234")
    unreachable = await _student(db_session, full_name="To'rtinchi Talaba")
    inactive = await _student(db_session, full_name="Beshinchi Talaba", active=False, parent_phone="+998901112236")
    day = date(2026, 9, 18)

    await notify_absences([tg.id, phone.id, off.id, unreachable.id, inactive.id], day)
    await dispatcher.wait_for_pending()

    tg_sent = apis.of("sendMessage")
    assert [c.body["chat_id"] for c in tg_sent] == ["1001"]
    assert "Farzandingiz Birinchi Talaba 18.09.2026 kuni institutga kelmadi." in tg_sent[0].body["text"]
    sms_sent = apis.of("message/sms/send")
    assert [c.body["mobile_phone"] for c in sms_sent] == ["998901112233"]
    logs = await _logs(db_session)
    assert sorted(log.ref_id for log in logs) == sorted([str(tg.id), str(phone.id)])
    assert {log.kind for log in logs} == {"parent_absence"}


async def test_notify_absences_disabled(apis, db_session, monkeypatch):
    monkeypatch.setattr(settings, "parent_notify_absence_enabled", False)
    person = await _student(db_session, parent_phone="+998901112233")
    await notify_absences([person.id], date(2026, 9, 18))
    await dispatcher.wait_for_pending()
    assert apis.calls == []
