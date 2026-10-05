"""Unit tests for entrance camera main-stream AI source selection."""
from unittest.mock import MagicMock

import pytest

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
    cam.stream_url = kwargs.get("stream_url")
    return cam


def test_ai_reads_the_substream_through_the_mediamtx_relay(monkeypatch):
    """Kameraga bitta ulanish: AI MediaMTX yo'lini o'qiydi (kamera sessiya cheklovi)."""
    monkeypatch.setattr(settings, "ai_read_via_mediamtx", True)
    monkeypatch.setattr(settings, "mediamtx_shard_hls_base_urls", "/s0,/s1")
    monkeypatch.setattr(settings, "mediamtx_shard_hls_internal_base_urls", "http://mediamtx-0:8888,http://mediamtx-1:8888")
    cam = _camera(stream_url="/s1/cam-abc/index.m3u8")
    assert frame_grabber.rtsp_url_for_camera(cam, substream=True) == "rtsp://mediamtx-1:8554/cam-abc"
    # Asosiy oqim va yo'li yo'q kamera — to'g'ridan-to'g'ri kameraga.
    assert frame_grabber.rtsp_url_for_camera(cam, substream=False).startswith("rtsp://192.168.0.8")
    assert frame_grabber.rtsp_url_for_camera(_camera(), substream=True).startswith("rtsp://192.168.0.8")


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


def test_perimeter_uses_main_stream_only_when_enabled(monkeypatch):
    """720p substream'dan keyin perimetr ham standart bo'yicha substream'da."""
    monkeypatch.setattr(settings, "ai_entrance_use_main_stream", True)
    cam = _camera(is_perimeter=True)
    assert frame_grabber.ai_prefers_substream(cam) is True
    monkeypatch.setattr(settings, "ai_perimeter_main_stream", True)
    assert frame_grabber.ai_prefers_substream(cam) is False


class _FakeCache:
    """get_cached_frame_with_seq o'rnini bosadi: har chaqiruvda navbatdagi
    (kadr, raqam) ni beradi, ro'yxat tugagach oxirgisini qaytaraveradi —
    yangi kadr kelmay qolgan oqim xuddi shunday ko'rinadi."""

    def __init__(self, *snapshots):
        self.snapshots = list(snapshots)
        self.calls = 0

    async def __call__(self, source):
        index = min(self.calls, len(self.snapshots) - 1)
        self.calls += 1
        return self.snapshots[index]


def _patch_grabber(monkeypatch, cache: _FakeCache, wait_seconds: float = 0.6, history=None):
    async def no_thumbnail(camera_id, frame):
        return None

    async def fake_history(source):
        return list(history or [])

    # Standart bo'yicha tarix bo'sh — bu testlar kutish yo'lini tekshiradi.
    monkeypatch.setattr(frame_grabber, "get_cached_history", fake_history)

    monkeypatch.setattr(frame_grabber, "get_cached_frame_with_seq", cache)
    monkeypatch.setattr(frame_grabber, "camera_video_source", lambda camera: "rtsp://fake")
    monkeypatch.setattr(frame_grabber, "frame_wait_seconds_for_camera", lambda camera: wait_seconds)
    monkeypatch.setattr(frame_grabber, "remember_frame", no_thumbnail)
    monkeypatch.setattr(frame_grabber, "is_stream_known_broken", lambda source: False)
    monkeypatch.setattr(frame_grabber, "_POLL_SECONDS", 0.01)


class TestPairNeverRepeatsAFrame:
    """Ikki kadrli tasdiq productionda bitta kadrni ikki marta tekshirardi:
    #13 signallarining 32/33 tasida ikkala o'lchov aynan bir xil edi."""

    async def test_waits_for_a_newer_frame(self, monkeypatch):
        cache = _FakeCache((b"A", 1), (b"A", 1), (b"A", 1), (b"B", 2))
        _patch_grabber(monkeypatch, cache)

        pair = await frame_grabber.grab_frame_pair_for_camera(_camera(), gap_seconds=0)

        assert pair == (b"A", b"B")

    async def test_stalled_stream_gives_no_pair_instead_of_a_duplicate(self, monkeypatch):
        cache = _FakeCache((b"A", 1))
        _patch_grabber(monkeypatch, cache, wait_seconds=0.1)

        assert await frame_grabber.grab_frame_pair_for_camera(_camera(), gap_seconds=0) is None

    async def test_no_first_frame_means_no_pair(self, monkeypatch):
        cache = _FakeCache(None)
        _patch_grabber(monkeypatch, cache, wait_seconds=0.05)

        assert await frame_grabber.grab_frame_pair_for_camera(_camera(), gap_seconds=0) is None


class TestBurstHasOnlyDistinctFrames:
    async def test_every_frame_is_newer_than_the_previous(self, monkeypatch):
        cache = _FakeCache((b"A", 1), (b"A", 1), (b"B", 2), (b"B", 2), (b"C", 3), (b"D", 4))
        _patch_grabber(monkeypatch, cache)

        frames = await frame_grabber.grab_frame_burst_for_camera(_camera(), count=4, gap_seconds=0)

        assert frames == [b"A", b"B", b"C", b"D"]

    async def test_burst_stops_when_the_stream_stalls(self, monkeypatch):
        """Uyqu ovozida bitta yumuq ko'zli kadr to'rt marta sanalardi —
        endi takror kadr umuman olinmaydi."""
        cache = _FakeCache((b"A", 1), (b"B", 2))
        _patch_grabber(monkeypatch, cache, wait_seconds=0.1)

        frames = await frame_grabber.grab_frame_burst_for_camera(_camera(), count=4, gap_seconds=0)

        assert frames == [b"A", b"B"]

    async def test_single_grab_accepts_whatever_is_cached(self, monkeypatch):
        cache = _FakeCache((b"A", 7))
        _patch_grabber(monkeypatch, cache)

        assert await frame_grabber.grab_frame_for_camera(_camera()) == b"A"


