"""Rahbariyat KPI (GET /api/kpi) va avtomatik hisobotlar (/api/hisobot-jadval,
app/jobs/report_schedules.py). Telegram — soxta server (tests/notify_fakes.py),
haqiqiy xabar yuborilmaydi.

KPI ma'lumotlari (davr: d1..d2 — 10 va 9 kun oldin; oldingi davr: 12..11 kun oldin):
  Xodimlar: A (tasdiq.), B (tasdiq.), C (tasdiqlanmagan)
    d1: A keldi (kamera), B kech_keldi (kamera); d2: A keldi (kamera), B kelmadi
    -> kelgan 3, kech 1, kelmagan 1: davomat 75.0, kechikish 33.3
    oldingi: A, B keldi -> 100.0
  Talabalar: S1 (tasdiq.), S2 (tasdiqlanmagan)
    d1: S1 keldi (kamera); d2: S1 keldi (qo'lda) -> 100.0; oldingi — yo'q
  Tanilganlar (tasdiqlangan 3): d1 — 3, d2 — 1 (qo'lda kiritilgan sanalmaydi) -> 66.7
  Hodisalar: #5 — rad (10 daq), hal qilingan (20 daq, 60 daq), yangi; #7 — yangi;
    sinov rejimi va davrdan tashqari hodisa hisobga kirmaydi
  Kameralar: faol 2 (1 tasi ishlayapti), nofaol 1
"""

from datetime import date, datetime, time, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import (
    AttendanceRecord,
    Camera,
    Event,
    NotificationLog,
    ReportSchedule,
    StudentStaff,
    UnknownSighting,
    User,
)
from app.security import hash_password
from app.services import kpi, report_schedule as rs, situation
from app.timezone import INSTITUTE_TZ
from tests.conftest import TestSessionLocal, auth_headers
from tests.notify_fakes import apis  # noqa: F401 — fixture

STEWARD = ("steward_kpi", "steward-pass-123")


@pytest.fixture(autouse=True)
def _fresh_cache():
    situation.clear_cache()
    yield
    situation.clear_cache()


@pytest.fixture
async def admin_headers(client, seeded) -> dict:
    return await auth_headers(client, "admin", "admin123")


@pytest.fixture
async def steward_headers(client, db_session, seeded) -> dict:
    db_session.add(User(login=STEWARD[0], password_hash=hash_password(STEWARD[1]), full_name="Kamera Mas'uli",
                        role="kamera-masuli"))
    await db_session.commit()
    return await auth_headers(client, *STEWARD)


def _p(name, type_, enrolled=True):
    return StudentStaff(full_name=name, type=type_, group_or_position="Anatomiya kafedrasi" if type_ == "xodim"
                        else "2-kurs, DI-2301", biometrics_status="tasdiqlangan" if enrolled else "yoq", active=True)


def _rec(person, day, status, source="kamera", check_in="08:00"):
    return AttendanceRecord(student_staff_id=person.id, date=day, status=status, source=source,
                            check_in=time.fromisoformat(check_in) if status != "kelmadi" else None)


def _event(day, code, status, *, review=None, resolve=None, trial=False):
    at = datetime.combine(day, time(10, 0), tzinfo=INSTITUTE_TZ)
    return Event(
        occurred_at=at, camera_name="205-xona", building="Asosiy bino", module_code=code, module_name=f"Modul {code}",
        group="xavfsizlik", confidence=80, severity="o'rta", status=status, is_trial=trial,
        reviewed_at=at + timedelta(minutes=review) if review is not None else None,
        resolved_at=at + timedelta(minutes=resolve) if resolve is not None else None,
    )


