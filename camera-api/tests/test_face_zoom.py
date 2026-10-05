"""Kichik yuzni asosiy oqimdan yaqinlashtirib tanish — app/services/face_zoom.py
va uning app/jobs/attendance_ai.py dagi ulanishi.

Model chaqirilmaydi: detect_faces va asosiy oqimdan kadr olish
soxtalashtiriladi (boshqa yuz testlari kabi) — tekshirilayotgani mantiq:
qaysi o'lcham zoomni ishga tushiradi, hudud qanday hisoblanadi va qisiladi,
oraliq va bir vaqtdagi kameralar chegarasi, va zoomdagi moslik odatdagi
moslik bilan BIR XIL davomat yozuvini berishi.
"""

import io
import json
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import select

from app.config import settings
from app.jobs import attendance_ai
from app.models import AttendanceRecord, Building, Camera, Faculty, StudentStaff
from app.services import face_zoom, recognition_stats
from app.services.face_zoom import ZoomLimiter, merge_zoom_faces, roi_for_box, zoom_candidate_boxes


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


# ── Qaysi yuz zoomga nomzod ────────────────────────────────────────────────


class TestCandidateWindow:
    def test_only_faces_inside_the_window(self):
        faces = [_face(5), _face(12), _face(30), _face(60, embedding=np.ones(2))]
        boxes = zoom_candidate_boxes(faces, min_px=40, floor_px=10, max_faces=4)
        # 5 px — shovqin, 60 px — allaqachon tahlil qilingan (embedding bor).
        assert [box[3] - box[1] for box in boxes] == [30.0, 12.0]

    def test_boundaries_are_inclusive_below_and_exclusive_above(self):
        faces = [_face(10), _face(40), _face(39)]
        boxes = zoom_candidate_boxes(faces, min_px=40, floor_px=10, max_faces=4)
        assert [box[3] - box[1] for box in boxes] == [39.0, 10.0]

    def test_tracked_and_already_matched_faces_are_skipped(self):
        """Vektori hisoblangan, lekin hech kimga mos kelmagan yuz — nomzod;
        tanilgani (matched) va oldingi kadrdan kuzatilgani — yo'q."""
        assert zoom_candidate_boxes([_face(20, tracked=True)], min_px=40, floor_px=10, max_faces=4) == []
        unmatched = _face(20, embedding=np.ones(2))
        assert zoom_candidate_boxes([unmatched], min_px=40, floor_px=10, max_faces=4) == [
            tuple(float(v) for v in unmatched.bbox[:4])
        ]
        assert zoom_candidate_boxes(
            [unmatched], min_px=40, floor_px=10, max_faces=4, matched=(unmatched.bbox,)
        ) == []

    def test_biggest_candidates_first_and_capped(self):
        faces = [_face(12), _face(35), _face(20), _face(28)]
        boxes = zoom_candidate_boxes(faces, min_px=40, floor_px=10, max_faces=2)
        assert [box[3] - box[1] for box in boxes] == [35.0, 28.0]

    def test_disabled_window_returns_nothing(self):
        faces = [_face(20)]
        assert zoom_candidate_boxes(faces, min_px=40, floor_px=0, max_faces=4) == []
        assert zoom_candidate_boxes(faces, min_px=40, floor_px=40, max_faces=4) == []
        assert zoom_candidate_boxes(faces, min_px=40, floor_px=10, max_faces=0) == []


# ── Hudud (ROI) hisobi ─────────────────────────────────────────────────────


