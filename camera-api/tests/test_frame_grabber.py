"""Unit tests for entrance camera main-stream AI source selection."""
from unittest.mock import MagicMock

from app.config import settings
from app.services import frame_grabber


def _camera(**kwargs):
    cam = MagicMock()
    cam.is_entrance = kwargs.get("is_entrance", False)
    cam.is_perimeter = kwargs.get("is_perimeter", False)
    cam.ip = "192.168.0.8"
    cam.port = 554
    cam.rtsp_path = "/Streaming/Channels/101"
    cam.rtsp_username = None
    cam.rtsp_password = None
    return cam


def test_entrance_uses_main_stream_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "ai_entrance_use_main_stream", True)
    cam = _camera(is_entrance=True)
    assert frame_grabber.ai_prefers_substream(cam) is False
    url = frame_grabber.rtsp_url_for_camera(cam)
    assert "/Streaming/Channels/101" in url


def test_non_entrance_uses_substream(monkeypatch):
    monkeypatch.setattr(settings, "ai_entrance_use_main_stream", True)
    cam = _camera(is_entrance=False)
    assert frame_grabber.ai_prefers_substream(cam) is True
    url = frame_grabber.rtsp_url_for_camera(cam)
    assert "/Streaming/Channels/102" in url


def test_perimeter_uses_main_stream(monkeypatch):
    monkeypatch.setattr(settings, "ai_entrance_use_main_stream", True)
    cam = _camera(is_perimeter=True)
    assert frame_grabber.ai_prefers_substream(cam) is False
