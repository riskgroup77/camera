"""Zoom passi asosiy (4K) oqimning "orqaga chekinish" muddatiga bo'ysunadi.

Productionda topilgan (2026-09-20): kameraning 4K oqimi kadr bermay qo'ysa,
_main_stream_blocked faqat ODATDAGI yo'lni to'xtatardi. Zoom passi esa
(app/services/face_zoom.py) o'sha o'lik oqimga har 60 sekundda urinib,
face_zoom_wait_seconds gacha (8 s) kutib turardi — kirish/chiqish
sweep'ining 6 ta slotidan biri shuncha vaqt band bo'lardi — va muddatni
hech qachon uzaytirmasdi.
"""

import time
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.services import frame_grabber


def _camera(camera_id: str = "cam-1", **kwargs):
    cam = MagicMock()
    cam.id = camera_id
    cam.is_entrance = kwargs.get("is_entrance", False)
    cam.is_exit = kwargs.get("is_exit", False)
    cam.is_perimeter = kwargs.get("is_perimeter", False)
    cam.ip = "192.168.0.8"
    cam.port = 554
    cam.rtsp_path = "/Streaming/Channels/101"
    cam.rtsp_username = None
    cam.rtsp_password = None
    cam.stream_url = None
    return cam


@pytest.fixture
def zoom_env(monkeypatch):
    """4K kadr olish yo'li: to'g'ridan-to'g'ri RTSP, oqim esa kadr bermaydi."""
    frame_grabber.reset_main_stream_fallbacks_for_tests()
    monkeypatch.setattr(settings, "ai_use_direct_rtsp", True)
    monkeypatch.setattr(settings, "ai_read_via_mediamtx", False)
    monkeypatch.setattr(settings, "ai_entrance_use_main_stream", False)
    monkeypatch.setattr(settings, "face_zoom_wait_seconds", 0.05)
    monkeypatch.setattr(settings, "ai_room_main_stream_retry_seconds", 1000.0)
    monkeypatch.setattr(settings, "ai_entrance_main_stream_retry_seconds", 1000.0)
    dialed: list[str] = []

    async def fake_cached(source):
        dialed.append(source)
        return None

    async def fake_stop(source):
        return None

    monkeypatch.setattr(frame_grabber, "get_cached_frame_with_seq", fake_cached)
    monkeypatch.setattr(frame_grabber, "stop_stream_reader", fake_stop)
    monkeypatch.setattr(frame_grabber, "is_stream_known_broken", lambda source: True)
    yield dialed
    frame_grabber.reset_main_stream_fallbacks_for_tests()


class TestZoomRespectsMainStreamBackoff:
    async def test_blocked_camera_is_not_dialed_at_all(self, zoom_env):
        camera = _camera()
        frame_grabber._note_main_stream_result(camera, ok=False)  # 4K yiqildi
        assert frame_grabber._main_stream_blocked(camera) is True

        assert await frame_grabber.grab_main_stream_frame_once(camera) is None
        assert zoom_env == [], "jazo muddatida zoom 4K oqimga umuman ulanmasligi kerak"

    async def test_a_failed_zoom_attempt_extends_the_backoff(self, zoom_env):
        camera = _camera("cam-2")
        assert frame_grabber._main_stream_blocked(camera) is False

        assert await frame_grabber.grab_main_stream_frame_once(camera) is None
        assert zoom_env, "birinchi urinishda oqimga ulanishga harakat qilinadi"
        assert frame_grabber._main_stream_blocked(camera) is True, (
            "kadr bermagan zoom urinishi ham muddatni uzaytirishi kerak"
        )
        assert frame_grabber._main_stream_failed_until["cam-2"] - time.monotonic() > 500

    async def test_a_working_main_stream_clears_the_backoff(self, zoom_env, monkeypatch):
        camera = _camera("cam-3")
        frame_grabber._note_main_stream_result(camera, ok=False)

        async def fake_cached(source):
            return (b"jpeg", 7)

        monkeypatch.setattr(frame_grabber, "get_cached_frame_with_seq", fake_cached)
        # Muddat tugagan deb hisoblaymiz — oqim yana sinab ko'riladi.
        frame_grabber._main_stream_failed_until["cam-3"] = time.monotonic() - 1
        assert await frame_grabber.grab_main_stream_frame_once(camera) == b"jpeg"
        assert frame_grabber._main_stream_blocked(camera) is False