class TestRoi:
    def test_box_is_expanded_around_its_centre(self):
        # 20 px li yuz kadr o'rtasida, 1280x720, 2.5 barobar -> 50 px.
        roi = roi_for_box((630.0, 350.0, 650.0, 370.0), 1280, 720, margin=2.5)
        assert roi == pytest.approx((615 / 1280, 335 / 720, 665 / 1280, 385 / 720))

    def test_clamped_to_the_frame(self):
        roi = roi_for_box((0.0, 0.0, 20.0, 20.0), 1280, 720, margin=2.5)
        assert roi[0] == 0.0 and roi[1] == 0.0
        assert 0.0 < roi[2] <= 1.0 and 0.0 < roi[3] <= 1.0

        roi = roi_for_box((1270.0, 710.0, 1280.0, 720.0), 1280, 720, margin=2.5)
        assert roi[2] == 1.0 and roi[3] == 1.0
        assert 0.0 <= roi[0] < 1.0 and 0.0 <= roi[1] < 1.0

    def test_never_returns_an_empty_region(self):
        roi = roi_for_box((-500.0, -500.0, -480.0, -480.0), 1280, 720, margin=2.5)
        assert roi[2] > roi[0] and roi[3] > roi[1]

    def test_margin_below_one_does_not_shrink_the_box(self):
        roi = roi_for_box((600.0, 300.0, 640.0, 340.0), 1280, 720, margin=0.5)
        assert roi == pytest.approx((600 / 1280, 300 / 720, 640 / 1280, 340 / 720))

    def test_unknown_frame_size_falls_back_to_the_whole_frame(self):
        assert roi_for_box((0.0, 0.0, 20.0, 20.0), 0, 0, margin=2.5) == (0.0, 0.0, 1.0, 1.0)


class TestMergeZoomFaces:
    def test_the_same_face_found_in_two_regions_is_kept_once(self):
        a, b = _face(60), _face(60, left=2, top=2)
        far = _face(60, left=500, top=500)
        merged = merge_zoom_faces([[a], [b, far]])
        assert merged == [a, far]


# ── Chegaralovchi ──────────────────────────────────────────────────────────


class TestZoomLimiter:
    def test_one_camera_waits_out_the_interval(self, monkeypatch):
        monkeypatch.setattr(settings, "face_zoom_interval_seconds", 60)
        monkeypatch.setattr(settings, "face_zoom_max_concurrent_cameras", 4)
        limiter = ZoomLimiter()

        assert limiter.acquire("cam", now=1000.0) is True
        limiter.release()
        assert limiter.acquire("cam", now=1030.0) is False
        assert limiter.acquire("cam", now=1060.0) is True
        limiter.release()

    def test_interval_is_per_camera(self, monkeypatch):
        monkeypatch.setattr(settings, "face_zoom_interval_seconds", 60)
        monkeypatch.setattr(settings, "face_zoom_max_concurrent_cameras", 4)
        limiter = ZoomLimiter()
        assert limiter.acquire("a", now=1000.0) is True
        assert limiter.acquire("b", now=1000.0) is True

    def test_concurrency_cap_blocks_the_third_camera(self, monkeypatch):
        monkeypatch.setattr(settings, "face_zoom_interval_seconds", 0)
        monkeypatch.setattr(settings, "face_zoom_max_concurrent_cameras", 2)
        limiter = ZoomLimiter()

        assert limiter.acquire("a", now=1.0) is True
        assert limiter.acquire("b", now=1.0) is True
        assert limiter.acquire("c", now=1.0) is False
        assert limiter.active == 2
        limiter.release()
        assert limiter.acquire("c", now=1.0) is True

    def test_slot_releases_even_on_error(self, monkeypatch):
        monkeypatch.setattr(settings, "face_zoom_interval_seconds", 0)
        monkeypatch.setattr(settings, "face_zoom_max_concurrent_cameras", 1)
        limiter = ZoomLimiter()
        with pytest.raises(RuntimeError):
            with limiter.slot("a") as allowed:
                assert allowed is True
                raise RuntimeError("tahlil xatosi")
        assert limiter.active == 0

    def test_blocked_slot_yields_false_and_holds_no_capacity(self, monkeypatch):
        monkeypatch.setattr(settings, "face_zoom_interval_seconds", 0)
        monkeypatch.setattr(settings, "face_zoom_max_concurrent_cameras", 0)
        limiter = ZoomLimiter()
        with limiter.slot("a") as allowed:
            assert allowed is False
        assert limiter.active == 0


