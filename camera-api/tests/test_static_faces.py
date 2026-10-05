"""Devordagi rasmni ("statik yuz") tirik odamdan ajratish —
app/services/static_faces.py va uning app/jobs/attendance_ai.py dagi ulanishi.

Model chaqirilmaydi: yuzlar soxta (bbox + embedding), vaqt esa har doim
ANIQ beriladi (now=...) — chegaralar soatlar bilan o'lchanadi, test esa
soat kutib o'tira olmaydi.
"""

import io
import json
import time
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import select

from app.config import settings
from app.jobs import attendance_ai
from app.models import Building, Camera, Faculty, StudentStaff
from app.services import recognition_stats
from app.services.static_faces import StaticFaceStore, static_face_store


def _face(height: float, *, top: float = 0.0, left: float = 0.0, embedding=None, tracked: bool = False):
    return SimpleNamespace(
        bbox=np.array([left, top, left + height, top + height], dtype=np.float32),
        embedding=embedding,
        tracked=tracked,
        det_score=0.9,
        yaw=0.0,
        sharpness=100.0,
    )


def _jpeg(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (40, 40, 40)).save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def quick_static(monkeypatch):
    """Chegaralar test o'lchamida: 5 ta ko'rinish, 100 soniya oralig'i."""
    monkeypatch.setattr(settings, "static_face_skip_enabled", True)
    monkeypatch.setattr(settings, "static_face_iou", 0.9)
    monkeypatch.setattr(settings, "static_face_min_hits", 5)
    monkeypatch.setattr(settings, "static_face_min_span_seconds", 100)
    monkeypatch.setattr(settings, "static_face_min_gap_seconds", 10)
    monkeypatch.setattr(settings, "static_face_expire_seconds", 1000)
    monkeypatch.setattr(settings, "static_face_person_memory_seconds", 5000)
    monkeypatch.setattr(settings, "static_face_max_boxes_per_camera", 4)
    monkeypatch.setattr(settings, "static_face_max_cameras", 3)


def _promote(store: StaticFaceStore, camera: str, face, *, base: float = 0.0, steps: int = 5, step: float = 25.0):
    """Bir ramkani chegaragacha ko'rsatadi; oxirgi chaqiruv natijasini qaytaradi."""
    promoted = []
    for i in range(steps):
        promoted = store.observe(camera, [face], now=base + i * step)
    return promoted


# ── Statikka o'tish ────────────────────────────────────────────────────────


class TestPromotion:
    def test_box_seen_long_enough_becomes_static(self, quick_static):
        store = StaticFaceStore()
        poster = _face(30, top=100, left=200)

        promoted = _promote(store, "cam", poster)

        assert len(promoted) == 1
        assert promoted[0].hits == 5
        assert promoted[0].span_seconds == 100
        assert store.static_boxes("cam", now=110.0) == ((200.0, 100.0, 230.0, 130.0),)
        assert store.static_heights("cam") == [30]

    def test_promotion_is_reported_once(self, quick_static):
        store = StaticFaceStore()
        poster = _face(30, top=100, left=200)
        _promote(store, "cam", poster)
        # Chegaradan keyingi ko'rinishlar yangi xabar bermaydi (log bir marta).
        assert store.observe("cam", [poster], now=200.0) == []

    def test_few_sightings_are_not_enough_even_over_a_long_span(self, quick_static):
        """Kun bo'yi bir necha marta o'tib ketgan odam rasm emas."""
        store = StaticFaceStore()
        face = _face(30, top=100, left=200)
        assert _promote(store, "cam", face, steps=3, step=500.0) == []
        assert store.static_boxes("cam", now=1000.0) == ()

    def test_many_sightings_in_a_short_span_are_not_enough(self, quick_static):
        """Oraliq shart: qisqa vaqtda qimirlamay turgan odam hali rasm emas."""
        store = StaticFaceStore()
        face = _face(30, top=100, left=200)
        assert _promote(store, "cam", face, steps=6, step=11.0) == []  # 55 s < 100 s
        assert store.static_boxes("cam", now=60.0) == ()

    def test_a_face_that_moves_never_accumulates(self, quick_static):
        """Har safar biroz siljigan yuz — bitta ramka emas (IoU 0.9 dan past)."""
        store = StaticFaceStore()
        for i in range(8):
            store.observe("cam", [_face(30, top=100 + i * 12, left=200)], now=i * 25.0)
        assert store.static_boxes("cam", now=200.0) == ()

    def test_sightings_closer_than_the_gap_are_not_counted_twice(self, quick_static):
        """Sekundiga bir kadr o'qiydigan kuzatuvchi sanoqni to'ldirmaydi."""
        store = StaticFaceStore()
        face = _face(30, top=100, left=200)
        for i in range(40):
            store.observe("cam", [face], now=i * 1.0)  # 40 kadr, 39 soniya
        assert store.static_boxes("cam", now=40.0) == ()

    def test_disabled_flag_learns_nothing(self, quick_static, monkeypatch):
        monkeypatch.setattr(settings, "static_face_skip_enabled", False)
        store = StaticFaceStore()
        assert _promote(store, "cam", _face(30, top=100, left=200)) == []
        assert store.static_boxes("cam", now=110.0) == ()


