"""Bildirishnomalar API: qoidalar CRUD, jurnal, sinov xabari, holat,
Telegram bog'lash havolalari, ruxsatlar; talaba/xodim va foydalanuvchi
yozuvlaridagi yangi maydonlar (ota-ona telefoni, karta, telefon).

Barcha shaxsiy ma'lumotlar SOXTA."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.models import AuditLog, Building, Faculty, NotificationLog, NotificationRule, StudentStaff, User
from app.security import hash_password
from tests.conftest import auth_headers
from tests.notify_fakes import apis  # noqa: F401 — fixture

pytestmark = pytest.mark.asyncio

STEWARD = ("steward_notify", "steward-pass-123")


@pytest.fixture
async def steward(db_session, seeded) -> User:
    user = User(login=STEWARD[0], password_hash=hash_password(STEWARD[1]), full_name="Kamera Mas'uli", role="kamera-masuli")
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.fixture
async def admin_headers(client, seeded) -> dict:
    return await auth_headers(client, "admin", "admin123")


@pytest.fixture
async def student(db_session, seeded) -> StudentStaff:
    faculty = (await db_session.execute(select(Faculty).where(Faculty.name == "Davolash ishi"))).scalar_one()
    person = StudentStaff(
        full_name="Soxtaov Talaba Birinchi", type="talaba", faculty_id=faculty.id, group_or_position="2-kurs, DI-1625"
    )
    db_session.add(person)
    await db_session.commit()
    return person


# ---------------------------------------------------------------------------
# Ruxsatlar
# ---------------------------------------------------------------------------


async def test_endpoints_require_auth_and_permission(client: AsyncClient, steward, student):
    for method, path in [
        ("get", "/api/notifications/rules"),
        ("get", "/api/notifications/log"),
        ("get", "/api/notifications/status"),
        ("get", "/api/notifications/me"),
        ("post", "/api/notifications/me/telegram-link"),
    ]:
        resp = await client.request(method.upper(), path)
        assert resp.status_code == 401, path

    headers = await auth_headers(client, *STEWARD)
    assert (await client.get("/api/notifications/rules", headers=headers)).status_code == 403
    assert (await client.get("/api/notifications/log", headers=headers)).status_code == 403
    assert (await client.get("/api/notifications/status", headers=headers)).status_code == 403
    resp = await client.post("/api/notifications/test", headers=headers, json={"channel": "telegram", "recipient": "1"})
    assert resp.status_code == 403
    resp = await client.post(f"/api/students-staff/{student.id}/parent-telegram-link", headers=headers)
    assert resp.status_code == 403
    # O'z sozlamalari — har qanday kirgan foydalanuvchi uchun
    assert (await client.get("/api/notifications/me", headers=headers)).status_code == 200


# ---------------------------------------------------------------------------
# Qoidalar
# ---------------------------------------------------------------------------


async def test_rule_crud(client: AsyncClient, db_session, admin_headers):
    building = (await db_session.execute(select(Building).limit(1))).scalar_one()
    resp = await client.post(
        "/api/notifications/rules",
        headers=admin_headers,
        json={
            "name": "Navbatchi SMS",
            "channel": "sms",
            "recipients": ["90 111 22 33", "+998901112233", ""],
            "kinds": ["event", "event", "camera_offline"],
            "moduleCodes": [3, 5],
            "buildingIds": [str(building.id)],
            "minSeverity": "o'rta",
        },
    )
    assert resp.status_code == 201, resp.text
    rule = resp.json()
    assert rule["recipients"] == ["+998901112233"]  # bir xil raqam bir marta
    assert rule["kinds"] == ["event", "camera_offline"]
    assert rule["moduleCodes"] == [3, 5]
    assert rule["buildingIds"] == [str(building.id)]
    assert rule["minSeverity"] == "o'rta"
    assert rule["enabled"] is True

    listed = (await client.get("/api/notifications/rules", headers=admin_headers)).json()
    assert [r["id"] for r in listed] == [rule["id"]]

    resp = await client.patch(
        f"/api/notifications/rules/{rule['id']}",
        headers=admin_headers,
        json={"enabled": False, "moduleCodes": [], "minSeverity": None},
    )
    assert resp.status_code == 200, resp.text
    patched = resp.json()
    assert patched["enabled"] is False
    assert patched["moduleCodes"] is None and patched["minSeverity"] is None
    assert patched["recipients"] == ["+998901112233"]  # yuborilmagan — o'zgarmagan

    # Kanal almashsa eski qabul qiluvchilar yangi kanal qoidasi bilan tekshiriladi
    resp = await client.patch(f"/api/notifications/rules/{rule['id']}", headers=admin_headers, json={"channel": "telegram"})
    assert resp.status_code == 422
    resp = await client.patch(
        f"/api/notifications/rules/{rule['id']}",
        headers=admin_headers,
        json={"channel": "telegram", "recipients": ["123456", "-1001234567890", "@navbatchi_kanal"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["recipients"] == ["123456", "-1001234567890", "@navbatchi_kanal"]

    assert (await client.delete(f"/api/notifications/rules/{rule['id']}", headers=admin_headers)).status_code == 204
    assert (await client.get("/api/notifications/rules", headers=admin_headers)).json() == []
    assert (await client.delete(f"/api/notifications/rules/{rule['id']}", headers=admin_headers)).status_code == 404

    actions = [a.action for a in (await db_session.execute(select(AuditLog))).scalars().all()]
    assert any("qoidasi qo'shdi: Navbatchi SMS" in a for a in actions)
    assert any("qoidasini o'chirdi" in a for a in actions)


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "channel": "sms", "recipients": ["+998901112233"], "kinds": ["event"]},  # nom qisqa
        {"name": "Qoida", "channel": "sms", "recipients": ["12345"], "kinds": ["event"]},  # telefon
        {"name": "Qoida", "channel": "telegram", "recipients": ["abc def"], "kinds": ["event"]},  # chat id
        {"name": "Qoida", "channel": "telegram", "recipients": [], "kinds": ["event"]},
        {"name": "Qoida", "channel": "telegram", "recipients": ["1"], "kinds": []},
        {"name": "Qoida", "channel": "telegram", "recipients": ["1"], "kinds": ["nomalum"]},
        {"name": "Qoida", "channel": "pochta", "recipients": ["1"], "kinds": ["event"]},
        {"name": "Qoida", "channel": "telegram", "recipients": ["1"], "kinds": ["event"], "minSeverity": "juda"},
    ],
)
async def test_rule_validation(client: AsyncClient, admin_headers, body):
    resp = await client.post("/api/notifications/rules", headers=admin_headers, json=body)
    assert resp.status_code == 422, resp.text


async def test_rule_unknown_building(client: AsyncClient, admin_headers):
    resp = await client.post(
        "/api/notifications/rules",
        headers=admin_headers,
        json={"name": "Qoida", "channel": "telegram", "recipients": ["1"], "kinds": ["event"],
              "buildingIds": ["00000000-0000-0000-0000-000000000000"]},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Jurnal
# ---------------------------------------------------------------------------


async def test_log_pagination_and_filters(client: AsyncClient, db_session, admin_headers):
    now = datetime.now(timezone.utc)
    rows = [
        NotificationLog(channel="telegram", recipient="111", kind="event", status="yuborildi", text="Yong'in", ref_id="e1",
                        created_at=now - timedelta(minutes=i))
        for i in range(25)
    ]
    rows.append(NotificationLog(channel="sms", recipient="+998901112233", kind="camera_offline", status="xato",
                                text="Kamera o'chdi", error="Eskiz xatosi", created_at=now + timedelta(minutes=1)))
    db_session.add_all(rows)
    await db_session.commit()

    page = (await client.get("/api/notifications/log?pageSize=10", headers=admin_headers)).json()
    assert page["total"] == 26 and page["totalPages"] == 3 and len(page["items"]) == 10
    assert page["items"][0]["status"] == "xato"  # eng yangisi birinchi
    assert page["items"][0]["error"] == "Eskiz xatosi"

    only_errors = (await client.get("/api/notifications/log?status=xato", headers=admin_headers)).json()
    assert only_errors["total"] == 1
    by_channel = (await client.get("/api/notifications/log?channel=telegram&pageSize=5&page=5", headers=admin_headers)).json()
    assert by_channel["total"] == 25 and len(by_channel["items"]) == 5
    searched = (await client.get("/api/notifications/log?search=o'chdi", headers=admin_headers)).json()
    assert searched["total"] == 1
    by_ref = (await client.get("/api/notifications/log?refId=e1&kind=event", headers=admin_headers)).json()
    assert by_ref["total"] == 25
    future = (now + timedelta(days=2)).date().isoformat()
    assert (await client.get(f"/api/notifications/log?from={future}", headers=admin_headers)).json()["total"] == 0
    assert (await client.get("/api/notifications/log?status=boshqa", headers=admin_headers)).status_code == 422


# ---------------------------------------------------------------------------
# Holat va sinov xabari
# ---------------------------------------------------------------------------


async def test_status_unconfigured(client: AsyncClient, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "sms_provider", "none")
    monkeypatch.setattr(settings, "parent_notify_absence_enabled", True)
    body = (await client.get("/api/notifications/status", headers=admin_headers)).json()
    assert body["telegramConfigured"] is False and body["telegramBotUsername"] is None
    assert body["smsConfigured"] is False and body["smsProvider"] == "none"
    assert body["parentAbsenceEnabled"] is True
    assert body["orgName"] == settings.org_name
    assert "token" not in str(body).lower().replace("telegram", "")


async def test_status_configured_never_returns_secrets(client: AsyncClient, admin_headers, apis):
    body = (await client.get("/api/notifications/status", headers=admin_headers)).json()
    assert body["telegramConfigured"] is True
    assert body["telegramBotUsername"] == "situatsion_bot"
    assert body["smsConfigured"] is True and body["smsSender"] == settings.eskiz_sender
    text = str(body)
    assert settings.telegram_bot_token not in text and settings.eskiz_password not in text


async def test_send_test_message(client: AsyncClient, db_session, admin_headers, apis):
    resp = await client.post(
        "/api/notifications/test", headers=admin_headers, json={"channel": "sms", "recipient": "90 111 22 33"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "error": None}
    assert apis.of("message/sms/send")[0].body["mobile_phone"] == "998901112233"

    apis.queue("sendMessage", 403, {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"})
    resp = await client.post(
        "/api/notifications/test", headers=admin_headers, json={"channel": "telegram", "recipient": "42", "text": "Salom"}
    )
    assert resp.json()["ok"] is False
    assert "bloklangan" in resp.json()["error"]

    logs = (await db_session.execute(select(NotificationLog).order_by(NotificationLog.created_at))).scalars().all()
    assert [(log.channel, log.status, log.kind) for log in logs] == [("sms", "yuborildi", "system"), ("telegram", "xato", "system")]

    bad = await client.post("/api/notifications/test", headers=admin_headers, json={"channel": "sms", "recipient": "123"})
    assert bad.status_code == 422


async def test_send_test_message_unconfigured(client: AsyncClient, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    resp = await client.post("/api/notifications/test", headers=admin_headers, json={"channel": "telegram", "recipient": "42"})
    assert resp.json() == {"ok": False, "error": "Telegram bot sozlanmagan"}


# ---------------------------------------------------------------------------
# Telegram bog'lash
# ---------------------------------------------------------------------------


async def test_my_telegram_link_flow(client: AsyncClient, db_session, admin_headers, apis):
    me = (await client.get("/api/notifications/me", headers=admin_headers)).json()
    assert me == {"telegramLinked": False, "telegramBotConfigured": True, "phone": None}

    resp = await client.post("/api/notifications/me/telegram-link", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    link = resp.json()
    assert link["botUsername"] == "situatsion_bot"
    assert link["deepLink"] == f"https://t.me/situatsion_bot?start={link['code']}"
    assert len(link["code"]) >= 20

    user = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
    assert user.telegram_link_code == link["code"]

    # Bot kodni qabul qildi deb faraz qilamiz
    user.telegram_chat_id = "5001"
    await db_session.commit()
    assert (await client.get("/api/notifications/me", headers=admin_headers)).json()["telegramLinked"] is True

    assert (await client.delete("/api/notifications/me/telegram", headers=admin_headers)).status_code == 204
    await db_session.refresh(user)
    assert user.telegram_chat_id is None and user.telegram_link_code is None


async def test_telegram_link_needs_bot(client: AsyncClient, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    resp = await client.post("/api/notifications/me/telegram-link", headers=admin_headers)
    assert resp.status_code == 409
    assert "sozlanmagan" in resp.json()["detail"]


async def test_parent_telegram_link(client: AsyncClient, db_session, admin_headers, student, apis, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_username", "@markaz_bot")
    resp = await client.post(f"/api/students-staff/{student.id}/parent-telegram-link", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    link = resp.json()
    assert link["deepLink"].startswith("https://t.me/markaz_bot?start=")
    await db_session.refresh(student)
    assert student.telegram_link_code == link["code"]
    assert apis.of("getMe") == []  # nom sozlamada bor — getMe shart emas

    student.parent_telegram_chat_id = "7007"
    await db_session.commit()
    detail = (await client.get(f"/api/students-staff/{student.id}/details", headers=admin_headers)).json()
    assert detail["parentTelegramLinked"] is True

    resp = await client.delete(f"/api/students-staff/{student.id}/parent-telegram", headers=admin_headers)
    assert resp.status_code == 204
    detail = (await client.get(f"/api/students-staff/{student.id}/details", headers=admin_headers)).json()
    assert detail["parentTelegramLinked"] is False

    assert (await client.post("/api/students-staff/nope/parent-telegram-link", headers=admin_headers)).status_code == 404


async def test_parent_link_only_for_students(client: AsyncClient, db_session, admin_headers, student, apis):
    student.type = "xodim"
    await db_session.commit()
    resp = await client.post(f"/api/students-staff/{student.id}/parent-telegram-link", headers=admin_headers)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Talaba/xodim: ota-ona va karta maydonlari
# ---------------------------------------------------------------------------


def _edit_body(person: StudentStaff, **extra) -> dict:
    body = {"fullName": person.full_name, "type": person.type, "faculty": "Davolash ishi", "course": 2, "group": "DI-1625"}
    body.update(extra)
    return body


async def test_student_parent_fields_roundtrip(client: AsyncClient, db_session, admin_headers, student):
    resp = await client.patch(
        f"/api/students-staff/{student.id}",
        headers=admin_headers,
        json=_edit_body(student, parentPhone="90 123 45 67", parentNotifyEnabled=True, cardNumber=" 00A1 B2C3 "),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["parentPhone"] == "+998901234567"
    assert body["parentNotifyEnabled"] is True
    assert body["cardNumber"] == "00A1B2C3"
    assert body["parentTelegramLinked"] is False

    # Yuborilmagan maydonlar o'zgarmaydi
    resp = await client.patch(f"/api/students-staff/{student.id}", headers=admin_headers, json=_edit_body(student))
    assert resp.json()["parentPhone"] == "+998901234567" and resp.json()["cardNumber"] == "00A1B2C3"

    # Bo'sh satr — o'chiriladi
    resp = await client.patch(
        f"/api/students-staff/{student.id}", headers=admin_headers, json=_edit_body(student, parentPhone="", cardNumber="")
    )
    assert resp.json()["parentPhone"] is None and resp.json()["cardNumber"] is None

    bad = await client.patch(
        f"/api/students-staff/{student.id}", headers=admin_headers, json=_edit_body(student, parentPhone="12345")
    )
    assert bad.status_code == 422
    assert "Ota-ona telefon" in bad.json()["detail"]

    # Audit jurnalida raqamning o'zi emas, faqat nima o'zgargani
    actions = [a.action for a in (await db_session.execute(select(AuditLog))).scalars().all()]
    assert any("ota-ona telefoni" in a and "karta" in a for a in actions)
    assert not any("901234567" in a for a in actions)


async def test_card_number_unique(client: AsyncClient, db_session, admin_headers, student):
    other = StudentStaff(full_name="Boshqaov Xodim Ikkinchi", type="xodim", group_or_position="Kafedra", card_number="CARD-1")
    db_session.add(other)
    await db_session.commit()

    resp = await client.patch(
        f"/api/students-staff/{student.id}", headers=admin_headers, json=_edit_body(student, cardNumber="CARD-1")
    )
    assert resp.status_code == 409
    assert "Bu karta raqami boshqa yozuvga biriktirilgan: Boshqaov Xodim Ikkinchi" in resp.json()["detail"]

    resp = await client.post(
        "/api/students-staff",
        headers=admin_headers,
        json={"fullName": "Yangiov Talaba Uchinchi", "type": "talaba", "faculty": "Davolash ishi",
              "groupOrPosition": "1-kurs", "cardNumber": "CARD-1"},
    )
    assert resp.status_code == 409


async def test_create_student_with_parent_fields(client: AsyncClient, db_session, admin_headers, seeded):
    resp = await client.post(
        "/api/students-staff",
        headers=admin_headers,
        json={"fullName": "Yangiov Talaba Uchinchi", "type": "talaba", "faculty": "Davolash ishi",
              "groupOrPosition": "1-kurs, DI-1", "parentPhone": "+998 90 000 11 22", "parentNotifyEnabled": True,
              "cardNumber": "77"},
    )
    assert resp.status_code == 201, resp.text
    detail = (await client.get(f"/api/students-staff/{resp.json()['id']}/details", headers=admin_headers)).json()
    assert detail["parentPhone"] == "+998900001122"
    assert detail["parentNotifyEnabled"] is True
    assert detail["cardNumber"] == "77"

    # Xodimga ota-ona xabarnomasi yoqilmaydi
    resp = await client.post(
        "/api/students-staff",
        headers=admin_headers,
        json={"fullName": "Yangiov Xodim Tortinchi", "type": "xodim", "faculty": "Davolash ishi",
              "groupOrPosition": "Kafedra mudiri", "parentNotifyEnabled": True},
    )
    assert resp.status_code == 201
    detail = (await client.get(f"/api/students-staff/{resp.json()['id']}/details", headers=admin_headers)).json()
    assert detail["parentNotifyEnabled"] is False


# ---------------------------------------------------------------------------
# Foydalanuvchilar: telefon
# ---------------------------------------------------------------------------


async def test_user_phone(client: AsyncClient, db_session, admin_headers):
    resp = await client.post(
        "/api/users",
        headers=admin_headers,
        json={"name": "Telefonli Operator", "login": "tel_operator", "password": "parol-12345", "role": "Admin",
              "phone": "90 555 44 33"},
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["phone"] == "+998905554433"
    assert created["telegramLinked"] is False

    base = {"name": "Telefonli Operator", "login": "tel_operator", "role": "Admin"}
    # Telefon yuborilmasa — o'zgarmaydi
    resp = await client.patch(f"/api/users/{created['id']}", headers=admin_headers, json=base)
    assert resp.json()["phone"] == "+998905554433"
    resp = await client.patch(f"/api/users/{created['id']}", headers=admin_headers, json={**base, "phone": ""})
    assert resp.json()["phone"] is None
    bad = await client.patch(f"/api/users/{created['id']}", headers=admin_headers, json={**base, "phone": "555"})
    assert bad.status_code == 422

    listed = (await client.get("/api/users", headers=admin_headers)).json()["items"]
    assert all("phone" in u for u in listed)


async def test_resend_failed_message(client: AsyncClient, db_session, admin_headers, apis):
    failed = NotificationLog(channel="telegram", recipient="555", kind="event", status="xato",
                             text="Yong'in <signal>", error="Bad Request: chat not reachable")
    sent = NotificationLog(channel="telegram", recipient="555", kind="event", status="yuborildi", text="ok")
    db_session.add_all([failed, sent])
    await db_session.commit()

    resp = await client.post(f"/api/notifications/log/{failed.id}/qayta", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    # Matn HTML sifatida xavfsiz ketadi va jurnalga yangi qator qo'shiladi.
    assert apis.of("sendMessage")[-1].body["text"] == "Yong&#x27;in &lt;signal&gt;"
    retry = await db_session.get(NotificationLog, resp.json()["id"])
    assert retry.status == "yuborildi" and retry.kind == "event"

    assert (await client.post(f"/api/notifications/log/{sent.id}/qayta", headers=admin_headers)).status_code == 409
    # Bir marta: ikkinchi bosish yana xabar (pullik SMS) yubormaydi.
    again = await client.post(f"/api/notifications/log/{failed.id}/qayta", headers=admin_headers)
    assert again.status_code == 409


async def test_timeout_is_not_resent(client: AsyncClient, db_session, admin_headers, apis):
    """Javob kelmagan xabar yetib borgan bo'lishi mumkin — qayta yuborilmaydi."""
    row = NotificationLog(channel="sms", recipient="998900000001", kind="event", status="xato",
                          text="x", error="Eskiz javob bermadi (timeout)")
    db_session.add(row)
    await db_session.commit()
    resp = await client.post(f"/api/notifications/log/{row.id}/qayta", headers=admin_headers)
    assert resp.status_code == 409


async def test_parent_coverage(client: AsyncClient, db_session, admin_headers, student):
    student.parent_telegram_chat_id = "777"
    student.parent_notify_enabled = True
    db_session.add(StudentStaff(full_name="Soxta Ikkinchi", type="talaba", group_or_position="1-kurs, X", parent_phone="998900000000"))
    db_session.add(NotificationLog(channel="telegram", recipient="777", kind="parent_arrival", status="yuborildi", text="keldi"))
    db_session.add(NotificationLog(channel="sms", recipient="99890", kind="parent_absence", status="xato", text="kelmadi"))
    await db_session.commit()
    body = (await client.get("/api/notifications/ota-ona", headers=admin_headers)).json()
    assert body["telegramLinked"] == 1 and body["phoneOnly"] == 1 and body["enabled"] == 1
    assert body["students"] >= 2
    assert (body["weekSent"], body["weekFailed"]) == (1, 1)
