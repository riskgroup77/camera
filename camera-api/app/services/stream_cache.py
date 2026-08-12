"""Persistent per-camera frame cache — replaces spawning a fresh ffmpeg
process on every single frame grab with one long-lived ffmpeg reader per
camera stream that continuously decodes frames and keeps only the latest
one in memory. app/services/frame_grabber.py's grab_frame()/
grab_frame_pair() now read from this cache instead of shelling out fresh
each call — same public contract (JPEG bytes or None), different
implementation underneath.

Why this matters at scale: the old grab_frame() made ffmpeg reconnect to
the camera's stream from scratch — fresh process spawn, fresh TCP/RTSP
handshake, fresh HLS playlist fetch — on every single call. At 400
cameras swept every 30s by up to three independent sweep loops
(attendance_ai/vision_ai/fire_ai), that was hundreds of fresh
reconnects every interval: real CPU/process/network overhead that scales
linearly with camera count for no benefit, since the stream itself is
continuous — there was never a reason to disconnect between grabs. A
persistent reader connects once and stays connected; every subsequent
grab is just reading whatever frame it decoded most recently.

A reader is started lazily (on first request for a stream_url) and
stopped after stream_cache_idle_timeout_seconds of no requests, so a
camera that's been deactivated/removed doesn't keep a decode pipeline
running forever. If the ffmpeg process dies (camera went offline, network
blip), the cached frame simply ages out (see stream_cache_max_age_seconds)
and reads as "no frame" until the next request restarts it.
"""

import asyncio
import logging
import time

from app.config import settings

logger = logging.getLogger("app.stream_cache")

_JPEG_SOI = b"\xff\xd8"
_JPEG_EOI = b"\xff\xd9"
_MAX_BUFFER_BYTES = 5_000_000  # guards against unbounded growth if a stream never emits a clean JPEG boundary


def extract_complete_jpeg_frames(buffer: bytes) -> tuple[list[bytes], bytes]:
    """Pulls every complete JPEG frame (SOI...EOI) out of a raw MJPEG byte
    buffer, in order. Returns (frames_found, remaining_buffer) — the
    remainder is either empty (buffer ended cleanly) or an incomplete
    frame's leading bytes still waiting for more data on the next read.
    A pure function (no I/O, no object state) specifically so this
    byte-level parsing can be unit tested without a real ffmpeg process —
    see _StreamReader._read_loop, its only caller."""
    frames: list[bytes] = []
    while True:
        start = buffer.find(_JPEG_SOI)
        if start == -1:
            return frames, b""
        end = buffer.find(_JPEG_EOI, start + 2)
        if end == -1:
            return frames, buffer[start:]  # incomplete frame tail — keep from SOI, wait for more bytes
        frames.append(buffer[start : end + 2])
        buffer = buffer[end + 2 :]


class _StreamReader:
    """One persistent ffmpeg process for one stream_url, continuously
    decoding frames at settings.stream_cache_capture_fps and keeping only
    the latest complete JPEG frame in memory."""

    def __init__(self, stream_url: str):
        self.stream_url = stream_url
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._latest_frame: bytes | None = None
        self._latest_frame_at: float = 0.0
        self._last_requested_at: float = time.monotonic()
        self._lock = asyncio.Lock()

    def touch(self) -> None:
        self._last_requested_at = time.monotonic()

    @property
    def idle_seconds(self) -> float:
        return time.monotonic() - self._last_requested_at

    def get_frame(self) -> bytes | None:
        if self._latest_frame is None:
            return None
        if time.monotonic() - self._latest_frame_at > settings.stream_cache_max_age_seconds:
            return None  # stale — reader is running but hasn't decoded anything recent (stream stalled)
        return self._latest_frame

    async def ensure_started(self) -> None:
        async with self._lock:
            if self._proc is not None and self._proc.returncode is None:
                return  # already running
            await self._start()

    async def _start(self) -> None:
        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            self.stream_url,
            "-f",
            "mjpeg",
            "-q:v",
            "5",
            "-r",
            str(settings.stream_cache_capture_fps),
            "-",
        ]
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
            )
        except FileNotFoundError:
            logger.error("ffmpeg not found; cannot start stream reader", extra={"stream_url": self.stream_url})
            return
        self._reader_task = asyncio.create_task(self._read_loop())
        logger.info("stream reader started", extra={"stream_url": self.stream_url})

    async def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        buffer = b""
        try:
            while True:
                chunk = await self._proc.stdout.read(65536)
                if not chunk:
                    break
                buffer += chunk
                frames, buffer = extract_complete_jpeg_frames(buffer)
                if frames:
                    self._latest_frame = frames[-1]  # only the most recent decoded frame is kept
                    self._latest_frame_at = time.monotonic()
                if len(buffer) > _MAX_BUFFER_BYTES:
                    logger.warning("stream reader buffer overflow, resetting", extra={"stream_url": self.stream_url})
                    buffer = b""
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("stream reader loop crashed", extra={"stream_url": self.stream_url})
        finally:
            logger.info("stream reader stopped reading", extra={"stream_url": self.stream_url})

    async def stop(self) -> None:
        async with self._lock:
            if self._reader_task is not None:
                self._reader_task.cancel()
                self._reader_task = None
            if self._proc is not None and self._proc.returncode is None:
                try:
                    self._proc.kill()
                    await self._proc.wait()
                except ProcessLookupError:
                    pass
            self._proc = None


class StreamCache:
    def __init__(self) -> None:
        self._readers: dict[str, _StreamReader] = {}
        self._lock = asyncio.Lock()

    async def get_frame(self, stream_url: str) -> bytes | None:
        reader = await self._get_or_create_reader(stream_url)
        reader.touch()
        await reader.ensure_started()
        return reader.get_frame()

    async def _get_or_create_reader(self, stream_url: str) -> _StreamReader:
        async with self._lock:
            reader = self._readers.get(stream_url)
            if reader is None:
                reader = _StreamReader(stream_url)
                self._readers[stream_url] = reader
            return reader

    async def reap_idle(self) -> None:
        async with self._lock:
            idle_urls = [
                url
                for url, reader in self._readers.items()
                if reader.idle_seconds > settings.stream_cache_idle_timeout_seconds
            ]
            reapers = [self._readers.pop(url) for url in idle_urls]
        for reader in reapers:
            await reader.stop()
            logger.info("stream reader reaped (idle)", extra={"stream_url": reader.stream_url})

    async def stop_all(self) -> None:
        async with self._lock:
            readers = list(self._readers.values())
            self._readers.clear()
        await asyncio.gather(*(r.stop() for r in readers), return_exceptions=True)


_cache = StreamCache()


async def get_cached_frame(stream_url: str) -> bytes | None:
    return await _cache.get_frame(stream_url)


async def reap_idle_readers() -> None:
    await _cache.reap_idle()


async def shutdown_stream_cache() -> None:
    """Kills every live ffmpeg reader process — called from main.py's
    lifespan teardown so a restart doesn't leave orphaned ffmpeg processes
    running past the app's own shutdown."""
    await _cache.stop_all()


async def stream_cache_reaper_loop() -> None:
    while True:
        try:
            await reap_idle_readers()
        except Exception:
            logger.exception("stream cache reaper failed")
        await asyncio.sleep(60)
