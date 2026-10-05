"""Kirish/chiqish kameralarini doimiy kuzatish (app/jobs/attendance_ai.py).

Productionda (2026-09-18) kirish kamerasi 21-100 s da bir marta
tekshirilardi, odam esa eshikdan 2-3 s da o'tadi. Endi har kameraning o'z
kuzatuvchisi bor: kesh yangi kadr berishi bilan u aynan bir marta tahlil
qilinadi.
"""

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import select

from app.jobs import attendance_ai
from app.models import AIModuleConfig, Building, Camera
from app.services import recognition_stats
from app.services.face_matching import CandidateMatrix
from app.timezone import local_now
from tests.conftest import TestSessionLocal


@pytest.fixture(autouse=True)
async def _clean(monkeypatch):
    recognition_stats.reset_for_tests()
    monkeypatch.setattr(attendance_ai, "ENTRANCE_MAX_BACKOFF_SECONDS", 0.01)
    monkeypatch.setattr(attendance_ai, "ENTRANCE_ERROR_PAUSE_SECONDS", 0.01)
    yield
    await attendance_ai.stop_entrance_watchers()
    recognition_stats.reset_for_tests()


def _camera(camera_id: str = "cam-1", **changes):
    fields = dict(
        id=camera_id, name="Kirish-1", ip="10.0.0.1", port=554, rtsp_path=None, rtsp_username=None,
        rtsp_password=None, is_entrance=True, is_exit=True, is_perimeter=False, excluded_module_codes=None,
        building_id=None,
    )
    fields.update(changes)
    return SimpleNamespace(**fields)


def _context():
    return attendance_ai._EntranceContext(
        session_factory=TestSessionLocal,
        candidates=CandidateMatrix(ids=["p1"], matrix=np.array([[1.0, 0.0]])),
        staff_active=True, student_active=False, off_hours_active=False,
    )


async def _settle(rounds: int = 20) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


class TestWatcher:
    async def test_every_new_frame_is_analysed_exactly_once(self, monkeypatch):
        frames = [(b"a", 1), (b"b", 2), (b"c", 3)]
        asked_after: list[int | None] = []
        analysed: list[bytes] = []
        blocked = asyncio.Event()
        exhausted = asyncio.Event()

        async def fake_grab(camera, *, wait_seconds, after_seq):
            asked_after.append(after_seq)
            if frames:
                return frames.pop(0)
            exhausted.set()
            await blocked.wait()  # yangi kadr hali kelmagan

        async def fake_analyse(camera, frame, context, **_options):
            analysed.append(frame)
            return 1

        monkeypatch.setattr(attendance_ai, "grab_newer_frame", fake_grab)
        monkeypatch.setattr(attendance_ai, "_analyse_entrance_frame", fake_analyse)
        monkeypatch.setattr(attendance_ai, "_entrance_context", _context())
        watcher = attendance_ai._EntranceWatcher(signature=())
        task = asyncio.create_task(attendance_ai._watch_entrance_camera(_camera(), watcher))
        await asyncio.wait_for(exhausted.wait(), timeout=2)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        assert analysed == [b"a", b"b", b"c"]
        # Har so'rov oldingi kadrdan KEYINGISINI so'raydi — bir kadr ikki marta emas.
        assert asked_after == [None, 1, 2, 3]
        assert watcher.matched == 3
        assert recognition_stats.export_snapshot()["cam-1"]["cycles"] == 3

    async def test_a_silent_stream_is_retried_from_scratch(self, monkeypatch):
        """Yangi kadr kelmasa, bir necha urinishdan keyin "yangidan" so'raladi —
        asosiy oqim o'lgan bo'lsa zaxira substream'ga o'tish shu yerda yuz beradi."""
        answers = [(b"a", 7), None, None, (b"b", 9)]
        asked_after: list[int | None] = []
        done = asyncio.Event()

        async def fake_grab(camera, *, wait_seconds, after_seq):
            asked_after.append(after_seq)
            if answers:
                return answers.pop(0)
            done.set()
            await asyncio.Event().wait()

        async def fake_analyse(camera, frame, context, **_options):
            return 0

        monkeypatch.setattr(attendance_ai, "grab_newer_frame", fake_grab)
        monkeypatch.setattr(attendance_ai, "_analyse_entrance_frame", fake_analyse)
        monkeypatch.setattr(attendance_ai, "_entrance_context", _context())
        task = asyncio.create_task(attendance_ai._watch_entrance_camera(_camera(), attendance_ai._EntranceWatcher(())))
        await asyncio.wait_for(done.wait(), timeout=2)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        assert asked_after == [None, 7, 7, None, 9]

    async def test_a_failing_frame_does_not_stop_the_watcher(self, monkeypatch):
        frames = [(b"bad", 1), (b"good", 2)]
        analysed: list[bytes] = []
        done = asyncio.Event()

        async def fake_grab(camera, *, wait_seconds, after_seq):
            if frames:
                return frames.pop(0)
            done.set()
            await asyncio.Event().wait()

        async def fake_analyse(camera, frame, context, **_options):
            if frame == b"bad":
                raise RuntimeError("baza bir lahza javob bermadi")
            analysed.append(frame)
            return 1

        monkeypatch.setattr(attendance_ai, "grab_newer_frame", fake_grab)
        monkeypatch.setattr(attendance_ai, "_analyse_entrance_frame", fake_analyse)
        monkeypatch.setattr(attendance_ai, "_entrance_context", _context())
        task = asyncio.create_task(attendance_ai._watch_entrance_camera(_camera(), attendance_ai._EntranceWatcher(())))
        await asyncio.wait_for(done.wait(), timeout=2)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        assert analysed == [b"good"]