@pytest.fixture(autouse=True)
def _fresh_fallbacks():
    frame_grabber.reset_main_stream_fallbacks_for_tests()
    yield
    frame_grabber.reset_main_stream_fallbacks_for_tests()


class TestMainStreamFallback:
    """Productionda 11 ta kirish kamerasidan 7 tasining asosiy oqimi kun
    bo'yi kadr bermagan — ular davomatdan butunlay chiqib qolgan edi."""

    async def test_silent_main_stream_switches_the_camera_to_the_substream(self, monkeypatch):
        monkeypatch.setattr(settings, "ai_entrance_use_main_stream", True)
        cam = _camera(is_entrance=True)
        real_wait = frame_grabber.frame_wait_seconds_for_camera
        _patch_grabber(monkeypatch, _FakeCache(None), wait_seconds=0.05)

        assert frame_grabber.ai_prefers_substream(cam) is False
        assert await frame_grabber.grab_frame_for_camera(cam, wait_seconds=0.05) is None
        assert frame_grabber.ai_prefers_substream(cam) is True
        assert "/Streaming/Channels/102" in frame_grabber.rtsp_url_for_camera(cam)
        assert real_wait(cam) == 8.0

    async def test_the_silent_main_reader_is_closed_at_once(self, monkeypatch):
        """Yopilmasa, u yana 5 daqiqa tarmoqni band qilib, substream bilan
        birga ikki barobar yuklardi (productionda 172 o'quvchi)."""
        monkeypatch.setattr(settings, "ai_entrance_use_main_stream", True)
        cam = _camera(is_entrance=True)
        _patch_grabber(monkeypatch, _FakeCache(None), wait_seconds=0.05)
        stopped: list[str] = []

        async def fake_stop(url):
            stopped.append(url)

        monkeypatch.setattr(frame_grabber, "stop_stream_reader", fake_stop)
        await frame_grabber.grab_frame_for_camera(cam, wait_seconds=0.05)
        assert len(stopped) == 1

    async def test_main_stream_is_retried_after_the_cooldown(self, monkeypatch):
        monkeypatch.setattr(settings, "ai_entrance_use_main_stream", True)
        monkeypatch.setattr(settings, "ai_entrance_main_stream_retry_seconds", 0.0)
        cam = _camera(is_entrance=True)
        _patch_grabber(monkeypatch, _FakeCache(None), wait_seconds=0.05)

        await frame_grabber.grab_frame_for_camera(cam, wait_seconds=0.05)
        assert frame_grabber.ai_prefers_substream(cam) is False

    async def test_a_late_second_frame_is_not_a_main_stream_failure(self, monkeypatch):
        """Uzun kalit kadr oralig'ida ikkinchi kadr kechikishi tabiiy —
        bu asosiy oqimni tashlab ketishga sabab emas."""
        monkeypatch.setattr(settings, "ai_entrance_use_main_stream", True)
        cam = _camera(is_entrance=True)
        _patch_grabber(monkeypatch, _FakeCache((b"A", 1)), wait_seconds=0.05)

        assert await frame_grabber.grab_frame_pair_for_camera(cam, gap_seconds=0) is None
        assert frame_grabber.ai_prefers_substream(cam) is False

    async def test_substream_cameras_are_never_marked(self, monkeypatch):
        cam = _camera(is_entrance=False)
        _patch_grabber(monkeypatch, _FakeCache(None), wait_seconds=0.05)

        await frame_grabber.grab_frame_for_camera(cam, wait_seconds=0.05)
        assert frame_grabber._main_stream_failed_until == {}


class TestFramesFromHistory:
    """Kadr tarixi (stream_cache): juftlik va burst yangi kalit kadrni
    kutmasdan olinadi — bir vaqtda ishlagan modullar bir xil kadrni oladi."""

    @pytest.fixture(autouse=True)
    def _clean_frames(self, monkeypatch):
        monkeypatch.setattr(frame_grabber, "_all_clean", lambda frames: True)

    async def test_pair_comes_from_history_without_waiting(self, monkeypatch):
        cache = _FakeCache(None)
        history = [(b"c", 3, 102.0), (b"b", 2, 101.5), (b"a", 1, 101.0)]
        _patch_grabber(monkeypatch, cache, history=history)
        pair = await frame_grabber.grab_frame_pair_for_camera(_camera(), gap_seconds=1.0)
        assert pair == (b"a", b"c")  # 1 s oraliq: b (0.5 s) tashlab ketildi
        assert cache.calls == 0  # oqimdan yangi kadr kutilmadi

    async def test_burst_comes_from_history_oldest_first(self, monkeypatch):
        history = [(b"d", 4, 13.0), (b"c", 3, 12.0), (b"b", 2, 11.0), (b"a", 1, 10.0)]
        _patch_grabber(monkeypatch, _FakeCache(None), history=history)
        frames = await frame_grabber.grab_frame_burst_for_camera(_camera(), count=4, gap_seconds=1.0)
        assert frames == [b"a", b"b", b"c", b"d"]

    async def test_too_short_history_falls_back_to_waiting(self, monkeypatch):
        cache = _FakeCache((b"x", 5), (b"y", 6))
        _patch_grabber(monkeypatch, cache, history=[(b"only", 1, 5.0)])
        pair = await frame_grabber.grab_frame_pair_for_camera(_camera(), gap_seconds=0)
        assert pair == (b"x", b"y")
