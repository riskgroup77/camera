"""app/services/stream_cache.py replaced spawning a fresh ffmpeg process
on every frame grab with one persistent per-camera reader that caches its
most recently decoded frame. These tests cover the pure/deterministic
parts (JPEG boundary parsing, freshness, idle reaping) without spawning
real ffmpeg processes — the actual subprocess plumbing is exercised
implicitly by every attendance_ai/vision_ai/fire_ai test that already
mocks grab_frame/grab_frame_pair further up the stack, and by live
verification against a real camera."""

import time

from app.config import settings
from app.services.stream_cache import StreamCache, _StreamReader, extract_complete_jpeg_frames


def _fake_jpeg(payload: bytes) -> bytes:
    return b"\xff\xd8" + payload + b"\xff\xd9"


class TestExtractCompleteJpegFrames:
    def test_empty_buffer_yields_nothing(self):
        frames, remainder = extract_complete_jpeg_frames(b"")
        assert frames == []
        assert remainder == b""

    def test_single_complete_frame(self):
        jpeg = _fake_jpeg(b"frame-data")
        frames, remainder = extract_complete_jpeg_frames(jpeg)
        assert frames == [jpeg]
        assert remainder == b""

    def test_two_back_to_back_frames_both_extracted_in_order(self):
        first, second = _fake_jpeg(b"one"), _fake_jpeg(b"two")
        frames, remainder = extract_complete_jpeg_frames(first + second)
        assert frames == [first, second]
        assert remainder == b""

    def test_incomplete_trailing_frame_is_kept_as_remainder(self):
        complete = _fake_jpeg(b"done")
        incomplete_tail = b"\xff\xd8partial-frame-no-eoi-yet"
        frames, remainder = extract_complete_jpeg_frames(complete + incomplete_tail)
        assert frames == [complete]
        assert remainder == incomplete_tail

    def test_garbage_before_first_soi_is_discarded(self):
        jpeg = _fake_jpeg(b"real-frame")
        frames, remainder = extract_complete_jpeg_frames(b"\x00\x01garbage" + jpeg)
        assert frames == [jpeg]
        assert remainder == b""

    def test_no_soi_at_all_discards_everything(self):
        frames, remainder = extract_complete_jpeg_frames(b"no jpeg markers here at all")
        assert frames == []
        assert remainder == b""


class TestStreamReaderFreshness:
    def test_no_frame_yet_returns_none(self):
        reader = _StreamReader("rtsp://fake")
        assert reader.get_frame() is None

    def test_fresh_frame_is_returned(self):
        reader = _StreamReader("rtsp://fake")
        reader._latest_frame = b"jpeg-bytes"
        reader._latest_frame_at = time.monotonic()
        assert reader.get_frame() == b"jpeg-bytes"

    def test_stale_frame_reads_as_none(self):
        reader = _StreamReader("rtsp://fake")
        reader._latest_frame = b"jpeg-bytes"
        reader._latest_frame_at = time.monotonic() - settings.stream_cache_max_age_seconds - 1
        assert reader.get_frame() is None


class TestStreamCacheIdleReaping:
    async def test_idle_reader_is_stopped_and_removed(self):
        cache = StreamCache()
        reader = await cache._get_or_create_reader("rtsp://fake")
        reader._last_requested_at = time.monotonic() - settings.stream_cache_idle_timeout_seconds - 1

        await cache.reap_idle()

        assert "rtsp://fake" not in cache._readers

    async def test_recently_used_reader_is_not_reaped(self):
        cache = StreamCache()
        reader = await cache._get_or_create_reader("rtsp://fake")
        reader.touch()

        await cache.reap_idle()

        assert "rtsp://fake" in cache._readers

    async def test_same_stream_url_reuses_the_same_reader(self):
        cache = StreamCache()
        first = await cache._get_or_create_reader("rtsp://fake")
        second = await cache._get_or_create_reader("rtsp://fake")
        assert first is second

    async def test_stop_all_clears_every_reader(self):
        cache = StreamCache()
        await cache._get_or_create_reader("rtsp://a")
        await cache._get_or_create_reader("rtsp://b")

        await cache.stop_all()

        assert cache._readers == {}
