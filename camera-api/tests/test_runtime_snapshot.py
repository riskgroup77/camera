"""AI holati API jarayonlari o'rtasida Redis orqali ulashiladi.

Productionda WEB_CONCURRENCY=2, AI esa faqat leader jarayonda ishlaydi.
Ilgari so'rov leader bo'lmagan jarayonga tushsa, "Davomat kameralari"
tashxisi "hali tekshirilmadi", boshqaruv paneli esa "0 modul" ko'rsatardi."""

import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from app.jobs import scheduler_metrics
from app.services import recognition_stats, runtime_snapshot
from app.services.face_matching import GradedMatch


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.ttl: dict[str, int] = {}
        self.hashes: dict[str, dict[str, str]] = {}

    async def get(self, key):
        return self.store.get(key)

    async def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def hdel(self, key, *fields):
        for field in fields:
            self.hashes.get(key, {}).pop(field, None)

    def pipeline(self, transaction=False):
        redis = self

        class _Pipe:
            def __init__(self):
                self.ops = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def set(self, key, value, ex=None):
                self.ops.append((key, value, ex))

            async def execute(self):
                for key, value, ex in self.ops:
                    redis.store[key] = value
                    redis.ttl[key] = ex

        return _Pipe()


@pytest.fixture(autouse=True)
def _clean():
    recognition_stats.reset_for_tests()
    scheduler_metrics.reset_for_tests()
    runtime_snapshot.reset_for_tests()
    yield
    recognition_stats.reset_for_tests()
    scheduler_metrics.reset_for_tests()
    runtime_snapshot.reset_for_tests()


@pytest.fixture
def fake_redis(monkeypatch):
    redis = FakeRedis()

    async def _get():
        return redis

    monkeypatch.setattr(runtime_snapshot, "_get_redis", _get)
    monkeypatch.setattr(runtime_snapshot, "_redis_url", lambda: "redis://fake:6379/0")
    return redis


def _record_sample_frame(camera_id: str) -> None:
    face = SimpleNamespace(embedding=np.zeros(4), bbox=np.array([0, 0, 80, 96]))
    recognition_stats.record_frame(camera_id, [face], [GradedMatch("p1", 0.51, 0.2, "relaxed")])
    recognition_stats.record_credit(camera_id, "relaxed_pending")


class TestRecognitionShared:
    async def test_other_worker_sees_leader_stats_through_redis(self, fake_redis):
        _record_sample_frame("cam-1")
        assert await runtime_snapshot.publish_once() is True
        assert fake_redis.ttl[runtime_snapshot.KEY_RECOGNITION] == runtime_snapshot.SNAPSHOT_TTL_SECONDS

        # Boshqa jarayon: o'z xotirasi bo'sh, surat Redis'dan.
        recognition_stats.reset_for_tests()
        views = await runtime_snapshot.load_recognition_views()
        view = views["cam-1"]
        assert view.frames == 1 and view.faces == 1
        assert view.face_px_median == 96
        assert view.relaxed_pending == 1
        assert view.buckets["0.47-0.55"] == 1
        assert view.best_similarity == pytest.approx(0.51)
        assert view.last_frame_at is not None

    async def test_leader_reads_its_own_memory(self, fake_redis):
        runtime_snapshot._is_publisher = True
        _record_sample_frame("cam-2")
        # Redis'da hech narsa yo'q, lekin leader o'z xotirasidan ko'radi.
        views = await runtime_snapshot.load_recognition_views()
        assert views["cam-2"].frames == 1

    async def test_without_redis_each_process_uses_local_memory(self, monkeypatch):
        monkeypatch.setattr(runtime_snapshot, "_redis_url", lambda: None)
        _record_sample_frame("cam-3")
        views = await runtime_snapshot.load_recognition_views()
        assert views["cam-3"].faces == 1

    async def test_yesterdays_snapshot_is_ignored(self, fake_redis):
        _record_sample_frame("cam-4")
        snapshot = recognition_stats.export_snapshot()
        snapshot["cam-4"]["day"] = "2000-01-01"
        fake_redis.store[runtime_snapshot.KEY_RECOGNITION] = json.dumps(snapshot)
        recognition_stats.reset_for_tests()
        assert await runtime_snapshot.load_recognition_views() == {}

    async def test_leader_not_published_yet_means_empty_not_error(self, fake_redis):
        assert await runtime_snapshot.load_recognition_views() == {}