class TestReconcile:
    async def test_watchers_follow_the_camera_list(self):
        started: list[str] = []
        stop_forever = asyncio.Event()

        async def start(camera, watcher):
            started.append(f"{camera.id}:{camera.ip}")
            await stop_forever.wait()

        attendance_ai._reconcile_entrance_watchers([_camera("a"), _camera("b")], start)
        await _settle()
        assert sorted(started) == ["a:10.0.0.1", "b:10.0.0.1"]

        # O'zgarishsiz dispetcher — hech kim qayta boshlanmaydi.
        attendance_ai._reconcile_entrance_watchers([_camera("a"), _camera("b")], start)
        await _settle()
        assert len(started) == 2

        # "b" ro'yxatdan chiqdi, "a" ning IP si o'zgardi.
        attendance_ai._reconcile_entrance_watchers([_camera("a", ip="10.0.0.9")], start)
        await _settle()
        assert started[-1] == "a:10.0.0.9"
        assert set(attendance_ai._entrance_watchers) == {"a"}
        assert attendance_ai.entrance_watcher_count() == 1

    async def test_a_stuck_watcher_is_restarted(self, monkeypatch):
        """17.09 da AI 18 soat jim turgan: vazifa tirik, lekin qadam qo'ymaydi."""
        from app.config import settings

        runs = {"n": 0}

        async def start(camera, watcher):
            runs["n"] += 1
            await asyncio.Event().wait()  # hech qachon qadam qo'ymaydi

        attendance_ai._reconcile_entrance_watchers([_camera("a")], start)
        await _settle()
        monkeypatch.setattr(settings, "entrance_watcher_stall_seconds", -1)
        attendance_ai._reconcile_entrance_watchers([_camera("a")], start)
        await _settle()
        assert runs["n"] == 2
        assert attendance_ai.entrance_watcher_count() == 1

    async def test_a_crashed_watcher_is_restarted_and_matches_are_collected(self):
        runs = {"n": 0}

        async def start(camera, watcher):
            runs["n"] += 1
            watcher.matched += 2
            if runs["n"] == 1:
                raise RuntimeError("kutilmagan xato")
            await asyncio.Event().wait()

        attendance_ai._reconcile_entrance_watchers([_camera("a")], start)
        await _settle()
        assert attendance_ai._reconcile_entrance_watchers([_camera("a")], start) == 2  # yiqilgan, qayta boshlandi
        await _settle()
        assert runs["n"] == 2
        assert attendance_ai._reconcile_entrance_watchers([_camera("a")], start) == 2
        assert attendance_ai._reconcile_entrance_watchers([_camera("a")], start) == 0


