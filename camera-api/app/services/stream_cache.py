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
import re
import time

from app.config import settings
from app.services.frame_quality import FlatBlock, looks_like_decode_damage, measure_frame

logger = logging.getLogger("app.stream_cache")

_JPEG_SOI = b"\xff\xd8"
_JPEG_EOI = b"\xff\xd9"
_MAX_BUFFER_BYTES = 5_000_000  # guards against unbounded growth if a stream never emits a clean JPEG boundary
_STDERR_TAIL_LINES = 20  # enough to see the actual RTSP failure reason without unbounded memory growth

_CREDENTIALS_IN_URL = re.compile(r"(rtsp://)[^@/]+@")


def _redact(text: str) -> str:
    """Strips `user:pass@` from any rtsp:// URL in `text` — ffmpeg's own
    stderr often echoes the input URL verbatim (e.g. in a 401/DESCRIBE
    failure line), so logging its raw stderr would otherwise leak camera
    RTSP credentials in plaintext the moment any camera has real ones set."""
    return _CREDENTIALS_IN_URL.sub(r"\1***:***@", text)


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
        self._log_url = _redact(stream_url)
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stderr_tail: list[str] = []
        self._frames_decoded = 0
        self._proc_started_at: float = 0.0
        self._latest_frame: bytes | None = None
        self._latest_frame_at: float = 0.0
        self._last_requested_at: float = time.monotonic()
        self._lock = asyncio.Lock()
        # Buzilgan kadr tekshiruvi (frame_quality.py) uchun holat.
        # `_last_judged` — AYNAN o'sha bayt obyekti: grab_frame_for_camera
        # kadr paydo bo'lguncha har 0.5 soniyada qayta so'raydi, va bitta
        # kadrni o'nlab marta dekodlab o'tirish behuda bo'lardi.
        self._last_judged: bytes | None = None
        self._last_judged_corrupt = False
        # Oxirgi QABUL QILINGAN kadrdagi blok — solishtirish uchun tayanch.
        # Rad etilgan kadr tayanchni yangilamaydi, aks holda bitta
        # shikastlangan kadr keyingisini "turg'un" ko'rsatib qo'yardi.
        self._previous_block: FlatBlock | None = None
        self._consecutive_rejected = 0

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

        frame = self._latest_frame
        if frame is not self._last_judged:
            self._last_judged = frame
            block = measure_frame(frame)
            self._last_judged_corrupt = looks_like_decode_damage(block, self._previous_block)
            if not self._last_judged_corrupt:
                self._previous_block = block
            if self._last_judged_corrupt:
                self._consecutive_rejected += 1
                # Bir-ikkita shikastlangan kadr — tarmoqda odatiy hol,
                # jimgina tashlab yuboriladi. Ketma-ket ko'p rad etilishi
                # esa kamera AI uchun ko'r bo'lib qolgani demakdir, va bu
                # jimgina sodir bo'lmasligi kerak — birinchi versiyada
                # aynan shu holat 107 kameradan 29 tasida bir tongda yuz
                # bergan va faqat loglar tufayli aniqlangan.
                if self._consecutive_rejected % 20 == 0:
                    logger.warning(
                        "stream keeps yielding corrupted frames; this camera is invisible to the AI sweeps",
                        extra={
                            "stream_url": self._log_url,
                            "consecutive_rejected": self._consecutive_rejected,
                        },
                    )
            else:
                self._consecutive_rejected = 0

        if self._last_judged_corrupt:
            return None
        return frame

    def is_known_broken(self) -> bool:
        """True once this reader has had stream_broken_grace_seconds to
        connect and decode at least one frame and still hasn't — lets a
        caller stop polling instead of waiting out its full deadline on a
        stream that was never going to produce anything. Recovers on its
        own: the moment a frame lands, _frames_decoded > 0 and this flips
        back to False for the reader's remaining lifetime."""
        if self._proc is None or self._frames_decoded > 0:
            return False
        return time.monotonic() - self._proc_started_at > settings.stream_broken_grace_seconds

    async def ensure_started(self) -> None:
        async with self._lock:
            if self._proc is not None and self._proc.returncode is None:
                return  # already running
            await self._start()

    async def _start(self) -> None:
        # +discardcorrupt: shikastlangan paketni dekoderga bermaydi, ya'ni
        # qisman dekodlangan kadr umuman hosil bo'lmaydi. Bu birinchi
        # himoya qatlami; frame_quality.py esa o'tib ketganini ushlaydi.
        # Ikkalasi kerak — ffmpeg faqat O'ZI shikastlangan deb bilgan
        # paketni tashlaydi, kadrdagi oq blok esa ba'zan "to'g'ri" deb
        # qabul qilingan paketdan ham chiqadi.
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-fflags", "+discardcorrupt"]
        # See stream_cache_decode_threads/stream_cache_keyframes_only's
        # docstrings in app/config.py — both target the same measured
        # problem (one persistent reader per camera decoding far more
        # than the ~1-2fps this cache actually samples) without changing
        # anything callers see: same JPEG-frame contract, same cache
        # behavior, just far less CPU spent producing it.
        if settings.stream_cache_decode_threads > 0:
            cmd.extend(["-threads", str(settings.stream_cache_decode_threads)])
        if settings.stream_cache_keyframes_only:
            cmd.extend(["-skip_frame", "nokey"])
        if self.stream_url.startswith("rtsp://"):
            cmd.extend(["-rtsp_transport", "tcp"])
        cmd.extend(
            [
                "-i",
                self.stream_url,
                "-an",
                "-f",
                "mjpeg",
                "-q:v",
                "5",
                "-r",
                str(settings.stream_cache_capture_fps),
                "-",
            ]
        )
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except FileNotFoundError:
            logger.error("ffmpeg not found; cannot start stream reader", extra={"stream_url": self._log_url})
            return
        self._stderr_tail = []
        self._frames_decoded = 0
        self._proc_started_at = time.monotonic()
        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        logger.info("stream reader started", extra={"stream_url": self._log_url})

    async def _drain_stderr(self) -> None:
        """ffmpeg's stderr must always be read, or the pipe fills and blocks
        the process — this ALSO gives us the actual failure reason (RTSP
        401/404/timeout/etc.) that used to be discarded entirely (was
        stderr=DEVNULL), which was the reason a broken camera's frame grab
        just silently returned None forever with zero trace anywhere."""
        assert self._proc is not None and self._proc.stderr is not None
        try:
            while True:
                line = await self._proc.stderr.readline()
                if not line:
                    break
                self._stderr_tail.append(_redact(line.decode(errors="replace").rstrip()))
                if len(self._stderr_tail) > _STDERR_TAIL_LINES:
                    self._stderr_tail.pop(0)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass  # best-effort diagnostics only — never let stderr draining itself break the reader

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
                    self._frames_decoded += len(frames)
                if len(buffer) > _MAX_BUFFER_BYTES:
                    logger.warning("stream reader buffer overflow, resetting", extra={"stream_url": self._log_url})
                    buffer = b""
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("stream reader loop crashed", extra={"stream_url": self._log_url})
        finally:
            # A reader that produced zero frames before its process ended almost
            # certainly failed to connect at all (wrong RTSP path/credentials/
            # transport) — that's exactly the failure mode that used to be
            # invisible. Surface ffmpeg's own stderr for it; a reader that had
            # been decoding fine and just got torn down normally (idle-reap,
            # shutdown) doesn't need its tail logged at all.
            if self._frames_decoded == 0 and self._stderr_tail:
                logger.warning(
                    "stream reader never decoded a frame before exiting",
                    extra={"stream_url": self._log_url, "ffmpeg_stderr": self._stderr_tail},
                )
            logger.info("stream reader stopped reading", extra={"stream_url": self._log_url})

    async def stop(self) -> None:
        async with self._lock:
            if self._reader_task is not None:
                self._reader_task.cancel()
                self._reader_task = None
            if self._stderr_task is not None:
                self._stderr_task.cancel()
                self._stderr_task = None
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

    def peek_frame(self, stream_url: str) -> bytes | None:
        """The reader's latest usable frame, WITHOUT starting one.

        get_frame() is the right call for anything that needs a picture:
        it starts a reader and waits for one. This is for asking "is this
        camera actually producing video right now?" — a question that
        must not itself create the reader whose output it is judging, and
        must not keep an unwatched camera's ffmpeg alive by touching it.
        """
        reader = self._readers.get(stream_url)
        return reader.get_frame() if reader else None

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


def peek_cached_frame(stream_url: str) -> bytes | None:
    """See StreamCache.peek_frame."""
    return _cache.peek_frame(stream_url)


def is_stream_known_broken(stream_url: str) -> bool:
    """Cheap, non-blocking check callers can poll between grab attempts —
    see _StreamReader.is_known_broken. Returns False for a URL with no
    reader yet (nothing to judge broken)."""
    reader = _cache._readers.get(stream_url)
    return reader is not None and reader.is_known_broken()


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


def active_stream_reader_count() -> int:
    """Active ffmpeg-backed readers held by the in-process stream cache."""
    return len(_cache._readers)
