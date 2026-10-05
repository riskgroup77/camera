"""GET /metrics — Prometheus ko'rsatkichlari va ularning himoyasi."""

from collections.abc import AsyncGenerator
from datetime import datetime, time, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from prometheus_client.parser import text_string_to_metric_families
from sqlalchemy import select

from app.config import settings
from app.database import get_db
from app.jobs import scheduler_metrics
from app.main import app
from app.models import AccessEvent, AttendanceRecord, Building, Camera, Event, Faculty, NotificationLog, StudentStaff
from app.routers import metrics as metrics_module
from app.services import runtime_snapshot
from app.timezone import INSTITUTE_TZ, local_now


@pytest.fixture(autouse=True)
def _metrics_defaults(monkeypatch):
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(settings, "metrics_token", "")
    monkeypatch.setattr(settings, "redis_url", "")
    metrics_module.reset_metrics_cache()
    scheduler_metrics.reset_for_tests()
    runtime_snapshot.reset_for_tests()
    yield
    metrics_module.reset_metrics_cache()
    scheduler_metrics.reset_for_tests()
    runtime_snapshot.reset_for_tests()


@pytest_asyncio.fixture
async def public_client(db_session) -> AsyncGenerator[AsyncClient, None]:
    """Tashqi (internet) manzildan kelgan so'rovlar."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app, client=("8.8.8.8", 40000))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def _samples(text: str) -> dict[tuple[str, tuple[tuple[str, str], ...]], float]:
    out: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            out[(sample.name, tuple(sorted(sample.labels.items())))] = sample.value
    return out


def _value(samples, metric: str, /, **labels: str) -> float | None:
    return samples.get((metric,tuple(sorted(labels.items()))))


class TestAccess:
    async def test_disabled_returns_404(self, client: AsyncClient, monkeypatch):
        monkeypatch.setattr(settings, "metrics_enabled", False)
        resp = await client.get("/metrics")
        assert resp.status_code == 404

    async def test_loopback_without_token_is_allowed(self, client: AsyncClient):
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        samples = _samples(resp.text)
        assert _value(samples, "sm_metrics_collect_success") == 1
        assert _value(samples, "sm_cameras_total") == 0

    async def test_public_ip_without_token_is_forbidden(self, public_client: AsyncClient):
        resp = await public_client.get("/metrics")
        assert resp.status_code == 403

    async def test_proxied_public_client_is_forbidden(self, client: AsyncClient):
        # nginx (ichki manzil) orqali kelgan tashqi foydalanuvchi.
        resp = await client.get("/metrics", headers={"X-Forwarded-For": "203.0.113.7", "X-Real-IP": "203.0.113.7"})
        assert resp.status_code == 403

    async def test_proxied_private_client_is_allowed(self, client: AsyncClient):
        resp = await client.get("/metrics", headers={"X-Forwarded-For": "172.18.0.5"})
        assert resp.status_code == 200

    async def test_token_required_when_configured(self, client: AsyncClient, monkeypatch):
        monkeypatch.setattr(settings, "metrics_token", "s3cret-token")
        resp = await client.get("/metrics")
        assert resp.status_code == 401
        assert resp.headers.get("www-authenticate") == "Bearer"
        resp = await client.get("/metrics", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401
        resp = await client.get("/metrics", headers={"Authorization": "Basic s3cret-token"})
        assert resp.status_code == 401

    async def test_valid_token_allows_public_ip(self, public_client: AsyncClient, monkeypatch):
        monkeypatch.setattr(settings, "metrics_token", "s3cret-token")
        resp = await public_client.get("/metrics", headers={"Authorization": "Bearer s3cret-token"})
        assert resp.status_code == 200
        assert "sm_cameras_total" in resp.text

    async def test_app_info_uses_app_version(self, client: AsyncClient, monkeypatch):
        monkeypatch.setenv("APP_VERSION", "abc1234")
        resp = await client.get("/metrics")
        samples = _samples(resp.text)
        assert _value(samples, "sm_app_info", version="abc1234", role=settings.ai_role,
                      system=settings.org_system_name) == 1


async def _building(db) -> Building:
    return (await db.execute(select(Building))).scalars().first()


async def _person(db) -> StudentStaff:
    faculty = (await db.execute(select(Faculty))).scalars().first()
    person = StudentStaff(full_name="Ali Valiyev", type="xodim", faculty_id=faculty.id, group_or_position="Kafedra")
    db.add(person)
    await db.commit()
    return person


def _event(camera: Camera, **kwargs) -> Event:
    values = dict(
        camera_id=camera.id, camera_name=camera.name, building="1-bino", module_code=14,
        module_name="Chekish", group="D", confidence=80, severity="yuqori", status="yangi",
    )
    values.update(kwargs)
    return Event(**values)


@pytest.mark.usefixtures("seeded")
class TestContent:
    async def test_system_gauges(self, client: AsyncClient, db_session):
        building = await _building(db_session)
        now = datetime.now(timezone.utc)
        stale = now - timedelta(seconds=settings.camera_health_freshness_seconds + 60)
        live = Camera(name="Kirish", ip="10.0.0.1", port=554, building_id=building.id, zone="Z",
                      resolution="1080p", status="faol", last_seen_at=now, last_frame_at=now)
        blind = Camera(name="Yo'lak", ip="10.0.0.2", port=554, building_id=building.id, zone="Z",
                       resolution="1080p", status="faol", last_seen_at=now, last_frame_at=None)
        offline = Camera(name="Hovli", ip="10.0.0.3", port=554, building_id=building.id, zone="Z",
                         resolution="1080p", status="faol", last_seen_at=stale)
        disabled = Camera(name="Ombor", ip="10.0.0.4", port=554, building_id=building.id, zone="Z",
                          resolution="1080p", status="nofaol")
        db_session.add_all([live, blind, offline, disabled])
        await db_session.commit()

        person = await _person(db_session)
        db_session.add_all([
            _event(live, occurred_at=now - timedelta(minutes=5), due_at=now - timedelta(minutes=1)),
            _event(live, occurred_at=now - timedelta(minutes=10), status="jarayonda", severity="o'rta"),
            _event(live, occurred_at=now - timedelta(minutes=15), status="hal_qilindi",
                   due_at=now - timedelta(minutes=1)),
            # Sinov rejimi signali hech qayerda sanalmaydi.
            _event(live, occurred_at=now - timedelta(minutes=5), is_trial=True, due_at=now - timedelta(minutes=1)),
            # Bir soatdan eski — faqat ochiq hodisalar sonida.
            _event(live, occurred_at=now - timedelta(hours=3), module_code=5, module_name="Yong'in"),
            AttendanceRecord(student_staff_id=person.id, date=local_now().date(), status="keldi", source="kamera",
                             check_in=time(8, 55)),
            AccessEvent(external_id="1", occurred_at=now - timedelta(minutes=2), granted=True, direction="kirish"),
            AccessEvent(external_id="2", occurred_at=now - timedelta(minutes=3), granted=False, direction="kirish"),
            AccessEvent(external_id="3", occurred_at=now - timedelta(hours=2), granted=True, direction="kirish"),
            NotificationLog(channel="telegram", recipient="1", kind="event", status="yuborildi"),
            NotificationLog(channel="telegram", recipient="2", kind="event", status="xato"),
        ])
        await db_session.commit()

        resp = await client.get("/metrics")
        assert resp.status_code == 200
        s = _samples(resp.text)

        assert _value(s, "sm_cameras_total") == 4
        assert _value(s, "sm_cameras", status="faol") == 3
        assert _value(s, "sm_cameras", status="nofaol") == 1
        assert _value(s, "sm_cameras_active") == 3
        assert _value(s, "sm_cameras_reachable") == 2
        assert _value(s, "sm_cameras_video_flowing") == 1

        assert _value(s, "sm_events_last_hour", module_code="14", module="Chekish", severity="yuqori") == 2
        assert _value(s, "sm_events_last_hour", module_code="14", module="Chekish", severity="o'rta") == 1
        assert _value(s, "sm_events_last_hour", module_code="5", module="Yong'in", severity="yuqori") is None
        assert _value(s, "sm_events_unreviewed") == 2
        assert _value(s, "sm_events_open", status="yangi") == 2
        assert _value(s, "sm_events_open", status="jarayonda") == 1
        assert _value(s, "sm_events_overdue") == 1

        assert _value(s, "sm_attendance_records_today", status="keldi", source="kamera") == 1
        expected = datetime.combine(local_now().date(), time(8, 55), tzinfo=INSTITUTE_TZ).timestamp()
        assert _value(s, "sm_attendance_last_check_in_timestamp_seconds") == expected

        assert _value(s, "sm_access_events_last_hour", granted="true", direction="kirish") == 1
        assert _value(s, "sm_access_events_last_hour", granted="false", direction="kirish") == 1
        assert _value(s, "sm_notifications_last_hour", channel="telegram", status="yuborildi") == 1
        assert _value(s, "sm_notifications_last_hour", channel="telegram", status="xato") == 1

    async def test_snapshot_is_cached(self, client: AsyncClient, db_session):
        building = await _building(db_session)
        first = _samples((await client.get("/metrics")).text)
        assert _value(first, "sm_cameras_total") == 0

        db_session.add(Camera(name="Yangi", ip="10.0.0.9", port=554, building_id=building.id, zone="Z",
                              resolution="1080p", status="faol"))
        await db_session.commit()

        cached = _samples((await client.get("/metrics")).text)
        assert _value(cached, "sm_cameras_total") == 0

        metrics_module.reset_metrics_cache()
        fresh = _samples((await client.get("/metrics")).text)
        assert _value(fresh, "sm_cameras_total") == 1

    async def test_database_failure_is_reported_not_raised(self, client: AsyncClient, monkeypatch):
        async def boom(db):
            raise RuntimeError("db down")

        monkeypatch.setattr(metrics_module, "_camera_families", boom)
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert _value(_samples(resp.text), "sm_metrics_collect_success") == 0


class TestAiRuntime:
    async def test_sweep_stats_exported(self, client: AsyncClient):
        scheduler_metrics.register_sweep("zone_entry", "critical", 30)
        scheduler_metrics.record_sweep_started("zone_entry")
        scheduler_metrics.record_sweep_finished("zone_entry", duration_seconds=2.5, result=3)
        scheduler_metrics.register_sweep("teacher_punctuality", "standard", 60)
        scheduler_metrics.record_sweep_started("teacher_punctuality")
        scheduler_metrics.record_sweep_finished("teacher_punctuality", duration_seconds=1.0, result=0, error="boom")

        s = _samples((await client.get("/metrics")).text)
        assert _value(s, "sm_ai_sweep_runs", name="zone_entry", tier="critical") == 1
        assert _value(s, "sm_ai_sweep_last_duration_seconds", name="zone_entry", tier="critical") == 2.5
        assert _value(s, "sm_ai_sweep_failures", name="teacher_punctuality", tier="standard") == 1
        assert _value(s, "sm_ai_sweep_lagging", name="zone_entry", tier="critical") == 0
        assert _value(s, "sm_ai_sweep_last_finished_timestamp_seconds", name="zone_entry", tier="critical") is not None
        assert _value(s, "sm_ai_stream_readers") is not None
        # AI (leader) surati yo'q — shu jarayon o'lchanmaydi.
        assert _value(s, "sm_ai_entrance_watchers") is None

    async def test_leader_process_view_exported(self, client: AsyncClient, monkeypatch):
        finished = datetime.now(timezone.utc).isoformat()
        view = {
            "sweep_slots": {"max": 18, "in_use": 4},
            "entrance_exit_sweep_slots": {"max": 12, "in_use": 2},
            "face_inference_gate": {"max": 10, "in_use": 3, "waiting": 1},
            "gpu": {"cuda_available": True},
            "camera_health_sweep": {"finished_at": finished, "duration_seconds": 1.5, "faol_checked": 300,
                                    "reachable": 290, "skipped_overlap": False},
            "entrance_watchers": 6,
        }
        monkeypatch.setattr(runtime_snapshot, "_is_publisher", True)
        monkeypatch.setattr(runtime_snapshot, "local_process_view", lambda: view)

        s = _samples((await client.get("/metrics")).text)
        assert _value(s, "sm_ai_slots", pool="global", kind="in_use") == 4
        assert _value(s, "sm_ai_slots", pool="entrance_exit", kind="max") == 12
        assert _value(s, "sm_ai_face_inference_gate", kind="waiting") == 1
        assert _value(s, "sm_ai_entrance_watchers") == 6
        assert _value(s, "sm_camera_health_sweep", kind="reachable") == 290
        assert _value(s, "sm_ai_gpu_cuda_available") == 1