@pytest.mark.usefixtures("seeded")
class TestDispatch:
    @pytest.fixture
    async def entrance(self, db_session):
        building = (await db_session.execute(select(Building))).scalars().first()
        camera = Camera(name="Asosiy kirish", ip="10.0.7.1", building_id=building.id, zone="Kirish",
                        resolution="1080p", status="faol", is_entrance=True, is_exit=True,
                        stream_url="/s0/cam-x/index.m3u8", last_seen_at=local_now())
        db_session.add(camera)
        await db_session.commit()
        return camera

    @pytest.fixture(autouse=True)
    def _no_real_streams(self, monkeypatch):
        async def idle(camera, *, wait_seconds, after_seq):
            await asyncio.Event().wait()

        monkeypatch.setattr(attendance_ai, "grab_newer_frame", idle)
        monkeypatch.setattr(
            attendance_ai,
            "load_candidate_matrix_for_sweep",
            lambda db: _async(CandidateMatrix(ids=["p1"], matrix=np.array([[1.0, 0.0]]))),
        )

    async def test_dispatch_starts_and_stops_watchers(self, db_session, entrance):
        await attendance_ai.run_entrance_exit_attendance_dispatch_once(session_factory=TestSessionLocal)
        await _settle()
        assert attendance_ai.entrance_watcher_count() == 1

        entrance.status = "nofaol"
        await db_session.commit()
        await attendance_ai.run_entrance_exit_attendance_dispatch_once(session_factory=TestSessionLocal)
        await _settle()
        assert attendance_ai.entrance_watcher_count() == 0

    async def test_switching_attendance_off_stops_every_watcher(self, db_session, entrance):
        await attendance_ai.run_entrance_exit_attendance_dispatch_once(session_factory=TestSessionLocal)
        await _settle()
        modules = (await db_session.execute(select(AIModuleConfig).where(AIModuleConfig.code.in_([6, 7])))).scalars()
        for module in modules:
            module.active = False
        await db_session.commit()

        await attendance_ai.run_entrance_exit_attendance_dispatch_once(session_factory=TestSessionLocal)
        await _settle()

        assert attendance_ai.entrance_watcher_count() == 0
        assert attendance_ai._entrance_context is None


async def _async(value):
    return value


class TestWhichStreamIsInUse:
    @pytest.fixture(autouse=True)
    def _main_stream_for_entrances(self, monkeypatch):
        from app.config import settings
        from app.services import frame_grabber

        monkeypatch.setattr(settings, "ai_use_direct_rtsp", True)
        monkeypatch.setattr(settings, "ai_entrance_use_main_stream", True)
        frame_grabber.reset_main_stream_fallbacks_for_tests()
        yield
        frame_grabber.reset_main_stream_fallbacks_for_tests()

    def test_labels_follow_the_fallback(self):
        from app.services import frame_grabber

        entrance, room = _camera("e"), _camera("r", name="2-xona", is_entrance=False, is_exit=False)
        assert frame_grabber.stream_label(entrance) == "asosiy"
        assert frame_grabber.stream_label(room) == "substream"

        frame_grabber._note_main_stream_result(entrance, ok=False)
        assert frame_grabber.stream_label(entrance) == "substream (zaxira)"

    def test_the_diagnosis_names_the_fallback(self):
        from app.routers.presence import _diagnose

        recognition_stats.record_frame("e", [], [])
        recognition_stats.record_cycle("e", total_seconds=4.0, grab_seconds=3.9, stream="substream (zaxira)")
        view = recognition_stats.local_views()["e"]

        assert view.stream == "substream (zaxira)"
        assert "substream" in _diagnose(True, True, view, recognized=3, enrolled=100)