@pytest.fixture
async def kpi_world(db_session, seeded):
    db = db_session
    today = situation.today()
    d1, d2 = today - timedelta(days=10), today - timedelta(days=9)
    p1, p2 = today - timedelta(days=12), today - timedelta(days=11)
    a, b, c = _p("Aliyev A", "xodim"), _p("Botirov B", "xodim"), _p("Choriyev C", "xodim", enrolled=False)
    s1, s2 = _p("Sobirov S", "talaba"), _p("Salimova S", "talaba", enrolled=False)
    db.add_all([a, b, c, s1, s2])
    await db.flush()
    db.add_all([
        _rec(a, d1, "keldi"), _rec(b, d1, "kech_keldi", check_in="09:20"),
        _rec(a, d2, "keldi"), _rec(b, d2, "kelmadi"),
        _rec(a, p1, "keldi"), _rec(b, p2, "keldi"),
        _rec(s1, d1, "keldi"), _rec(s1, d2, "keldi", source="qolda"),
    ])
    db.add_all([
        _event(d1, 5, "rad_etilgan", review=10),
        _event(d1, 5, "hal_qilindi", review=20, resolve=60),
        _event(d2, 5, "yangi"),
        _event(d2, 7, "yangi"),
        _event(d2, 5, "rad_etilgan", review=5, trial=True),
        _event(today - timedelta(days=20), 5, "rad_etilgan", review=500),
    ])
    now = datetime.now(timezone.utc)
    db.add_all([
        Camera(name="C1", ip="10.0.0.1", zone="z", resolution="1080p", status="faol", last_seen_at=now),
        Camera(name="C2", ip="10.0.0.2", zone="z", resolution="1080p", status="faol", last_seen_at=None),
        Camera(name="C3", ip="10.0.0.3", zone="z", resolution="1080p", status="nofaol", last_seen_at=now),
    ])
    for st in ("kutilmoqda", "kutilmoqda", "talaba"):
        db.add(UnknownSighting(day=d1, first_seen_at=now, last_seen_at=now, embedding="[]", status=st))
    await db.commit()
    return d1, d2


# ─────────────────────────────────────────── KPI

async def test_kpi_blocks(client: AsyncClient, admin_headers, kpi_world):
    d1, d2 = kpi_world
    res = await client.get("/api/kpi", params={"dan": d1.isoformat(), "gacha": d2.isoformat()}, headers=admin_headers)
    assert res.status_code == 200, res.text
    data = res.json()
    staff, students = data["attendance"]["staff"], data["attendance"]["students"]
    assert (staff["rate"], staff["prevRate"], staff["latePct"]) == (75.0, 100.0, 33.3)
    assert (students["rate"], students["prevRate"]) == (100.0, None)
    assert data["attendance"]["previous"]["to"] == (d1 - timedelta(days=1)).isoformat()

    rec = data["recognition"]
    assert (rec["staffCoverage"], rec["studentsCoverage"]) == (66.7, 50.0)
    assert rec["recognisedDailyPct"] == 66.7
    assert rec["unknownPending"] == 2

    sec = data["security"]
    assert (sec["events"], sec["reviewed"], sec["rejected"], sec["open"]) == (4, 2, 1, 2)
    assert (sec["falsePct"], sec["reviewMinutes"], sec["resolveMinutes"]) == (50.0, 15.0, 60.0)
    assert [m["code"] for m in sec["modules"]] == [5, 7]
    assert sec["modules"][0]["events"] == 3 and sec["modules"][1]["falsePct"] is None

    inf = data["infrastructure"]
    assert (inf["camerasTotal"], inf["camerasActive"], inf["camerasOnline"], inf["onlinePct"]) == (3, 2, 1, 50.0)

    lines = kpi.summary_lines(data)
    assert lines[0].startswith("Davomat: xodimlar 75% (-25)")
    assert "1/2" in lines[-1]


async def test_kpi_requires_view_reports(client: AsyncClient, steward_headers):
    assert (await client.get("/api/kpi")).status_code == 401
    assert (await client.get("/api/kpi", headers=steward_headers)).status_code == 403
    assert (await client.get("/api/hisobot-jadval", headers=steward_headers)).status_code == 403


async def test_kpi_rejects_bad_range(client: AsyncClient, admin_headers):
    res = await client.get("/api/kpi", params={"dan": "2026-09-10", "gacha": "2026-09-01"}, headers=admin_headers)
    assert res.status_code == 422


# ─────────────────────────────────────────── davrlar (sof funksiyalar)

def _local(y, m, d, h, minute=0):
    return datetime(y, m, d, h, minute, tzinfo=INSTITUTE_TZ)