class TestSweepsShared:
    async def test_dashboard_tick_is_the_same_on_every_worker(self, fake_redis):
        scheduler_metrics.register_sweep("entrance_exit_attendance", "critical", 6)
        scheduler_metrics.record_sweep_started("entrance_exit_attendance")
        scheduler_metrics.record_sweep_finished("entrance_exit_attendance", duration_seconds=2.5, result=3)
        await runtime_snapshot.publish_once()

        scheduler_metrics.reset_for_tests()  # boshqa jarayon
        sweeps = await runtime_snapshot.load_sweep_stats()
        assert [s.name for s in sweeps] == ["entrance_exit_attendance"]
        assert sweeps[0].runs == 1 and sweeps[0].last_result == 3
        tick = scheduler_metrics.tick_from_sweeps(sweeps)
        assert tick.modules_ran == 1 and tick.critical_ran == 1

    def test_malformed_rows_are_skipped(self):
        ok = {
            "name": "fire", "tier": "critical", "interval_seconds": 30,
            "last_finished_at": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
        }
        rows = [ok, {"tier": "critical"}, {"name": "x", "tier": "s", "interval_seconds": "nope"}]
        assert [s.name for s in scheduler_metrics.sweeps_from_dicts(rows)] == ["fire"]


class TestDashboardIsTheSameOnEveryWorker:
    """Productionda panel so'rov qaysi jarayonga tushganiga qarab
    "slotlar 0/18" yoki "18/18", "o'quvchilar 66" yoki "107" ko'rsatardi."""

    async def test_other_worker_shows_the_leaders_slots_and_gpu(self, fake_redis, monkeypatch):
        leader_view = {
            "sweep_slots": {"max": 18, "in_use": 18},
            "entrance_exit_sweep_slots": {"max": 4, "in_use": 2},
            "face_inference_gate": {"max": 2, "in_use": 2, "waiting": 5},
            "gpu": {"cuda_available": True, "face_gpu_active": True},
        }
        monkeypatch.setattr(runtime_snapshot, "local_process_view", lambda: leader_view)
        await runtime_snapshot.publish_once()

        idle_view = {**leader_view, "sweep_slots": {"max": 18, "in_use": 0}}
        monkeypatch.setattr(runtime_snapshot, "local_process_view", lambda: idle_view)  # boshqa jarayon
        assert await runtime_snapshot.load_leader_process_view() == leader_view

    async def test_the_leader_answers_from_its_own_memory(self, fake_redis, monkeypatch):
        runtime_snapshot._is_publisher = True
        monkeypatch.setattr(runtime_snapshot, "local_process_view", lambda: {"sweep_slots": {"in_use": 3}})
        assert await runtime_snapshot.load_leader_process_view() == {"sweep_slots": {"in_use": 3}}

    async def test_stream_readers_are_summed_over_live_workers(self, fake_redis, monkeypatch):
        monkeypatch.setattr(runtime_snapshot, "active_stream_reader_count", lambda: 66)
        monkeypatch.setattr(runtime_snapshot, "_process_id", lambda: "api:7")
        await runtime_snapshot.publish_stream_readers_once()

        now = int(time.time())
        fake_redis.hashes[runtime_snapshot.KEY_STREAM_READERS]["api:8"] = f"107:{now}"
        fake_redis.hashes[runtime_snapshot.KEY_STREAM_READERS]["api:3"] = f"40:{now - 600}"  # to'xtagan jarayon
        fake_redis.hashes[runtime_snapshot.KEY_STREAM_READERS]["api:4"] = "buzuq"

        assert await runtime_snapshot.total_stream_readers() == 66 + 107
        assert set(fake_redis.hashes[runtime_snapshot.KEY_STREAM_READERS]) == {"api:7", "api:8"}

    async def test_without_redis_only_this_process_counts(self, monkeypatch):
        monkeypatch.setattr(runtime_snapshot, "_redis_url", lambda: None)
        monkeypatch.setattr(runtime_snapshot, "active_stream_reader_count", lambda: 5)
        assert await runtime_snapshot.total_stream_readers() == 5

    async def test_camera_network_sweep_is_the_leaders(self, fake_redis, monkeypatch):
        """"Kamera tarmog'i" paneli leader bo'lmagan jarayonda "0/0" ko'rsatardi."""
        from app.jobs import camera_health_metrics

        # monkeypatch test oxirida asl qiymatni qaytaradi — boshqa testlarga o'tmaydi.
        monkeypatch.setattr(camera_health_metrics, "_last_sweep", camera_health_metrics.CameraHealthSweepStats())
        camera_health_metrics.record_camera_health_sweep(duration_seconds=2.25, faol_checked=107, reachable=107)
        await runtime_snapshot.publish_once()
        monkeypatch.setattr(camera_health_metrics, "_last_sweep", camera_health_metrics.CameraHealthSweepStats())

        view = await runtime_snapshot.load_leader_process_view()

        assert view["camera_health_sweep"]["faol_checked"] == 107
        assert view["camera_health_sweep"]["reachable"] == 107