class TestWatcherSavesCpu:
    async def test_frames_without_motion_are_not_analysed(self, monkeypatch):
        """Bo'sh eshik kadri yuz tahliliga bormaydi (app/services/motion_gate.py)."""
        frames = [(b"a", 1), (b"b", 2), (b"c", 3)]
        analysed: list[bytes] = []
        verdicts = iter([True, False, True])
        done = asyncio.Event()

        async def fake_grab(camera, *, wait_seconds, after_seq):
            if frames:
                return frames.pop(0)
            done.set()
            await asyncio.Event().wait()

        async def fake_analyse(camera, frame, context, **_options):
            analysed.append(frame)
            return 0

        monkeypatch.setattr(attendance_ai, "grab_newer_frame", fake_grab)
        monkeypatch.setattr(attendance_ai, "_analyse_entrance_frame", fake_analyse)
        monkeypatch.setattr(attendance_ai, "_entrance_context", _context())
        monkeypatch.setattr(attendance_ai.MotionGate, "should_analyse", lambda self, frame, roi=None: next(verdicts))
        task = asyncio.create_task(attendance_ai._watch_entrance_camera(_camera(), attendance_ai._EntranceWatcher(())))
        await asyncio.wait_for(done.wait(), timeout=2)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        assert analysed == [b"a", b"c"]
        assert recognition_stats.export_snapshot()["cam-1"]["motion_skipped"] == 1

    async def test_identified_faces_are_skipped_in_the_next_frame(self, monkeypatch):
        frames = [(b"a", 1), (b"b", 2)]
        seen_skip: list[tuple] = []
        done = asyncio.Event()

        async def fake_grab(camera, *, wait_seconds, after_seq):
            if frames:
                return frames.pop(0)
            done.set()
            await asyncio.Event().wait()

        async def fake_analyse(camera, frame, context, *, skip_boxes=(), identified_boxes=None, **_options):
            seen_skip.append(skip_boxes)
            identified_boxes.append((10.0, 10.0, 50.0, 60.0))
            return 1

        monkeypatch.setattr(attendance_ai, "grab_newer_frame", fake_grab)
        monkeypatch.setattr(attendance_ai, "_analyse_entrance_frame", fake_analyse)
        monkeypatch.setattr(attendance_ai, "_entrance_context", _context())
        task = asyncio.create_task(attendance_ai._watch_entrance_camera(_camera(), attendance_ai._EntranceWatcher(())))
        await asyncio.wait_for(done.wait(), timeout=2)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        assert seen_skip == [(), ((10.0, 10.0, 50.0, 60.0),)]


