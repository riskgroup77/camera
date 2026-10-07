"""Operator ochgan kamera — jonli yo'lak va tanilgan odam kartasi.

2026-10-06 o'lchovi (production): yuz chiqqan kadr natijasi 2.3-4.1 s
kechikardi — fon tahlillari band qilgan 24 slotdan biri bo'shashini kutish va
2 oqimli modellar. Endi jonli kadr zaxira joyda, 8 oqimli sessiyalarda."""

import asyncio
import threading
from types import SimpleNamespace

from app.jobs import attendance_ai
from app.services import face_recognition
from app.services.inference_gate import PRIORITY_ATTENDANCE, PRIORITY_BACKGROUND, PRIORITY_LIVE, PriorityInferenceGate


class TestReservedLiveSlots:
    async def test_live_passes_while_every_shared_slot_is_busy(self):
        gate = PriorityInferenceGate(1, live_reserved=1)
        release = asyncio.Event()

        async def hold():
            async with gate.slot(priority=PRIORITY_BACKGROUND):
                await release.wait()

        holder = asyncio.create_task(hold())
        await asyncio.sleep(0)
        # Umumiy slot band — jonli so'rov baribir darhol o'tadi.
        async with gate.slot(priority=PRIORITY_LIVE):
            assert gate.snapshot()["live_in_use"] == 1
            assert gate.snapshot()["in_use"] == 1
        release.set()
        await holder
        assert gate.snapshot() == {"max": 1, "in_use": 0, "waiting": 0, "live_in_use": 0}

    async def test_background_never_takes_the_reserve(self):
        gate = PriorityInferenceGate(1, live_reserved=1)
        release = asyncio.Event()
        served: list[str] = []

        async def hold():
            async with gate.slot(priority=PRIORITY_BACKGROUND):
                await release.wait()

        async def worker(name, priority):
            async with gate.slot(priority=priority):
                served.append(name)

        holder = asyncio.create_task(hold())
        await asyncio.sleep(0)
        waiting = asyncio.create_task(worker("eshik", PRIORITY_ATTENDANCE))
        await asyncio.sleep(0)
        assert served == [] and gate.snapshot()["waiting"] == 1
        release.set()
        await asyncio.gather(holder, waiting)
        assert served == ["eshik"]

    async def test_extra_live_requests_queue_first_in_the_shared_pool(self):
        gate = PriorityInferenceGate(1, live_reserved=1)
        release = asyncio.Event()
        served: list[str] = []

        async def hold(priority):
            async with gate.slot(priority=priority):
                await release.wait()

        async def worker(name, priority):
            async with gate.slot(priority=priority):
                served.append(name)

        holders = [asyncio.create_task(hold(PRIORITY_LIVE)), asyncio.create_task(hold(PRIORITY_BACKGROUND))]
        await asyncio.sleep(0)
        tasks = [asyncio.create_task(worker("fon", PRIORITY_BACKGROUND)), asyncio.create_task(worker("jonli", PRIORITY_LIVE))]
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(*holders, *tasks)
        assert served == ["jonli", "fon"]