# ── Davomat quvuriga ulanish ───────────────────────────────────────────────


@pytest.fixture
async def zoom_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Xona kamerasi", ip="10.0.9.44", building_id=building.id, zone="Xona",
        resolution="4K", status="faol",
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera, attribute_names=["building"])
    return camera


@pytest.fixture
def zoom_settings(monkeypatch):
    monkeypatch.setattr(settings, "face_zoom_enabled", True)
    monkeypatch.setattr(settings, "face_zoom_min_px", 10)
    monkeypatch.setattr(settings, "face_zoom_max_faces", 4)
    monkeypatch.setattr(settings, "face_zoom_interval_seconds", 60)
    monkeypatch.setattr(settings, "face_zoom_max_concurrent_cameras", 2)
    monkeypatch.setattr(settings, "face_analysis_min_px", 40)
    monkeypatch.setattr(settings, "attendance_min_face_px", 40)


async def _enrolled_person(db_session, embedding) -> StudentStaff:
    faculty = (await db_session.execute(select(Faculty))).scalars().first()
    person = StudentStaff(
        full_name="Uzoqdagi Talaba", type="talaba", faculty_id=faculty.id, group_or_position="1",
        biometric_embedding=json.dumps(list(embedding)),
    )
    db_session.add(person)
    await db_session.commit()
    return person


def _patch_zoom_pipeline(monkeypatch, *, main_frame: bytes | None, zoom_faces: list, calls: dict):
    """Asosiy oqimdan kadr olish va undagi detektsiya — soxta."""

    async def fake_grab(camera, **kwargs):
        calls.setdefault("grabs", []).append(str(camera.id))
        return main_frame

    async def fake_detect(frame, *, priority=None, roi=None, **kwargs):
        calls.setdefault("rois", []).append(roi)
        return zoom_faces

    monkeypatch.setattr(attendance_ai, "grab_main_stream_frame_once", fake_grab)
    monkeypatch.setattr(attendance_ai, "detect_faces", fake_detect)
    monkeypatch.setattr(attendance_ai, "ai_prefers_substream", lambda camera: True)


