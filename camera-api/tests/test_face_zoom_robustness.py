"""Zoom pass (app/jobs/attendance_ai.py::_zoom_recheck) nosozlikka chidamliligi.

Zoom — ODATDAGI tekshiruvga QO'SHIMCHA: u muvaffaqiyatsiz tugasa, shu
kadrda allaqachon yozilgan davomat natijasi yo'qolmasligi kerak.
"""

import asyncio
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
async def zoom_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Xona kamerasi", ip="10.0.9.77", building_id=building.id, zone="Xona",
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
    monkeypatch.setattr(settings, "face_zoom_interval_seconds", 0)
    monkeypatch.setattr(settings, "face_zoom_max_concurrent_cameras", 2)
    monkeypatch.setattr(settings, "face_analysis_min_px", 40)
    monkeypatch.setattr(settings, "attendance_min_face_px", 40)
    monkeypatch.setattr(settings, "face_track_fusion_enabled", False)


async def _enrolled_person(db_session, embedding, name="Yaqin Talaba") -> StudentStaff:
    faculty = (await db_session.execute(select(Faculty))).scalars().first()
    person = StudentStaff(
        full_name=name, type="talaba", faculty_id=faculty.id, group_or_position="1",
        biometric_embedding=json.dumps(list(embedding)),
    )
    db_session.add(person)
    await db_session.commit()
    return person


class TestSubToMainCoordinateMapping:
    """Ramka 1280x720 substreamdan, hudud esa 2688x1520 asosiy kadrga
    qo'llanadi — tomonlar nisbati biroz farq qiladi (1.778 vs 1.768)."""

    def test_region_still_covers_the_face_on_the_main_frame(self):
        from app.services.face_zoom import roi_for_box

        sub_w, sub_h = 1280, 720
        main_w, main_h = 2688, 1520
        # Yuz substreamda (630, 350)-(652, 372), 22 px.
        roi = roi_for_box((630.0, 350.0, 652.0, 372.0), sub_w, sub_h, margin=2.5)

        # Asosiy kadrdagi haqiqiy joy: BIR XIL ko'rish maydoni deb
        # hisoblaganda o'qlar bo'yicha alohida masshtab.
        fx, fy = main_w / sub_w, main_h / sub_h
        face = (630.0 * fx, 350.0 * fy, 652.0 * fx, 372.0 * fy)
        region = (roi[0] * main_w, roi[1] * main_h, roi[2] * main_w, roi[3] * main_h)

        assert region[0] <= face[0] and region[1] <= face[1]
        assert region[2] >= face[2] and region[3] >= face[3]
        # Kengaytma yuz o'lchamiga nisbatan sezilarli zaxira beradi
        # (odam kadr orasida biroz siljiydi).
        assert (region[2] - region[0]) >= 2.0 * (face[2] - face[0])
        assert (region[3] - region[1]) >= 2.0 * (face[3] - face[1])

    def test_mapping_is_per_axis_so_aspect_ratio_drift_does_not_shift_it(self):
        """Normallashtirish har o'q bo'yicha alohida — 16:9 va 1.768
        o'rtasidagi farq hududni siljitmaydi, faqat balandligini
        proporsional o'zgartiradi."""
        from app.services.face_zoom import roi_for_box

        a = roi_for_box((640.0, 360.0, 660.0, 380.0), 1280, 720, margin=2.5)
        b = roi_for_box((1344.0, 760.0, 1386.0, 802.0), 2688, 1520, margin=2.5)
        # Markazlar mos: ikkalasi ham kadr o'rtasida.
        assert (a[0] + a[2]) / 2 == pytest.approx((b[0] + b[2]) / 2, abs=0.01)
        assert (a[1] + a[3]) / 2 == pytest.approx((b[1] + b[3]) / 2, abs=0.01)


class TestZoomFailureDoesNotLoseTheNormalPass:
    async def test_main_stream_grab_error_keeps_the_records_already_matched(
        self, db_session, zoom_camera, zoom_settings, monkeypatch
    ):
        """4K kadr olishda xato (tarmoq, ffmpeg) — substreamda ALLAQACHON
        tanilgan odamning natijasi qaytishi kerak, chaqiruvchiga istisno
        ko'tarilmasligi kerak."""
        embedding = np.array([1.0] + [0.0] * 511)
        person = await _enrolled_person(db_session, embedding)

        async def boom(camera, **kwargs):
            raise RuntimeError("rtsp connect failed")

        monkeypatch.setattr(attendance_ai, "grab_main_stream_frame_once", boom)
        monkeypatch.setattr(attendance_ai, "ai_prefers_substream", lambda camera: True)

        records = await attendance_ai.process_camera_frame(
            _jpeg(1280, 720),
            db_session,
            zoom_camera,
            # Katta yuz — tanildi; kichik yuz — zoom nomzodi.
            faces=[_face(60, embedding=embedding), _face(22, top=350, left=630)],
        )
        assert [str(r.student_staff_id) for r in records] == [str(person.id)]

    async def test_one_failing_region_does_not_abort_the_frame(
        self, db_session, zoom_camera, zoom_settings, monkeypatch
    ):
        """Ikki hududdan biri xato bersa, ikkinchisining natijasi va
        substreamda tanilgan odam yo'qolmasligi kerak — va hech qanday
        vazifa "exception was never retrieved" holida qolmasligi kerak."""
        embedding = np.array([1.0] + [0.0] * 511)
        person = await _enrolled_person(db_session, embedding)
        monkeypatch.setattr(attendance_ai, "ai_prefers_substream", lambda camera: True)

        async def fake_grab(camera, **kwargs):
            return _jpeg(2688, 1520)

        seen: list = []

        async def fake_detect(frame, *, priority=None, roi=None, **kwargs):
            seen.append(roi)
            if len(seen) == 1:
                raise RuntimeError("detector blew up on region 1")
            await asyncio.sleep(0)
            return []

        monkeypatch.setattr(attendance_ai, "grab_main_stream_frame_once", fake_grab)
        monkeypatch.setattr(attendance_ai, "detect_faces", fake_detect)

        records = await attendance_ai.process_camera_frame(
            _jpeg(1280, 720),
            db_session,
            zoom_camera,
            faces=[
                _face(60, embedding=embedding),
                _face(22, top=350, left=630),
                _face(20, top=100, left=100),
            ],
        )
        assert [str(r.student_staff_id) for r in records] == [str(person.id)]

    async def test_zoom_slot_is_released_after_a_failure(
        self, db_session, zoom_camera, zoom_settings, monkeypatch
    ):
        """Xatodan keyin cheklovchi slot bo'sh qolishi kerak, aks holda
        kamera boshqa hech qachon zoom qila olmaydi."""

        async def boom(camera, **kwargs):
            raise RuntimeError("nope")

        monkeypatch.setattr(attendance_ai, "grab_main_stream_frame_once", boom)
        monkeypatch.setattr(attendance_ai, "ai_prefers_substream", lambda camera: True)
        await _enrolled_person(db_session, np.array([1.0] + [0.0] * 511))

        await attendance_ai.process_camera_frame(
            _jpeg(1280, 720), db_session, zoom_camera, faces=[_face(22, top=350, left=630)]
        )
        assert attendance_ai.face_zoom.zoom_limiter.active == 0