class TestRealTime:
    """Operator ochgan kamera va kutayotgan kameradagi harakat (2026-09-24):
    ilgari kutish 150 s gacha cho'zilardi, skaner esa 5-12 s kechikardi."""

    @pytest.fixture(autouse=True)
    def _fast(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "pacing_enabled", True)
        monkeypatch.setattr(settings, "pacing_idle_after", 0)
        monkeypatch.setattr(settings, "pacing_idle_base_seconds", 60.0)
        monkeypatch.setattr(settings, "pacing_motion_min_seconds", 0.0)
        monkeypatch.setattr(settings, "room_watcher_start_delay_seconds", 0.0)
        monkeypatch.setattr(settings, "room_watcher_start_spread_seconds", 0.0)
        monkeypatch.setattr(attendance_ai, "main_stream_source", lambda camera: None)
        monkeypatch.setattr(attendance_ai.MotionGate, "should_analyse", lambda self, frame, roi=None: True)

    async def _run(self, monkeypatch, camera, frames, *, analyse=None, until: int):
        analysed: list[bytes] = []
        done = asyncio.Event()

        async def fake_grab(camera, *, wait_seconds, after_seq):
            if frames:
                return frames.pop(0)
            await asyncio.Event().wait()

        async def fake_analyse(camera, frame, context, *, overlay_out=None, **_options):
            analysed.append(frame)
            if analyse is not None:
                analyse(overlay_out)
            if len(analysed) >= until:
                done.set()
            return 0

        monkeypatch.setattr(attendance_ai, "grab_newer_frame", fake_grab)
        monkeypatch.setattr(attendance_ai, "_analyse_entrance_frame", fake_analyse)
        monkeypatch.setattr(attendance_ai, "_entrance_context", _context())
        task = asyncio.create_task(attendance_ai._watch_entrance_camera(camera, attendance_ai._EntranceWatcher(())))
        try:
            await asyncio.wait_for(done.wait(), timeout=4)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return analysed

    async def test_a_watched_camera_never_waits_and_feeds_the_scanner(self, monkeypatch):
        from app.services import live_focus

        room = _camera("room-1", name="1-xona", is_entrance=False, is_exit=False)
        await live_focus.mark_focus("room-1")
        monkeypatch.setattr(attendance_ai, "jpeg_dimensions", lambda _frame: (1280, 720))

        def add_face(overlay_out):
            overlay_out.append({"bbox": [1.0, 2.0, 30.0, 40.0], "status": "notanish", "similarity": 0.3})

        analysed = await self._run(monkeypatch, room, [(b"a", 1), (b"b", 2), (b"c", 3)], analyse=add_face, until=3)
        assert analysed == [b"a", b"b", b"c"]  # yaroqli yuz yo'q, lekin kutmadi
        payload = await live_focus.latest_result("room-1", max_age_seconds=5)
        assert payload["frame_width"] == 1280
        assert payload["faces"][0]["status"] == "notanish"

    async def test_motion_wakes_an_idle_camera(self, monkeypatch):
        room = _camera("room-2", name="2-xona", is_entrance=False, is_exit=False)
        monkeypatch.setattr(attendance_ai, "_useful_face_total", lambda key: 1)  # kamera "hosildor"
        monkeypatch.setattr(attendance_ai, "camera_video_source", lambda camera: "src")
        monkeypatch.setattr(attendance_ai, "peek_cached_frame", lambda source: b"peek")
        moves = iter([False, True])
        monkeypatch.setattr(attendance_ai.MotionGate, "moved_since_peek", lambda self, frame, roi=None: next(moves, True))
        analysed = await self._run(monkeypatch, room, [(b"a", 1), (b"b", 2)], until=2)
        # 60 s kutish o'rniga ~2 s da uyg'ondi (timeout=4 s).
        assert analysed == [b"a", b"b"]


def _ids():
    import itertools

    counter = itertools.count(100)  # oldingi izlar raqamidan keyin (kuzatuvchida bitta hisoblagich)
    return lambda: next(counter)


def test_tracked_faces_keep_their_name_on_the_scanner():
    previous = [{"bbox": [10.0, 10.0, 50.0, 60.0], "status": "tanildi", "person_id": "p1", "person_name": "Ali", "similarity": 0.6, "track_id": 7, "named_at": 100.0}]
    entries = [
        {"bbox": [11.0, 11.0, 51.0, 61.0], "status": "kuzatuvda"},
        {"bbox": [200.0, 10.0, 240.0, 60.0], "status": "notanish", "similarity": 0.2},
    ]
    attendance_ai._link_tracks(entries, previous, _ids(), now=101.0)
    assert entries[0]["status"] == "tanildi" and entries[0]["person_name"] == "Ali" and entries[0]["track_id"] == 7
    assert entries[1]["status"] == "notanish" and entries[1]["track_id"] not in (None, 7)