def test_weekly_boundary_and_period():
    # 2026-09-21 — dushanba.
    b = rs.last_boundary("haftalik", _local(2026, 9, 21, 9))
    assert b == _local(2026, 9, 21, 8)
    assert rs.period_for("haftalik", b) == (date(2026, 9, 14), date(2026, 9, 20))
    # Dushanba 07:00 — hali o'tgan haftaning chegarasi.
    b = rs.last_boundary("haftalik", _local(2026, 9, 21, 7))
    assert rs.period_for("haftalik", b) == (date(2026, 9, 7), date(2026, 9, 13))
    # Payshanba — shu haftaning dushanbasi.
    assert rs.last_boundary("haftalik", _local(2026, 9, 24, 15)) == _local(2026, 9, 21, 8)


def test_monthly_boundary_and_period():
    b = rs.last_boundary("oylik", _local(2026, 10, 1, 8, 30))
    assert rs.period_for("oylik", b) == (date(2026, 9, 1), date(2026, 9, 30))
    b = rs.last_boundary("oylik", _local(2026, 10, 1, 7))
    assert rs.period_for("oylik", b) == (date(2026, 8, 1), date(2026, 8, 31))
    b = rs.last_boundary("oylik", _local(2026, 1, 15, 12))
    assert rs.period_for("oylik", b) == (date(2025, 12, 1), date(2025, 12, 31))


def test_due_period_once_per_period():
    now = _local(2026, 9, 21, 9)
    s = ReportSchedule(kind="haftalik", report="kpi", enabled=True, telegram_chat_ids=["1"],
                       created_at=_local(2026, 9, 1, 12), last_sent_at=None)
    assert rs.due_period(s, now) == (date(2026, 9, 14), date(2026, 9, 20))
    s.last_sent_at = _local(2026, 9, 21, 8, 5)
    assert rs.due_period(s, now) is None
    s.last_sent_at = _local(2026, 9, 14, 8, 5)  # o'tgan hafta yuborilgan — bu hafta hali yo'q
    assert rs.due_period(s, now) is not None
    # Chegaradan keyin yaratilgan jadval eski davrni yubormaydi.
    fresh = ReportSchedule(kind="haftalik", report="kpi", enabled=True, telegram_chat_ids=["1"],
                           created_at=_local(2026, 9, 21, 8, 30), last_sent_at=None)
    assert rs.due_period(fresh, now) is None
    s.enabled = False
    assert rs.due_period(s, _local(2026, 9, 28, 9)) is None


# ─────────────────────────────────────────── CRUD va sinov

async def test_schedule_crud(client: AsyncClient, admin_headers, steward_headers):
    body = {"name": "Rektorga", "kind": "haftalik", "report": "kpi", "telegramChatIds": [" 12345 ", "12345", "-100777"]}
    res = await client.post("/api/hisobot-jadval", json=body, headers=admin_headers)
    assert res.status_code == 201, res.text
    created = res.json()
    assert created["telegramChatIds"] == ["12345", "-100777"] and created["enabled"] is True
    assert created["lastSentAt"] is None

    bad = await client.post("/api/hisobot-jadval", json={**body, "telegramChatIds": ["salom dunyo"]}, headers=admin_headers)
    assert bad.status_code == 422
    bad = await client.post("/api/hisobot-jadval", json={**body, "report": "boshqa"}, headers=admin_headers)
    assert bad.status_code == 422
    denied = await client.post("/api/hisobot-jadval", json=body, headers=steward_headers)
    assert denied.status_code == 403

    sid = created["id"]
    res = await client.patch(f"/api/hisobot-jadval/{sid}", json={"kind": "oylik", "enabled": False}, headers=admin_headers)
    assert res.status_code == 200 and res.json()["kind"] == "oylik" and res.json()["enabled"] is False
    res = await client.patch(f"/api/hisobot-jadval/{sid}", json={"name": None}, headers=admin_headers)
    assert res.status_code == 422

    listed = (await client.get("/api/hisobot-jadval", headers=admin_headers)).json()
    assert [r["id"] for r in listed] == [sid]
    assert (await client.delete(f"/api/hisobot-jadval/{sid}", headers=admin_headers)).status_code == 204
    assert (await client.get("/api/hisobot-jadval", headers=admin_headers)).json() == []
    assert (await client.delete(f"/api/hisobot-jadval/{sid}", headers=admin_headers)).status_code == 404