# ── Tirik odamni qamab qo'ymaslik ──────────────────────────────────────────


class TestPersonIsNeverStatic:
    def test_a_matched_position_cannot_become_static(self, quick_static):
        """Darsda qimirlamay o'tirgan odam bir marta tanilsa — u rasm emas."""
        store = StaticFaceStore()
        person = _face(30, top=100, left=200)
        for i in range(5):
            store.observe("cam", [person], now=i * 25.0)
            if i == 1:
                store.note_matched("cam", [person.bbox], now=i * 25.0)
        assert store.static_boxes("cam", now=200.0) == ()

    def test_a_match_forgets_an_already_static_box(self, quick_static):
        """Ehtiyot chorasi: agar statik ramkada baribir odam tanilsa
        (plakat olib tashlandi, o'rniga odam turdi) — ramka o'chadi."""
        store = StaticFaceStore()
        face = _face(30, top=100, left=200)
        _promote(store, "cam", face)
        assert store.static_boxes("cam", now=110.0)

        store.note_matched("cam", [face.bbox], now=110.0)
        assert store.static_boxes("cam", now=110.0) == ()

    def test_the_ban_wears_off_with_time(self, quick_static):
        store = StaticFaceStore()
        face = _face(30, top=100, left=200)
        store.note_matched("cam", [face.bbox], now=0.0)
        # Taqiq amalda: 5000 s ichida o'rganilmaydi.
        assert _promote(store, "cam", face, base=100.0) == []
        # Taqiq tugagach odatdagidek o'rganiladi.
        assert len(_promote(store, "cam", face, base=6000.0)) == 1

    def test_a_match_elsewhere_does_not_free_the_poster(self, quick_static):
        store = StaticFaceStore()
        poster = _face(30, top=100, left=200)
        walker = _face(60, top=400, left=800)
        for i in range(5):
            store.note_matched("cam", [walker.bbox], now=i * 25.0)
            promoted = store.observe("cam", [poster], now=i * 25.0)
        assert len(promoted) == 1


# ── Eskirish va xotira chegarasi ───────────────────────────────────────────


class TestExpiryAndBounds:
    def test_a_box_that_stops_appearing_expires(self, quick_static):
        store = StaticFaceStore()
        face = _face(30, top=100, left=200)
        _promote(store, "cam", face)

        assert store.static_boxes("cam", now=1050.0) == ((200.0, 100.0, 230.0, 130.0),)  # 950 s < 1000 s
        assert store.static_boxes("cam", now=1200.0) == ()  # 1100 s > 1000 s
        assert store.static_heights("cam") == []

    def test_being_seen_keeps_a_static_box_alive(self, quick_static):
        store = StaticFaceStore()
        face = _face(30, top=100, left=200)
        _promote(store, "cam", face)
        fresh, skipped = store.split("cam", [face], now=900.0)
        assert fresh == [] and skipped == [face]
        assert store.static_boxes("cam", now=1500.0) != ()

    def test_boxes_per_camera_are_bounded(self, quick_static):
        store = StaticFaceStore()
        for i in range(20):
            store.observe("cam", [_face(30, top=100 + i * 100, left=200)], now=i * 25.0)
        assert store.static_boxes("cam", now=500.0) == ()
        assert len(store.static_heights("cam")) == 0
        # Ichki ro'yxat ham chegara ichida (nomzodlar bilan birga).
        assert len(store._cameras["cam"].boxes) <= settings.static_face_max_boxes_per_camera

    def test_a_static_box_is_not_evicted_by_new_candidates(self, quick_static):
        store = StaticFaceStore()
        poster = _face(30, top=100, left=200)
        _promote(store, "cam", poster)
        for i in range(20):
            store.observe("cam", [_face(30, top=1000 + i * 100, left=200)], now=200.0 + i * 25.0)
        assert store.static_boxes("cam", now=800.0) == ((200.0, 100.0, 230.0, 130.0),)

    def test_camera_count_is_bounded(self, quick_static):
        store = StaticFaceStore()
        for i in range(10):
            store.note_matched(f"cam-{i}", [_face(30).bbox], now=float(i))
        assert store.camera_count() == settings.static_face_max_cameras

    def test_matched_positions_are_bounded(self, quick_static):
        store = StaticFaceStore()
        for i in range(20):
            store.note_matched("cam", [_face(30, top=i * 100).bbox], now=float(i))
        assert len(store._cameras["cam"].people) <= settings.static_face_max_boxes_per_camera


# ── Ajratish ───────────────────────────────────────────────────────────────


class TestSplit:
    def test_only_static_boxes_are_skipped(self, quick_static):
        store = StaticFaceStore()
        poster = _face(30, top=100, left=200)
        person = _face(60, top=400, left=800)
        _promote(store, "cam", poster)

        fresh, skipped = store.split("cam", [poster, person], now=120.0)
        assert fresh == [person]
        assert skipped == [poster]

    def test_unknown_camera_passes_everything_through(self, quick_static):
        store = StaticFaceStore()
        faces = [_face(30)]
        assert store.split("yangi-kamera", faces, now=1.0) == (faces, [])


