"""Hodisa ish jarayoni: tayinlash, holat o'tishlari, izohlar, tarix,
SLA muddati, eskalatsiya va summary hisoblari."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.jobs import event_escalation
from app.models import AuditLog, Building, Camera, Event, EventComment, User
from app.routers import events as events_router
from app.security import hash_password
from app.services.event_status import TRANSITIONS, can_transition, fold_review_counts
from tests.conftest import TestSessionLocal, auth_headers

STEWARD_LOGIN = "kamera-wf"
STEWARD_PASSWORD = "kamera-parol-123"


@pytest.fixture
async def camera(db_session, seeded) -> Camera:
    building = (await db_session.execute(select(Building))).scalars().first()
    row = Camera(name="Koridor-WF", ip="10.9.0.1", building_id=building.id, zone="Z", resolution="1080p")
    db_session.add(row)
    await db_session.commit()
    return row


@pytest.fixture
async def steward(db_session, seeded) -> User:
    """Hodisalarni ko'rib chiqish huquqi yo'q rol (kamera mas'uli)."""
    user = User(
        login=STEWARD_LOGIN,
        password_hash=hash_password(STEWARD_PASSWORD),
        full_name="Kamera Mas'uli",
        role="kamera-masuli",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def sent(monkeypatch) -> list[dict]:
    messages: list[dict] = []

    async def capture(message: dict) -> None:
        messages.append(message)

    monkeypatch.setattr(events_router.manager, "broadcast", capture)
    return messages


@pytest.fixture
def notified(monkeypatch) -> list[tuple]:
    calls: list[tuple] = []

    async def fake_notify_user(user_id, text, *, kind="system", ref_id=None):
        calls.append((str(user_id), text, kind, ref_id))

    monkeypatch.setattr(events_router, "notify_user", fake_notify_user)
    return calls


async def make_event(db_session, camera, **overrides) -> uuid.UUID:
    values = dict(
        occurred_at=datetime.now(timezone.utc),
        camera_id=camera.id,
        camera_name=camera.name,
        building="1-bino",
        module_code=20,
        module_name="Tartib-intizom buzilishi",
        group="D",
        confidence=60,
        severity="o'rta",
        status="yangi",
    )
    values.update(overrides)
    event = Event(**values)
    db_session.add(event)
    await db_session.commit()
    return event.id


async def user_id(db_session, login: str) -> uuid.UUID:
    return (await db_session.execute(select(User.id).where(User.login == login))).scalar_one()


async def reload(db_session, event_id: uuid.UUID) -> Event:
    db_session.expire_all()
    return (await db_session.execute(select(Event).where(Event.id == event_id))).scalar_one()


class TestTransitionRules:
    def test_false_alarm_cannot_be_resolved(self):
        assert not can_transition("rad_etilgan", "hal_qilindi")
        assert can_transition("tasdiqlangan", "hal_qilindi")
        assert can_transition("yangi", "hal_qilindi")

    def test_only_in_progress_returns_to_queue(self):
        assert [s for s, targets in TRANSITIONS.items() if "yangi" in targets] == ["jarayonda"]

    def test_fold_counts_resolved_as_confirmed_and_in_progress_as_unreviewed(self):
        folded = fold_review_counts({"yangi": 2, "jarayonda": 3, "tasdiqlangan": 4, "hal_qilindi": 1, "rad_etilgan": 5})
        assert folded == {"yangi": 5, "tasdiqlangan": 5, "rad_etilgan": 5}


@pytest.mark.usefixtures("seeded")
class TestAssign:
    async def test_assign_moves_new_to_in_progress_notifies_and_logs(
        self, client: AsyncClient, db_session, camera, sent, notified
    ):
        event_id = await make_event(db_session, camera)
        operator_id = await user_id(db_session, "operator")
        headers = await auth_headers(client, "admin", "admin123")

        resp = await client.post(f"/api/events/{event_id}/assign", headers=headers, json={"userId": str(operator_id)})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "jarayonda"
        assert body["assignedToId"] == str(operator_id)
        assert body["assignedToName"] == "Behzod Karimov"
        assert body["assignedAt"] and body["commentsCount"] == 1

        assert len(notified) == 1
        assert notified[0][0] == str(operator_id) and notified[0][2] == "system"
        assert notified[0][3] == str(event_id)
        assert sent and sent[-1]["kind"] == "event_updated" and sent[-1]["id"] == str(event_id)

        comments = (await db_session.execute(select(EventComment).where(EventComment.event_id == event_id))).scalars().all()
        assert [c.kind for c in comments] == ["tayinlash"]
        assert "Behzod Karimov" in comments[0].body
        audit = (await db_session.execute(select(AuditLog.action))).scalars().all()
        assert any("tayinladi" in a for a in audit)

    async def test_self_assignment_does_not_notify(self, client: AsyncClient, db_session, camera, sent, notified):
        event_id = await make_event(db_session, camera)
        admin_id = await user_id(db_session, "admin")
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(f"/api/events/{event_id}/assign", headers=headers, json={"userId": str(admin_id)})
        assert resp.status_code == 200
        assert notified == []

        other = await make_event(db_session, camera)
        resp = await client.post(f"/api/events/{other}/assign", headers=headers, json={"userId": "me"})
        assert resp.status_code == 200
        assert resp.json()["assignedToId"] == str(admin_id) and resp.json()["status"] == "jarayonda"
        assert notified == []

    async def test_unassign_keeps_status_and_records_history(self, client: AsyncClient, db_session, camera, sent, notified):
        operator_id = await user_id(db_session, "operator")
        event_id = await make_event(
            db_session, camera, status="jarayonda", assigned_to_id=operator_id, assigned_at=datetime.now(timezone.utc)
        )
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(f"/api/events/{event_id}/assign", headers=headers, json={"userId": None})
        assert resp.status_code == 200
        assert resp.json()["assignedToId"] is None and resp.json()["status"] == "jarayonda"
        row = await reload(db_session, event_id)
        assert row.assigned_to_id is None and row.assigned_at is None

    async def test_cannot_assign_to_user_without_review_permission(
        self, client: AsyncClient, db_session, camera, steward, sent, notified
    ):
        event_id = await make_event(db_session, camera)
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(f"/api/events/{event_id}/assign", headers=headers, json={"userId": str(steward.id)})
        assert resp.status_code == 422
        resp = await client.post(f"/api/events/{event_id}/assign", headers=headers, json={"userId": str(uuid.uuid4())})
        assert resp.status_code == 404
        resp = await client.post(f"/api/events/{event_id}/assign", headers=headers, json={"userId": "yaroqsiz"})
        assert resp.status_code == 422

    async def test_closed_and_trial_events_cannot_be_assigned(self, client: AsyncClient, db_session, camera, sent, notified):
        operator_id = await user_id(db_session, "operator")
        headers = await auth_headers(client, "admin", "admin123")
        rejected = await make_event(db_session, camera, status="rad_etilgan")
        trial = await make_event(db_session, camera, is_trial=True)
        for event_id in (rejected, trial):
            resp = await client.post(f"/api/events/{event_id}/assign", headers=headers, json={"userId": str(operator_id)})
            assert resp.status_code == 409

    async def test_assignees_lists_only_users_with_review_permission(self, client: AsyncClient, steward):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/events/assignees", headers=headers)
        assert resp.status_code == 200
        names = {u["fullName"]: u["role"] for u in resp.json()}
        assert names.get("Behzod Karimov") == "Admin"
        assert "Kamera Mas'uli" not in names


@pytest.mark.usefixtures("seeded")
class TestStatus:
    async def test_full_lifecycle(self, client: AsyncClient, db_session, camera, sent):
        event_id = await make_event(db_session, camera)
        headers = await auth_headers(client, "operator", "operator123")

        resp = await client.post(f"/api/events/{event_id}/status", headers=headers, json={"status": "jarayonda"})
        assert resp.status_code == 200, resp.text
        # Hech kimga tayinlanmagan hodisani olgan operatorga tayinlanadi.
        assert resp.json()["assignedToName"] == "Behzod Karimov"

        resp = await client.post(f"/api/events/{event_id}/status", headers=headers, json={"status": "tasdiqlangan"})
        assert resp.status_code == 200
        assert resp.json()["reviewedBy"] == "Behzod Karimov" and resp.json()["reviewedAt"]

        resp = await client.post(f"/api/events/{event_id}/status", headers=headers, json={"status": "hal_qilindi"})
        assert resp.status_code == 422  # yechim izohi majburiy
        resp = await client.post(
            f"/api/events/{event_id}/status", headers=headers, json={"status": "hal_qilindi", "note": "   "}
        )
        assert resp.status_code == 422

        resp = await client.post(
            f"/api/events/{event_id}/status",
            headers=headers,
            json={"status": "hal_qilindi", "note": "Qo'riqchi yuborildi, tartib tiklandi"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "hal_qilindi"
        assert body["resolutionNote"] == "Qo'riqchi yuborildi, tartib tiklandi"
        assert body["resolvedBy"] == "Behzod Karimov" and body["resolvedAt"]
        assert body["reviewedAt"]  # tasdiqlash qarori saqlanadi

        comments = (
            (await db_session.execute(select(EventComment).where(EventComment.event_id == event_id).order_by(EventComment.created_at)))
            .scalars()
            .all()
        )
        assert [c.kind for c in comments] == ["holat", "holat", "holat"]
        assert "Hal qilindi" in comments[-1].body and "Qo'riqchi" in comments[-1].body
        assert all(m["kind"] == "event_updated" for m in sent)

    async def test_reopen_clears_decision(self, client: AsyncClient, db_session, camera, sent):
        now = datetime.now(timezone.utc)
        event_id = await make_event(
            db_session, camera, status="hal_qilindi", reviewed_by="X", reviewed_at=now,
            resolved_at=now, resolved_by="X", resolution_note="Hal qilindi",
        )
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(f"/api/events/{event_id}/status", headers=headers, json={"status": "jarayonda"})
        assert resp.status_code == 200
        row = await reload(db_session, event_id)
        assert row.status == "jarayonda"
        assert row.reviewed_at is None and row.resolved_at is None and row.resolution_note is None

    async def test_return_to_queue_unassigns(self, client: AsyncClient, db_session, camera, sent):
        operator_id = await user_id(db_session, "operator")
        event_id = await make_event(db_session, camera, status="jarayonda", assigned_to_id=operator_id)
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(f"/api/events/{event_id}/status", headers=headers, json={"status": "yangi"})
        assert resp.status_code == 200
        assert resp.json()["assignedToId"] is None

    @pytest.mark.parametrize(
        ("current", "target"),
        [("rad_etilgan", "hal_qilindi"), ("tasdiqlangan", "yangi"), ("yangi", "yangi"), ("hal_qilindi", "yangi")],
    )
    async def test_invalid_transitions_are_conflicts(self, client: AsyncClient, db_session, camera, sent, current, target):
        event_id = await make_event(db_session, camera, status=current)
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            f"/api/events/{event_id}/status", headers=headers, json={"status": target, "note": "izoh"}
        )
        assert resp.status_code == 409
        assert (await reload(db_session, event_id)).status == current

    async def test_unknown_status_and_event(self, client: AsyncClient, db_session, camera, sent):
        event_id = await make_event(db_session, camera)
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(f"/api/events/{event_id}/status", headers=headers, json={"status": "yopildi"})
        assert resp.status_code == 422
        resp = await client.post(f"/api/events/{uuid.uuid4()}/status", headers=headers, json={"status": "jarayonda"})
        assert resp.status_code == 404
        resp = await client.post("/api/events/not-a-uuid/status", headers=headers, json={"status": "jarayonda"})
        assert resp.status_code == 404

    async def test_legacy_review_patch_still_works_and_records_history(self, client: AsyncClient, db_session, camera, sent):
        event_id = await make_event(db_session, camera)
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.patch(f"/api/events/{event_id}/review", headers=headers, json={"status": "tasdiqlangan"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "tasdiqlangan" and resp.json()["reviewedAt"]
        assert resp.json()["commentsCount"] == 1
        assert sent[-1]["kind"] == "event_updated"

    async def test_bulk_resolve_requires_note_and_skips_false_alarms(self, client: AsyncClient, db_session, camera, sent):
        confirmed = await make_event(db_session, camera, status="tasdiqlangan")
        fresh = await make_event(db_session, camera)
        rejected = await make_event(db_session, camera, status="rad_etilgan")
        headers = await auth_headers(client, "admin", "admin123")
        ids = [str(confirmed), str(fresh), str(rejected)]

        resp = await client.post("/api/events/review-bulk", headers=headers, json={"ids": ids, "status": "hal_qilindi"})
        assert resp.status_code == 422

        resp = await client.post(
            "/api/events/review-bulk", headers=headers, json={"ids": ids, "status": "hal_qilindi", "note": "Tekshirildi"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"updated": 2, "skipped": 1, "status": "hal_qilindi"}
        assert (await reload(db_session, rejected)).status == "rad_etilgan"
        resolved = await reload(db_session, fresh)
        assert resolved.status == "hal_qilindi" and resolved.resolution_note == "Tekshirildi" and resolved.reviewed_at
        assert sent[-1]["kind"] == "events_reviewed" and len(sent[-1]["ids"]) == 2


@pytest.mark.usefixtures("seeded")
class TestPermissions:
    async def test_workflow_endpoints_require_review_permission(self, client: AsyncClient, db_session, camera, steward):
        event_id = await make_event(db_session, camera)
        headers = await auth_headers(client, STEWARD_LOGIN, STEWARD_PASSWORD)
        calls = [
            ("post", f"/api/events/{event_id}/assign", {"userId": None}),
            ("post", f"/api/events/{event_id}/status", {"status": "jarayonda"}),
            ("post", f"/api/events/{event_id}/comments", {"body": "salom"}),
            ("get", f"/api/events/{event_id}/comments", None),
            ("get", f"/api/events/{event_id}/timeline", None),
            ("get", f"/api/events/{event_id}", None),
            ("get", "/api/events/assignees", None),
        ]
        for method, url, payload in calls:
            kwargs = {"json": payload} if payload is not None else {}
            resp = await getattr(client, method)(url, headers=headers, **kwargs)
            assert resp.status_code == 403, url

    async def test_requires_auth(self, client: AsyncClient, db_session, camera):
        event_id = await make_event(db_session, camera)
        resp = await client.post(f"/api/events/{event_id}/status", json={"status": "jarayonda"})
        assert resp.status_code == 401


@pytest.mark.usefixtures("seeded")
class TestComments:
    async def test_add_and_list_comments_and_timeline(self, client: AsyncClient, db_session, camera, sent):
        event_id = await make_event(db_session, camera, occurred_at=datetime.now(timezone.utc) - timedelta(minutes=5))
        headers = await auth_headers(client, "operator", "operator123")

        resp = await client.post(f"/api/events/{event_id}/comments", headers=headers, json={"body": "  Kameraga qaradim  "})
        assert resp.status_code == 201, resp.text
        assert resp.json()["body"] == "Kameraga qaradim"
        assert resp.json()["authorName"] == "Behzod Karimov" and resp.json()["kind"] == "izoh"
        assert sent[-1]["kind"] == "event_updated" and sent[-1]["commentsCount"] == 1

        assert (await client.post(f"/api/events/{event_id}/comments", headers=headers, json={"body": "   "})).status_code == 422
        assert (await client.post(f"/api/events/{event_id}/comments", headers=headers, json={"body": ""})).status_code == 422

        await client.post(f"/api/events/{event_id}/status", headers=headers, json={"status": "tasdiqlangan"})

        comments = (await client.get(f"/api/events/{event_id}/comments", headers=headers)).json()
        assert [c["kind"] for c in comments] == ["izoh", "holat"]

        timeline = (await client.get(f"/api/events/{event_id}/timeline", headers=headers)).json()
        assert [t["kind"] for t in timeline] == ["yaratildi", "izoh", "holat"]

    async def test_timeline_reconstructs_legacy_review_and_escalation(self, client: AsyncClient, db_session, camera):
        occurred = datetime.now(timezone.utc) - timedelta(hours=3)
        event_id = await make_event(
            db_session, camera, occurred_at=occurred, status="rad_etilgan", reviewed_by="Eski operator",
            reviewed_at=occurred + timedelta(hours=2), escalated_at=occurred + timedelta(hours=1),
        )
        headers = await auth_headers(client, "admin", "admin123")
        timeline = (await client.get(f"/api/events/{event_id}/timeline", headers=headers)).json()
        assert [t["kind"] for t in timeline] == ["yaratildi", "muddat", "holat"]
        assert timeline[2]["authorName"] == "Eski operator" and "Rad etilgan" in timeline[2]["body"]


@pytest.mark.usefixtures("seeded")
class TestListAndSummary:
    async def test_filters_and_workflow_counts(self, client: AsyncClient, db_session, camera):
        now = datetime.now(timezone.utc)
        admin_id = await user_id(db_session, "admin")
        operator_id = await user_id(db_session, "operator")
        mine_overdue = await make_event(
            db_session, camera, status="jarayonda", assigned_to_id=admin_id, due_at=now - timedelta(minutes=5)
        )
        await make_event(db_session, camera, due_at=now - timedelta(minutes=1))  # muddati o'tgan, tayinlanmagan
        await make_event(db_session, camera, due_at=now + timedelta(hours=1))  # hali vaqt bor
        await make_event(db_session, camera, status="tasdiqlangan", assigned_to_id=admin_id)
        await make_event(db_session, camera, status="jarayonda", assigned_to_id=operator_id)
        # Hal qilingan — muddati o'tgan bo'lsa ham "overdue" emas.
        await make_event(db_session, camera, status="hal_qilindi", due_at=now - timedelta(hours=2))
        await make_event(db_session, camera, is_trial=True, due_at=now - timedelta(hours=2))

        headers = await auth_headers(client, "admin", "admin123")
        summary = (await client.get("/api/events/summary", headers=headers)).json()
        assert summary["total"] == 6
        assert (summary["unreviewed"], summary["inProgress"], summary["confirmed"], summary["resolved"]) == (2, 2, 1, 1)
        assert summary["overdue"] == 2
        assert summary["assignedToMe"] == 2
        assert summary["unassigned"] == 2
        # Qaror kutayotganlar (yangi + jarayonda) og'irlik bo'yicha.
        assert summary["unreviewedMedium"] == 4

        async def ids(**params) -> list[str]:
            resp = await client.get("/api/events", headers=headers, params=params)
            assert resp.status_code == 200, resp.text
            return [e["id"] for e in resp.json()["items"]]

        assert len(await ids(assignedTo="me")) == 2
        assert len(await ids(assignedTo=str(operator_id))) == 1
        assert len(await ids(assignedTo="none", status="yangi,jarayonda")) == 2
        overdue = await ids(overdue="true")
        assert len(overdue) == 2 and str(mine_overdue) in overdue
        assert len(await ids(status="jarayonda")) == 2
        assert len(await ids(status="hal_qilindi")) == 1

        items = (await client.get("/api/events", headers=headers, params={"assignedTo": "me", "overdue": "true"})).json()["items"]
        assert len(items) == 1 and items[0]["overdue"] is True and items[0]["assignedToName"] == "Jamshid Alimov"
        assert items[0]["dueAt"] and items[0]["commentsCount"] == 0

        assert (await client.get("/api/events", headers=headers, params={"status": "yopildi"})).status_code == 422
        assert (await client.get("/api/events", headers=headers, params={"assignedTo": "kimdir"})).status_code == 422
        resp = await client.get("/api/events", headers=headers, params={"sort": "due"})
        assert resp.status_code == 200

    async def test_precision_counts_resolved_as_confirmed(self, client: AsyncClient, db_session, camera):
        recent = datetime.now(timezone.utc) - timedelta(days=1)
        for _ in range(4):
            await make_event(db_session, camera, status="tasdiqlangan", reviewed_at=recent)
        for _ in range(4):
            await make_event(db_session, camera, status="hal_qilindi", reviewed_at=recent, resolved_at=recent)
        for _ in range(2):
            await make_event(db_session, camera, status="rad_etilgan", reviewed_at=recent)
        headers = await auth_headers(client, "admin", "admin123")
        body = (await client.get("/api/events/summary", headers=headers)).json()
        assert body["recentPrecision"] == 80.0

    async def test_get_single_event(self, client: AsyncClient, db_session, camera):
        event_id = await make_event(db_session, camera)
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get(f"/api/events/{event_id}", headers=headers)
        assert resp.status_code == 200 and resp.json()["id"] == str(event_id)
        assert (await client.get(f"/api/events/{uuid.uuid4()}", headers=headers)).status_code == 404


@pytest.mark.usefixtures("seeded")
class TestEscalation:
    async def test_escalates_overdue_open_events_once(self, db_session, camera, monkeypatch):
        now = datetime.now(timezone.utc)
        overdue_new = await make_event(db_session, camera, due_at=now - timedelta(minutes=10))
        overdue_progress = await make_event(db_session, camera, status="jarayonda", due_at=now - timedelta(minutes=1))
        not_yet = await make_event(db_session, camera, due_at=now + timedelta(minutes=10))
        closed = await make_event(db_session, camera, status="tasdiqlangan", due_at=now - timedelta(minutes=10))
        trial = await make_event(db_session, camera, is_trial=True, due_at=now - timedelta(minutes=10))
        already = await make_event(
            db_session, camera, due_at=now - timedelta(minutes=10), escalated_at=now - timedelta(minutes=5)
        )

        notified: list[uuid.UUID] = []
        broadcasts: list[dict] = []

        async def fake_overdue(event):
            notified.append(event.id)

        async def capture(message):
            broadcasts.append(message)

        monkeypatch.setattr(event_escalation, "notify_event_overdue", fake_overdue)
        monkeypatch.setattr(event_escalation.manager, "broadcast", capture)

        count = await event_escalation.run_escalation_once(TestSessionLocal, now=now)
        assert count == 2
        assert set(notified) == {overdue_new, overdue_progress}
        assert {m["id"] for m in broadcasts} == {str(overdue_new), str(overdue_progress)}
        assert all(m["kind"] == "event_updated" and m["overdue"] for m in broadcasts)

        for event_id in (overdue_new, overdue_progress):
            assert (await reload(db_session, event_id)).escalated_at is not None
        for event_id in (not_yet, closed, trial):
            assert (await reload(db_session, event_id)).escalated_at is None
        assert (await reload(db_session, already)).escalated_at < now

        # Ikkinchi aylanish hech narsani qayta yubormaydi.
        assert await event_escalation.run_escalation_once(TestSessionLocal, now=now) == 0
        assert len(notified) == 2

    async def test_notification_failure_does_not_stop_the_batch(self, db_session, camera, monkeypatch):
        now = datetime.now(timezone.utc)
        for _ in range(3):
            await make_event(db_session, camera, due_at=now - timedelta(minutes=10))
        calls: list[uuid.UUID] = []

        async def flaky(event):
            calls.append(event.id)
            if len(calls) == 1:
                raise RuntimeError("telegram ishlamayapti")

        async def capture(message):
            return None

        monkeypatch.setattr(event_escalation, "notify_event_overdue", flaky)
        monkeypatch.setattr(event_escalation.manager, "broadcast", capture)
        assert await event_escalation.run_escalation_once(TestSessionLocal, now=now) == 3
        assert len(calls) == 3

    async def test_new_events_get_sla_due_at(self, client: AsyncClient, db_session, camera, sent):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/events",
            headers=headers,
            json={
                "cameraId": str(camera.id), "moduleCode": 17, "moduleName": "Tartib", "group": "D",
                "confidence": 70, "severity": "yuqori",
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["dueAt"] is not None and resp.json()["overdue"] is False