def test_a_walking_person_keeps_the_same_track_even_without_overlap():
    """1 s da odam yuzining kengligicha siljiydi — IoU 0, lekin iz o'sha."""
    previous = [{"bbox": [100.0, 100.0, 140.0, 150.0], "status": "notanish", "track_id": 3}]
    entries = [{"bbox": [140.0, 102.0, 180.0, 152.0], "status": "notanish"}]
    attendance_ai._link_tracks(entries, previous, _ids(), now=1.0)
    assert entries[0]["track_id"] == 3


def test_a_turned_face_keeps_its_name_only_for_a_while():
    previous = [{"bbox": [0.0, 0.0, 40.0, 50.0], "status": "tanildi", "person_id": "p1", "person_name": "Ali", "track_id": 1, "named_at": 100.0}]
    soon = [{"bbox": [2.0, 0.0, 42.0, 50.0], "status": "notanish"}]
    attendance_ai._link_tracks(soon, previous, _ids(), now=104.0)
    assert soon[0]["person_name"] == "Ali"
    late = [{"bbox": [2.0, 0.0, 42.0, 50.0], "status": "notanish"}]
    attendance_ai._link_tracks(late, previous, _ids(), now=100.0 + attendance_ai.STICKY_NAME_SECONDS + 1)
    assert late[0]["status"] == "notanish" and late[0].get("person_name") is None


def test_someone_else_recognised_does_not_inherit_the_track():
    previous = [{"bbox": [0.0, 0.0, 40.0, 50.0], "status": "tanildi", "person_id": "p1", "person_name": "Ali", "track_id": 1, "named_at": 100.0}]
    entries = [{"bbox": [5.0, 0.0, 45.0, 50.0], "status": "tanildi", "person_id": "p2", "person_name": "Vali"}]
    attendance_ai._link_tracks(entries, previous, _ids(), now=101.0)
    assert entries[0]["track_id"] != 1 and entries[0]["person_name"] == "Vali"


def test_boxes_outside_the_motion_region_are_kept():
    previous = [{"bbox": [10.0, 10.0, 50.0, 60.0], "track_id": 1}, {"bbox": [900.0, 10.0, 950.0, 60.0], "track_id": 2}]
    kept = attendance_ai._outside_region(previous, (0.5, 0.0, 1.0, 1.0), (1280, 720))
    assert [entry["track_id"] for entry in kept] == [1]


def test_overlay_marks_only_accepted_matches_as_known():
    known = SimpleNamespace(bbox=np.array([0, 0, 50, 60]), embedding=np.ones(2), tracked=False, landmarks_68=None)
    stranger = SimpleNamespace(bbox=np.array([60, 0, 110, 60]), embedding=np.ones(2), tracked=False, landmarks_68=None)
    tiny = SimpleNamespace(bbox=np.array([0, 0, 8, 8]), embedding=None, tracked=False, landmarks_68=None)
    graded = [SimpleNamespace(similarity=0.62), SimpleNamespace(similarity=0.44)]
    entries = attendance_ai._overlay_entries([known, stranger, tiny], [known, stranger], graded, {id(known): "p1"})
    assert [e["status"] for e in entries] == ["tanildi", "notanish", "kichik"]
    assert entries[0]["person_id"] == "p1" and entries[1]["similarity"] == 0.44


def test_diagnosis_flags_a_camera_that_misses_most_faces():
    from types import SimpleNamespace

    from app.routers.presence import _diagnose

    base = dict(frames=100, stream="asosiy", strict=5, relaxed_confirmed=0, face_px_median=24)
    mostly_small = SimpleNamespace(**base, faces=200, small_faces=180)
    assert "90%" in _diagnose(True, True, mostly_small, recognized=5, enrolled=100)
    fine = SimpleNamespace(**base, faces=200, small_faces=40)
    assert _diagnose(True, True, fine, recognized=5, enrolled=100) is None
    few = SimpleNamespace(**base, faces=10, small_faces=10)
    assert _diagnose(True, True, few, recognized=5, enrolled=100) is None