@pytest.mark.parametrize("report,prefix", [
    ("kpi", b"kpi-"), ("davomat_xodim", b"davomat-xodimlar-"), ("tabel_talaba", b"tabel-talabalar-"),
])
async def test_send_now_sends_document(client: AsyncClient, admin_headers, apis, db_session, report, prefix):
    body = {"name": "Sinov", "kind": "haftalik", "report": report, "telegramChatIds": ["111", "222"]}
    sid = (await client.post("/api/hisobot-jadval", json=body, headers=admin_headers)).json()["id"]
    res = await client.post(f"/api/hisobot-jadval/{sid}/sinov", headers=admin_headers)
    assert res.status_code == 200, res.text
    out = res.json()
    assert (out["sent"], out["failed"]) == (2, 0)
    calls = apis.of("sendDocument")
    assert len(calls) == 2
    assert prefix in calls[0].raw and b"Davomat:" in calls[0].raw
    logs = (await db_session.execute(select(NotificationLog).where(NotificationLog.kind == "report"))).scalars().all()
    assert {log.status for log in logs} == {"yuborildi"}
    # Sinov navbatdagi avtomatik yuborishni bekor qilmaydi.
    row = await db_session.get(ReportSchedule, __import__("uuid").UUID(sid))
    await db_session.refresh(row)
    assert row.last_sent_at is None


async def test_send_now_without_bot(client: AsyncClient, admin_headers, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "telegram_bot_token", "")
    body = {"name": "Sinov", "kind": "oylik", "report": "kpi", "telegramChatIds": ["111"]}
    sid = (await client.post("/api/hisobot-jadval", json=body, headers=admin_headers)).json()["id"]
    assert (await client.post(f"/api/hisobot-jadval/{sid}/sinov", headers=admin_headers)).status_code == 409


# ─────────────────────────────────────────── fondagi yuborish

async def _schedule(db, **kw) -> ReportSchedule:
    row = ReportSchedule(name="Haftalik KPI", kind="haftalik", report="kpi", telegram_chat_ids=["111"], enabled=True,
                         created_at=_local(2026, 9, 1, 12), **kw)
    db.add(row)
    await db.commit()
    return row


async def test_job_sends_once_per_period(db_session, seeded, apis):
    row = await _schedule(db_session)
    now = _local(2026, 9, 21, 9).astimezone(timezone.utc)
    assert await rs.run_due(TestSessionLocal, now=now) == 1
    assert len(apis.of("sendDocument")) == 1
    await db_session.refresh(row)
    assert row.last_sent_at == now
    # Xuddi shu hafta ichida qayta aylanish — yuborilmaydi.
    assert await rs.run_due(TestSessionLocal, now=now + timedelta(hours=5)) == 0
    assert len(apis.of("sendDocument")) == 1
    # Keyingi dushanba — yana.
    assert await rs.run_due(TestSessionLocal, now=now + timedelta(days=7)) == 1


async def test_job_retries_after_transient_error(db_session, seeded, apis):
    row = await _schedule(db_session)
    now = _local(2026, 9, 21, 9).astimezone(timezone.utc)
    apis.queue("sendDocument", 500, {"ok": False, "error_code": 500, "description": "Internal"})
    assert await rs.run_due(TestSessionLocal, now=now) == 0
    await db_session.refresh(row)
    assert row.last_sent_at is None
    assert await rs.run_due(TestSessionLocal, now=now + timedelta(minutes=5)) == 1


async def test_job_skips_disabled_and_unconfigured(db_session, seeded, apis, monkeypatch):
    from app.config import settings

    await _schedule(db_session)
    db_session.add(ReportSchedule(name="O'chiq", kind="haftalik", report="kpi", telegram_chat_ids=["222"],
                                  enabled=False, created_at=_local(2026, 9, 1, 12)))
    await db_session.commit()
    now = _local(2026, 9, 21, 9).astimezone(timezone.utc)
    token = settings.telegram_bot_token
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    assert await rs.run_due(TestSessionLocal, now=now) == 0
    assert apis.of("sendDocument") == []
    monkeypatch.setattr(settings, "telegram_bot_token", token)
    assert await rs.run_due(TestSessionLocal, now=now) == 1
    assert len(apis.of("sendDocument")) == 1  # o'chiq jadval yuborilmadi


def test_job_registered_in_scheduler():
    from app.jobs import ai_scheduler

    entry = next(e for e in ai_scheduler._build_registry() if e.name == "report_schedules")
    assert entry.tier == "standard" and entry.interval_seconds == 300
    assert "report_schedules" in ai_scheduler._STANDALONE_SWEEPS
