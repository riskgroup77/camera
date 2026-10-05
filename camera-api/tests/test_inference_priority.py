"""Eshik (kirish/chiqish) kadrlari yuz tanish navbatini xona kameralaridan
oldin oladi.

Productionda o'lchandi: konteyner cpus: 20 chegarasida turganda kirish
kamerasi kadri 100+ xona kamerasini aylanib chiqadigan fon tekshiruvi bilan
bitta navbatda kutardi."""

import asyncio
import inspect

import numpy as np
import pytest

from app.jobs import attendance_ai
from app.services.face_matching import CandidateMatrix
from app.services.inference_gate import (
    PRIORITY_ATTENDANCE,
    PRIORITY_BACKGROUND,
    PRIORITY_LIVE,
    PriorityInferenceGate,
)


class TestGateOrder:
    async def test_attendance_is_served_before_earlier_queued_background_work(self):
        gate = PriorityInferenceGate(1)
        served: list[str] = []
        release = asyncio.Event()

        async def hold():
            async with gate.slot(priority=PRIORITY_BACKGROUND):
                await release.wait()

        async def worker(name: str, priority: int):
            async with gate.slot(priority=priority):
                served.append(name)

        holder = asyncio.create_task(hold())
        await asyncio.sleep(0)
        # Navbatga kelish tartibi: avval fon, keyin davomat, keyin jonli ko'rish.
        tasks = [
            asyncio.create_task(worker("xona", PRIORITY_BACKGROUND)),
            asyncio.create_task(worker("eshik", PRIORITY_ATTENDANCE)),
            asyncio.create_task(worker("jonli", PRIORITY_LIVE)),
        ]
        await asyncio.sleep(0)
        assert gate.snapshot()["waiting"] == 3

        release.set()
        await asyncio.gather(holder, *tasks)
        assert served == ["jonli", "eshik", "xona"]

    def test_priority_levels_are_ordered(self):
        assert PRIORITY_LIVE < PRIORITY_ATTENDANCE < PRIORITY_BACKGROUND


class TestAttendanceUsesItsPriority:
    async def test_process_camera_frame_forwards_priority_to_detection(self, db_session, monkeypatch):
        seen: list[int] = []

        async def fake_detect(frame_bytes, *, priority, **_options):
            seen.append(priority)
            return []

        monkeypatch.setattr(attendance_ai, "detect_faces", fake_detect)
        candidates = CandidateMatrix(ids=["p1"], matrix=np.array([[1.0, 0.0]]))

        await attendance_ai.process_camera_frame(b"x", db_session, None, candidates=candidates)
        await attendance_ai.process_camera_frame(
            b"x", db_session, None, candidates=candidates, inference_priority=PRIORITY_ATTENDANCE
        )
        assert seen == [PRIORITY_BACKGROUND, PRIORITY_ATTENDANCE]

    def test_entrance_camera_loop_requests_attendance_priority(self):
        # Kirish kamerasi kuzatuvchisi ham, bir martalik tekshiruv ham
        # process_camera_frame'ni PRIORITY_ATTENDANCE bilan chaqiradi.
        # Kuzatuvchi: operator ko'rayotgan kamera PRIORITY_LIVE, qolganlari ATTENDANCE.
        source = inspect.getsource(attendance_ai._analyse_entrance_frame)
        assert "inference_priority=PRIORITY_LIVE if live else PRIORITY_ATTENDANCE" in source
        assert "inference_priority=PRIORITY_ATTENDANCE" in inspect.getsource(
            attendance_ai.run_entrance_exit_attendance_sweep_once
        )
        # Xona kameralari (unified_face_sweep) esa tegilmagan — fon navbatida qoladi.
        from app.jobs import unified_face_sweep

        assert "PRIORITY_ATTENDANCE" not in inspect.getsource(unified_face_sweep)


class TestCancelledWaitersDoNotLeakSlots:
    """Kutayotgan so'rov bekor qilinsa, slot abadiy band bo'lib qolmasligi kerak."""

    async def test_cancel_while_queued(self):
        gate = PriorityInferenceGate(1)
        holder_in = asyncio.Event()
        release = asyncio.Event()

        async def holder():
            async with gate.slot():
                holder_in.set()
                await release.wait()

        async def waiter():
            async with gate.slot():
                pass

        holding = asyncio.create_task(holder())
        await holder_in.wait()
        waiting = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        assert gate.snapshot()["waiting"] == 1

        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        release.set()
        await holding

        assert gate.snapshot() == {"max": 1, "in_use": 0, "waiting": 0}
        async with gate.slot():  # darhol olinadi
            assert gate.snapshot()["in_use"] == 1

    async def test_cancel_right_after_the_slot_was_granted(self):
        gate = PriorityInferenceGate(1)
        entered = []

        async def waiter():
            async with gate.slot():
                entered.append(True)

        async with gate.slot():
            waiting = asyncio.create_task(waiter())
            await asyncio.sleep(0)
        # Chiqishda slot kutuvchiga berildi (event o'rnatildi), lekin u hali
        # davom etmadi — aynan shu lahzada bekor qilamiz.
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting

        assert entered == []
        assert gate.snapshot() == {"max": 1, "in_use": 0, "waiting": 0}