class TestLiveModels:
    def _fake_app(self):
        detection = SimpleNamespace(name="det")
        recognition = SimpleNamespace(name="rec")
        return SimpleNamespace(models={"detection": detection, "recognition": recognition}, det_model=detection)

    def test_live_app_is_a_separate_copy_rebuilt_when_the_base_changes(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "face_live_intra_op_threads", 8)
        monkeypatch.setattr(settings, "face_recognition_intra_op_threads", 2)
        monkeypatch.setattr(face_recognition, "_live_app", None)
        base = self._fake_app()
        monkeypatch.setattr(face_recognition, "_get_app", lambda: base)
        live = face_recognition._get_live_app()
        assert live is not base and live.det_model is live.models["detection"]
        assert live.models["detection"] is not base.models["detection"]
        assert face_recognition._get_live_app() is live  # keshlangan

        other = self._fake_app()
        monkeypatch.setattr(face_recognition, "_get_app", lambda: other)
        assert face_recognition._get_live_app() is not live

    def test_no_copy_when_threads_are_not_higher(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "face_live_intra_op_threads", 2)
        monkeypatch.setattr(settings, "face_recognition_intra_op_threads", 2)
        base = self._fake_app()
        monkeypatch.setattr(face_recognition, "_get_app", lambda: base)
        assert face_recognition._get_live_app() is base

    async def test_live_priority_runs_on_the_live_lane(self, monkeypatch):
        from app.config import settings
        from app.services.inference_cache import inference_cache

        monkeypatch.setattr(settings, "face_live_reserved_slots", 2)
        calls: list[tuple[bool, str]] = []

        def fake_sync(image, threshold, analyse, roi, skip, landmarks, live=False):
            calls.append((live, threading.current_thread().name))
            return []

        monkeypatch.setattr(face_recognition, "_detect_faces_sync", fake_sync)
        inference_cache.clear()
        await face_recognition.detect_faces(b"live-frame", priority=PRIORITY_LIVE)
        await face_recognition.detect_faces(b"room-frame", priority=PRIORITY_BACKGROUND)
        (live_call, live_thread), (room_call, room_thread) = calls
        assert live_call is True and live_thread.startswith("face-live")
        assert room_call is False and not room_thread.startswith("face-live")

    async def test_enrollment_stays_off_the_live_lane(self, monkeypatch):
        """/royxatdan-otish pose-check'i kameraning 2 oqimli yo'lagiga
        tushmaydi (2026-10-07: yuzlab telefon shu 2 oqimga tiqilgan edi)."""
        from app.config import settings
        from app.services.inference_cache import inference_cache

        monkeypatch.setattr(settings, "face_live_reserved_slots", 2)
        calls: list[tuple[bool, bool, str]] = []

        def fake_sync(image, threshold, analyse, roi, skip, landmarks, live=False, embed=True, det_max_side=None):
            calls.append((live, embed, threading.current_thread().name))
            return []

        monkeypatch.setattr(face_recognition, "_detect_faces_sync", fake_sync)
        inference_cache.clear()
        await face_recognition.detect_faces(b"pose", priority=PRIORITY_LIVE, enrollment=True, embed=False)
        [(live, embed, thread)] = calls
        assert live is False and embed is False and thread.startswith("face-enroll")


class TestPersonCardInPayload:
    def test_sticky_track_keeps_the_whole_card(self):
        old = {
            "bbox": [0, 0, 50, 50],
            "status": "tanildi",
            "person_id": "p1",
            "person_name": "Ali Valiyev",
            "person_type": "talaba",
            "person_unit": "101-guruh",
            "photo_url": "https://s3/p1.jpg",
            "similarity": 0.7,
            "track_id": 3,
            "named_at": 100.0,
        }
        new = {"bbox": [4, 0, 54, 50], "status": "notanish", "person_id": None, "similarity": 0.3}
        attendance_ai._link_tracks([new], [old], lambda: 99, now=102.0)
        assert new["track_id"] == 3 and new["status"] == "tanildi"
        assert {k: new[k] for k in attendance_ai.PERSON_KEYS} == {k: old[k] for k in attendance_ai.PERSON_KEYS}

    def test_payload_carries_the_card_fields(self, monkeypatch):
        monkeypatch.setattr(attendance_ai, "jpeg_dimensions", lambda frame: (2560, 1440))
        entry = {
            "bbox": [1, 2, 3, 4],
            "status": "tanildi",
            "person_id": "p1",
            "person_name": "Ali",
            "person_type": "xodim",
            "person_unit": "Dekan",
            "photo_url": "u",
            "similarity": 0.8,
            "track_id": 1,
        }
        face = attendance_ai._overlay_payload(b"", [entry], source="asosiy", captured_at=1.0)["faces"][0]
        assert (face["person_id"], face["person_type"], face["person_unit"], face["photo_url"]) == ("p1", "xodim", "Dekan", "u")

    def test_watched_camera_rechecks_unknown_faces_every_frame(self):
        import inspect

        source = inspect.getsource(attendance_ai._watch_entrance_camera)
        assert "unknown_skip=() if live else active_unknown" in source


def test_already_quantized_model_is_not_quantized_again(tmp_path, monkeypatch):
    """2026-10-06: har qayta ishga tushishda det_10g.int8.int8...onnx (47 qavat)."""
    from app.config import settings

    monkeypatch.setattr(settings, "face_detection_int8", True)
    path = str(tmp_path / "det_10g.int8.onnx")
    assert face_recognition._int8_model_file(path, "detection") == path

    for name in ("det_10g.onnx", "det_10g.int8.onnx", "det_10g.int8.int8.onnx", "w600k_r50.int8.int8.int8.onnx",
                 "x.onnx.part", "w600k_r50.int8.int8-inferred.onnx"):
        (tmp_path / name).write_bytes(b"x")
    assert face_recognition._remove_nested_int8_models(str(tmp_path)) == 4
    assert sorted(p.name for p in tmp_path.iterdir()) == ["det_10g.int8.onnx", "det_10g.onnx"]
