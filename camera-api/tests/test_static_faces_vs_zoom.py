"""Statik yuz filtri (app/services/static_faces.py) va zoom passi
(app/jobs/attendance_ai.py) o'rtasidagi ta'sir.

Savol: faqat 4K zoom orqali tanilayotgan odam — ya'ni aynan zoom uchun
yaratilgan holat — statik ("plakat") deb belgilanib qolmaydimi.
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
from app.models import Building, Camera, Faculty, StudentStaff
from app.services import static_faces


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
async def room_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Auditoriya", ip="10.0.9.88", building_id=building.id, zone="Xona",
        resolution="4K", status="faol",
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera, attribute_names=["building"])
    return camera


@pytest.fixture
def tight_static_settings(monkeypatch):
    """Productiondagi mantiq, lekin test uchun qisqartirilgan chegaralar."""
    monkeypatch.setattr(settings, "static_face_skip_enabled", True)
    monkeypatch.setattr(settings, "static_face_min_hits", 3)
    monkeypatch.setattr(settings, "static_face_min_span_seconds", 10)
    monkeypatch.setattr(settings, "static_face_min_gap_seconds", 5)
    monkeypatch.setattr(settings, "face_zoom_enabled", True)
    monkeypatch.setattr(settings, "face_zoom_min_px", 10)
    monkeypatch.setattr(settings, "face_zoom_max_px", 45)
    monkeypatch.setattr(settings, "face_zoom_max_faces", 4)
    monkeypatch.setattr(settings, "face_zoom_interval_seconds", 0)
    monkeypatch.setattr(settings, "face_zoom_max_concurrent_cameras", 2)
    monkeypatch.setattr(settings, "face_analysis_min_px", 40)
    monkeypatch.setattr(settings, "attendance_min_face_px", 40)
    monkeypatch.setattr(settings, "face_track_fusion_enabled", False)
    static_faces.reset_for_tests()
    yield
    static_faces.reset_for_tests()


async def _enrolled_person(db_session, embedding, name="Orqa Qatordagi Talaba") -> StudentStaff:
    faculty = (await db_session.execute(select(Faculty))).scalars().first()
    person = StudentStaff(
        full_name=name, type="talaba", faculty_id=faculty.id, group_or_position="1",
        biometric_embedding=json.dumps(list(embedding)),
    )
    db_session.add(person)
    await db_session.commit()
    return person


class TestZoomRecognisedPersonIsProtected:
    async def test_person_matched_only_by_zoom_never_becomes_static(
        self, db_session, room_camera, tight_static_settings, monkeypatch
    ):
        """Odam HAR kadrda 4K zoom orqali tanilyapti (davomati yozilyapti).
        Uning substream ramkasi HECH QACHON "plakat" deb belgilanmasligi
        kerak — aks holda undan keyin na solishtirish, na zoom bo'ladi,
        ya'ni tirik odam tizim uchun ko'rinmas bo'lib qolardi."""
        embedding = np.array([1.0] + [0.0] * 511)
        person = await _enrolled_person(db_session, embedding)
        camera_key = str(room_camera.id)

        async def fake_grab(camera, **kwargs):
            return _jpeg(2688, 1520)

        async def fake_detect(frame, *, priority=None, roi=None, **kwargs):
            # 4K hududda o'sha odam katta va aniq ko'rinadi.
            return [_face(90, embedding=embedding)]

        monkeypatch.setattr(attendance_ai, "grab_main_stream_frame_once", fake_grab)
        monkeypatch.setattr(attendance_ai, "detect_faces", fake_detect)
        monkeypatch.setattr(attendance_ai, "ai_prefers_substream", lambda camera: True)

        # Statik xotiradagi soat boshqariladigan bo'lsin (min_gap/min_span).
        clock = [1000.0]
        monkeypatch.setattr(static_faces.time, "monotonic", lambda: clock[0])

        matched_by_zoom = 0
        for _ in range(6):
            # Har safar AYNAN bir joyda o'tirgan, substreamda 22 px li yuz.
            faces = [_face(22, top=350, left=630)]
            records = await attendance_ai.process_camera_frame(
                _jpeg(1280, 720), db_session, room_camera, faces=faces
            )
            if records:
                matched_by_zoom += 1
            clock[0] += 6.0

        assert matched_by_zoom >= 1, "zoom hech bo'lmaganda bir marta tanishi kerak edi"
        # Zoom passi moslikni substream koordinatalariga qaytargani uchun
        # o'sha joy himoyalangan: statik ramka yo'q.
        static_boxes = static_faces.static_face_store.static_boxes(camera_key, now=clock[0])
        assert not static_boxes, (
            "zoom orqali tanilgan odamning ramkasi statik ('plakat') deb "
            "belgilandi — zoomdagi moslik note_matched ga yetib bormayapti"
        )
        assert str(person.id)  # yozuv bor

    async def test_a_real_poster_is_still_promoted(
        self, db_session, room_camera, tight_static_settings, monkeypatch
    ):
        """Nazorat: hech kimga mos kelmaydigan (zoom ham tanimaydigan)
        qimirlamas ramka oldingidek "plakat" deb belgilanadi."""
        camera_key = str(room_camera.id)
        await _enrolled_person(db_session, np.array([1.0] + [0.0] * 511))

        async def fake_grab(camera, **kwargs):
            return _jpeg(2688, 1520)

        async def fake_detect(frame, *, priority=None, roi=None, **kwargs):
            # 4K hududda ham hech qanday tanish mumkin yuz yo'q.
            return []

        monkeypatch.setattr(attendance_ai, "grab_main_stream_frame_once", fake_grab)
        monkeypatch.setattr(attendance_ai, "detect_faces", fake_detect)
        monkeypatch.setattr(attendance_ai, "ai_prefers_substream", lambda camera: True)
        clock = [1000.0]
        monkeypatch.setattr(static_faces.time, "monotonic", lambda: clock[0])

        for _ in range(6):
            await attendance_ai.process_camera_frame(
                _jpeg(1280, 720), db_session, room_camera, faces=[_face(22, top=350, left=630)]
            )
            clock[0] += 6.0

        assert static_faces.static_face_store.static_boxes(camera_key, now=clock[0]), (
            "devordagi rasm baribir statik deb belgilanishi kerak"
        )


class TestNoteMatchedProtection:
    def test_substream_match_clears_a_watched_box(self, tight_static_settings):
        """Nazorat: ODATDAGI (substream) moslik ramkani himoyalaydi."""
        store = static_faces.static_face_store
        face = _face(22, top=350, left=630)
        for i in range(4):
            store.observe("cam-a", [face], now=100.0 + i * 6.0)
        assert store.static_boxes("cam-a", now=125.0)
        store.note_matched("cam-a", [face.bbox], now=126.0)
        assert not store.static_boxes("cam-a", now=127.0)