class TestZoomPassInAttendance:
    async def test_zoom_match_writes_the_same_attendance_row(
        self, db_session, zoom_camera, zoom_settings, monkeypatch
    ):
        """Zoomda tanilgan odam odatdagi ko'rinish kabi davomatga tushadi."""
        embedding = np.array([1.0] + [0.0] * 511)
        person = await _enrolled_person(db_session, embedding)

        calls: dict = {}
        big_face = _face(90, embedding=embedding)
        _patch_zoom_pipeline(monkeypatch, main_frame=_jpeg(64, 36), zoom_faces=[big_face], calls=calls)

        # Substream kadrida faqat 22 pikselli yuz — tanib bo'lmaydi.
        records = await attendance_ai.process_camera_frame(
            _jpeg(1280, 720), db_session, zoom_camera, faces=[_face(22, top=350, left=630)]
        )

        assert [str(r.student_staff_id) for r in records] == [str(person.id)]
        stored = (await db_session.execute(select(AttendanceRecord))).scalars().all()
        assert len(stored) == 1
        assert str(stored[0].student_staff_id) == str(person.id)
        assert stored[0].source == "kamera"
        # Hudud 22 px li yuz atrofida, normallashgan va [0, 1] ichida.
        assert len(calls["rois"]) == 1
        roi = calls["rois"][0]
        assert all(0.0 <= value <= 1.0 for value in roi)
        assert roi[0] < 640 / 1280 < roi[2]

        stats = recognition_stats.snapshot(str(zoom_camera.id))
        assert stats.zoom_attempts == 1
        assert stats.zoom_faces == 1
        assert stats.zoom_matches == 1
        assert stats.zoom_px_median == 90

    async def test_no_zoom_when_every_face_is_outside_the_window(
        self, db_session, zoom_camera, zoom_settings, monkeypatch
    ):
        await _enrolled_person(db_session, np.array([1.0] + [0.0] * 511))
        calls: dict = {}
        _patch_zoom_pipeline(monkeypatch, main_frame=_jpeg(64, 36), zoom_faces=[], calls=calls)

        # 6 px — shovqin; 50 px — allaqachon tahlil qilingan.
        await attendance_ai.process_camera_frame(
            _jpeg(1280, 720),
            db_session,
            zoom_camera,
            faces=[_face(6), _face(50, embedding=np.array([0.0, 1.0] + [0.0] * 510))],
        )
        assert "grabs" not in calls
        assert recognition_stats.snapshot(str(zoom_camera.id)).zoom_attempts == 0

    async def test_second_frame_inside_the_interval_does_not_grab_again(
        self, db_session, zoom_camera, zoom_settings, monkeypatch
    ):
        await _enrolled_person(db_session, np.array([1.0] + [0.0] * 511))
        calls: dict = {}
        _patch_zoom_pipeline(monkeypatch, main_frame=None, zoom_faces=[], calls=calls)

        for _ in range(3):
            await attendance_ai.process_camera_frame(
                _jpeg(1280, 720), db_session, zoom_camera, faces=[_face(22, top=350, left=630)]
            )
        assert calls["grabs"] == [str(zoom_camera.id)]
        assert recognition_stats.snapshot(str(zoom_camera.id)).zoom_attempts == 1

    async def test_disabled_flag_turns_the_whole_pass_off(
        self, db_session, zoom_camera, zoom_settings, monkeypatch
    ):
        monkeypatch.setattr(settings, "face_zoom_enabled", False)
        await _enrolled_person(db_session, np.array([1.0] + [0.0] * 511))
        calls: dict = {}
        _patch_zoom_pipeline(monkeypatch, main_frame=_jpeg(64, 36), zoom_faces=[], calls=calls)

        await attendance_ai.process_camera_frame(
            _jpeg(1280, 720), db_session, zoom_camera, faces=[_face(22, top=350, left=630)]
        )
        assert "grabs" not in calls

    async def test_camera_already_on_the_main_stream_is_skipped(
        self, db_session, zoom_camera, zoom_settings, monkeypatch
    ):
        await _enrolled_person(db_session, np.array([1.0] + [0.0] * 511))
        calls: dict = {}
        _patch_zoom_pipeline(monkeypatch, main_frame=_jpeg(64, 36), zoom_faces=[], calls=calls)
        monkeypatch.setattr(attendance_ai, "ai_prefers_substream", lambda camera: False)

        await attendance_ai.process_camera_frame(
            _jpeg(1280, 720), db_session, zoom_camera, faces=[_face(22, top=350, left=630)]
        )
        assert "grabs" not in calls

    async def test_concurrency_cap_limits_how_many_cameras_read_4k(
        self, db_session, zoom_camera, zoom_settings, monkeypatch
    ):
        """Chegara to'lgan bo'lsa kamera shu kadrda zoom qilmaydi."""
        monkeypatch.setattr(settings, "face_zoom_max_concurrent_cameras", 1)
        await _enrolled_person(db_session, np.array([1.0] + [0.0] * 511))
        calls: dict = {}
        _patch_zoom_pipeline(monkeypatch, main_frame=_jpeg(64, 36), zoom_faces=[], calls=calls)

        # Boshqa kamera hozir asosiy oqimni o'qiyapti.
        assert face_zoom.zoom_limiter.acquire("boshqa-kamera") is True
        try:
            await attendance_ai.process_camera_frame(
                _jpeg(1280, 720), db_session, zoom_camera, faces=[_face(22, top=350, left=630)]
            )
        finally:
            face_zoom.zoom_limiter.release()
        assert "grabs" not in calls
