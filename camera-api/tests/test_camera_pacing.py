"""Hisoblash kuchini yuz ko'rayotgan kameralarga yo'naltirish
(app/services/camera_pacing.py, attendance_ai._watch_entrance_camera)."""

import asyncio

import pytest

from app.config import settings
from app.jobs import attendance_ai
from app.services import recognition_stats
from app.services.camera_pacing import CameraPacer
from tests.test_entrance_watchers import _camera, _context


@pytest.fixture(autouse=True)
def _pacing(monkeypatch):
    monkeypatch.setattr(settings, "pacing_enabled", True)
    monkeypatch.setattr(settings, "pacing_idle_after", 3)
    monkeypatch.setattr(settings, "pacing_idle_base_seconds", 20.0)
    monkeypatch.setattr(settings, "pacing_idle_max_seconds", 150.0)


class TestPacer:
    def test_empty_frames_back_off_and_are_capped(self):
        pacer = CameraPacer()
        waits = [pacer.note(0) for _ in range(8)]
        assert waits[:2] == [0.0, 0.0]
        assert waits[2:6] == [20.0, 40.0, 80.0, 150.0]
        assert max(waits) == 150.0

    def test_one_useful_face_restores_full_speed(self):
        pacer = CameraPacer()
        for _ in range(6):
            pacer.note(0)
        assert pacer.note(1) == 0.0
        assert pacer.note(0) == 0.0  # hisob qaytadan boshlanadi

    def test_entrance_camera_never_waits(self):
        pacer = CameraPacer(exempt=True)
        assert all(pacer.note(0) == 0.0 for _ in range(10))

    def test_can_be_switched_off(self, monkeypatch):
        monkeypatch.setattr(settings, "pacing_enabled", False)
        pacer = CameraPacer()
        assert all(pacer.note(0) == 0.0 for _ in range(10))


class TestWatcherPacing:
    async def _run(self, monkeypatch, camera, useful_per_frame: list[int]):
        recognition_stats.reset_for_tests()
        monkeypatch.setattr(settings, "room_watcher_start_delay_seconds", 0.0)
        monkeypatch.setattr(settings, "room_watcher_start_spread_seconds", 0.0)
        frames = [(bytes([i]), i) for i in range(len(useful_per_frame))]
        sleeps: list[float] = []
        done = asyncio.Event()
        real_sleep = asyncio.sleep
        clock = [1000.0]

        async def fake_sleep(seconds):
            if seconds > 0.02:
                sleeps.append(seconds)
            clock[0] += seconds
            await real_sleep(0)

        async def fake_grab(camera, *, wait_seconds, after_seq):
            if frames:
                return frames.pop(0)
            done.set()
            await asyncio.Event().wait()

        async def fake_analyse(camera, frame, context, **_options):
            stats = recognition_stats._camera_stats(str(camera.id))
            stats.faces += useful_per_frame[frame[0]]
            return 0

        monkeypatch.setattr(attendance_ai.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(attendance_ai, "monotonic", lambda: clock[0])
        monkeypatch.setattr(attendance_ai, "grab_newer_frame", fake_grab)
        monkeypatch.setattr(attendance_ai, "_analyse_entrance_frame", fake_analyse)
        monkeypatch.setattr(attendance_ai, "_entrance_context", _context())
        monkeypatch.setattr(attendance_ai, "_useful_face_total", lambda key: recognition_stats._camera_stats(key).faces)
        task = asyncio.create_task(attendance_ai._watch_entrance_camera(camera, attendance_ai._EntranceWatcher(())))
        await asyncio.wait_for(done.wait(), timeout=2)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return sleeps, recognition_stats.export_snapshot().get(str(camera.id), {})

    async def test_room_without_faces_yields_its_turn(self, monkeypatch):
        from app.config import settings

        # Harakat bilan uyg'onish o'chiq (bu test faqat kutish jadvalini tekshiradi).
        monkeypatch.setattr(settings, "pacing_motion_wake_any", False)
        room = _camera("xona-1", name="1-xona", is_entrance=False, is_exit=False)
        sleeps, stats = await self._run(monkeypatch, room, [0, 0, 0, 0])
        # 3- va 4-bo'sh kadrdan keyin kutadi (20 s, 40 s — 5 s lik bo'laklarda).
        assert sum(sleeps) == pytest.approx(60.0)
        assert stats["idle_waits"] == 2 and stats["idle_seconds"] == 60.0

    async def test_busy_room_never_waits(self, monkeypatch):
        room = _camera("xona-2", name="2-xona", is_entrance=False, is_exit=False)
        sleeps, stats = await self._run(monkeypatch, room, [2, 1, 3, 1])
        assert sleeps == []
        assert stats["idle_waits"] == 0

    async def test_entrance_never_waits(self, monkeypatch):
        sleeps, _stats = await self._run(monkeypatch, _camera("kirish-1"), [0, 0, 0, 0, 0])
        assert sleeps == []