# ── Davomat quvuriga ulanish ───────────────────────────────────────────────


@pytest.fixture
async def static_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Stend kamerasi", ip="10.0.9.77", building_id=building.id, zone="Yo'lak",
        resolution="4K", status="faol",
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera, attribute_names=["building"])
    return camera


async def _enrolled_person(db_session, embedding) -> StudentStaff:
    faculty = (await db_session.execute(select(Faculty))).scalars().first()
    person = StudentStaff(
        full_name="Stenddagi Xodim", type="xodim", faculty_id=faculty.id, group_or_position="1",
        biometric_embedding=json.dumps(list(embedding)),
    )
    db_session.add(person)
    await db_session.commit()
    return person


@pytest.fixture
def zoom_ready(monkeypatch):
    monkeypatch.setattr(settings, "face_zoom_enabled", True)
    monkeypatch.setattr(settings, "face_zoom_min_px", 10)
    monkeypatch.setattr(settings, "face_zoom_max_px", 45)
    monkeypatch.setattr(settings, "face_zoom_max_faces", 4)
    monkeypatch.setattr(settings, "face_zoom_interval_seconds", 60)
    monkeypatch.setattr(settings, "face_zoom_max_concurrent_cameras", 2)
    monkeypatch.setattr(settings, "face_analysis_min_px", 40)
    monkeypatch.setattr(settings, "attendance_min_face_px", 40)
    monkeypatch.setattr(attendance_ai, "ai_prefers_substream", lambda camera: True)


class TestAttendancePipeline:
    async def test_a_static_face_never_triggers_the_4k_zoom(
        self, db_session, static_camera, quick_static, zoom_ready, monkeypatch
    ):
        """Aynan shu narsa uchun qilingan: 22 pikselli plakat yuzi har
        tekshiruvda 4K kadr so'rardi."""
        await _enrolled_person(db_session, np.array([1.0] + [0.0] * 511))
        calls: dict = {}

        async def fake_grab(camera, **kwargs):
            calls.setdefault("grabs", []).append(str(camera.id))
            return _jpeg(64, 36)

        monkeypatch.setattr(attendance_ai, "grab_main_stream_frame_once", fake_grab)

        camera_key = str(static_camera.id)
        base = time.monotonic()
        poster = _face(22, top=350, left=630)
        # Chegaragacha: bu kadrlarda zoom ishlaydi (hali rasm ekani noma'lum).
        for i in range(5):
            static_face_store.observe(camera_key, [poster], now=base + i * 25.0)
        assert static_face_store.static_boxes(camera_key) != ()

        calls.clear()
        records = await attendance_ai.process_camera_frame(
            _jpeg(1280, 720), db_session, static_camera, faces=[poster]
        )

        assert records == []
        assert "grabs" not in calls
        stats = recognition_stats.snapshot(camera_key)
        assert stats.static_faces == 1
        assert stats.static_boxes == 1
        assert stats.static_px_median == 22
        # Yuz "jimgina yo'qolmadi": u odatdagi yuz sifatida sanalmaydi.
        assert stats.faces == 0

    async def test_a_static_box_is_not_embedded(
        self, db_session, static_camera, quick_static, zoom_ready, monkeypatch
    ):
        """Statik ramka detect_faces ga `skip_boxes` bo'lib boradi — ArcFace
        umuman chaqirilmaydi."""
        calls: dict = {}

        async def fake_detect(frame, *, priority=None, roi=None, skip_boxes=(), **kwargs):
            calls["skip_boxes"] = tuple(tuple(float(v) for v in box[:4]) for box in skip_boxes)
            return []

        monkeypatch.setattr(attendance_ai, "detect_faces", fake_detect)

        camera_key = str(static_camera.id)
        base = time.monotonic()
        poster = _face(22, top=350, left=630)
        for i in range(5):
            static_face_store.observe(camera_key, [poster], now=base + i * 25.0)

        await attendance_ai.process_camera_frame(_jpeg(1280, 720), db_session, static_camera)
        assert calls["skip_boxes"] == ((630.0, 350.0, 652.0, 372.0),)

    async def test_a_matched_face_is_remembered_as_a_person(
        self, db_session, static_camera, quick_static, zoom_ready, monkeypatch
    ):
        """Tanilgan yuz o'sha joyda hech qachon statik bo'lmaydi."""
        embedding = np.array([1.0] + [0.0] * 511)
        await _enrolled_person(db_session, embedding)
        monkeypatch.setattr(attendance_ai, "grab_main_stream_frame_once", lambda *a, **k: None)

        sitter = _face(90, top=100, left=200, embedding=embedding)
        for _ in range(8):
            await attendance_ai.process_camera_frame(
                _jpeg(1280, 720), db_session, static_camera, faces=[sitter]
            )
        camera_key = str(static_camera.id)
        assert static_face_store.static_boxes(camera_key) == ()
        assert recognition_stats.snapshot(camera_key).static_faces == 0
