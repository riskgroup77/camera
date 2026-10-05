"""Yozuvdan kadr o'qish: NVR (RTSP playback / ISAPI download) yoki papka.

Hamma manba bir xil interfeysga ega: `clip(start, end, fps)` — oraliqdagi
kadrlarni (vaqti bilan) beradi. Dekodlash ffmpeg'da: `fps` filtri kadrlarni
teng oraliqda tanlaydi, shuning uchun n-kadrning vaqti `start + n / fps`
(RTSP playback eng yaqin kalit kadrdan boshlanadi — xatolik ~1 s,
kriteriyalar uchun ahamiyatsiz).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from app.crypto import decrypt
from app.services.nvr.isapi import IsapiClient, NvrError, RecordingSpan, format_nvr_time, merge_spans
from app.services.stream_cache import JpegSplitter
from app.timezone import INSTITUTE_TZ

logger = logging.getLogger("app.nvr")

FFMPEG = os.environ.get("FFMPEG_BINARY", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE_BINARY", "ffprobe")
_STDERR_TAIL = 15
_READ_CHUNK = 256 * 1024


@dataclass(frozen=True)
class Frame:
    at: datetime
    jpeg: bytes


class VideoReadError(Exception):
    """Oraliqni o'qib bo'lmadi (yozuv yo'q, ulanish uzildi, format)."""


def _redact(text: str) -> str:
    return re.sub(r"(rtsp://)[^@/\s]+@", r"\1***@", text)


def output_args(fps: float, max_side: int) -> list[str]:
    scale = f"scale='min({max_side},iw)':-2" if max_side > 0 else "null"
    return [
        "-an",
        "-sn",
        "-vf",
        f"fps={fps:g},{scale}",
        "-f",
        "image2pipe",
        "-c:v",
        "mjpeg",
        "-q:v",
        "3",
        "pipe:1",
    ]


async def ffmpeg_frames(
    input_args: list[str],
    *,
    start: datetime,
    duration: float,
    fps: float,
    max_side: int,
    timeout: float,
    feed: AsyncIterator[bytes] | None = None,
    should_stop: Callable[[], bool] | None = None,
    label: str = "",
) -> AsyncIterator[Frame]:
    """ffmpeg'ni ishga tushiradi va kadrlarni vaqti bilan beradi.

    Hech qanday kadr chiqmasa VideoReadError (stderr oxiri bilan). Vaqt
    chegarasi butun o'qishga — NVR oqimni to'xtatib qo'ysa vazifa abadiy
    kutmasin."""
    expected = max(1, int(duration * fps + 0.5))
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error"]
    if feed is None:
        cmd.append("-nostdin")
    cmd += [*input_args, "-t", f"{duration:.3f}", *output_args(fps, max_side)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if feed is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise VideoReadError("ffmpeg topilmadi") from exc

    stderr_tail: list[str] = []
    feed_error: list[BaseException] = []

    async def drain_stderr() -> None:
        assert proc.stderr is not None
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            stderr_tail.append(_redact(line.decode(errors="replace").strip()))
            del stderr_tail[:-_STDERR_TAIL]

    async def pump() -> None:
        assert proc.stdin is not None and feed is not None
        try:
            async for chunk in feed:
                proc.stdin.write(chunk)
                await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass  # ffmpeg kerakli kadrlarni olib, chiqib ketdi
        except Exception as exc:  # noqa: BLE001 — sababi xatoda aytiladi
            feed_error.append(exc)
        finally:
            try:
                proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass

    stderr_task = asyncio.create_task(drain_stderr())
    pump_task = asyncio.create_task(pump()) if feed is not None else None
    splitter = JpegSplitter()
    produced = 0
    deadline = time.monotonic() + timeout
    try:
        assert proc.stdout is not None
        while produced < expected:
            if should_stop is not None and should_stop():
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise VideoReadError(f"o'qish vaqti tugadi ({timeout:.0f} s){label}")
            try:
                chunk = await asyncio.wait_for(proc.stdout.read(_READ_CHUNK), remaining)
            except TimeoutError as exc:
                raise VideoReadError(f"o'qish vaqti tugadi ({timeout:.0f} s){label}") from exc
            if not chunk:
                break
            stopped = False
            for jpeg in splitter.feed(chunk):
                if should_stop is not None and should_stop():
                    stopped = True
                    break
                yield Frame(at=start + timedelta(seconds=produced / fps), jpeg=jpeg)
                produced += 1
                if produced >= expected:
                    break
            if stopped:
                break
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(proc.wait(), 10)
        except TimeoutError:
            pass
        if pump_task is not None:
            pump_task.cancel()
            await asyncio.gather(pump_task, return_exceptions=True)
        await asyncio.wait_for(asyncio.gather(stderr_task, return_exceptions=True), 5)
    if produced == 0:
        reason = "; ".join(line for line in stderr_tail if line)[-400:]
        if feed_error:
            reason = f"{feed_error[0]}; {reason}".strip("; ")
        raise VideoReadError(f"kadr olinmadi{label}: {reason or 'yozuv yo‘q'}")


def clip_output_args(height: int) -> list[str]:
    """Dalil klipi: brauzerda ochiladigan H.264 MP4, balandligi `height`
    gacha kichraytirilgan (4K H.265 yozuv 2 daqiqada ~10 MB bo'ladi)."""
    scale = f"scale=-2:'min({height},ih)'" if height > 0 else "null"
    return [
        "-an",
        "-sn",
        "-vf",
        f"{scale},format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "28",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
    ]


async def ffmpeg_export(
    input_args: list[str],
    out_path: Path,
    *,
    duration: float,
    height: int,
    timeout: float,
    feed: AsyncIterator[bytes] | None = None,
    label: str = "",
) -> None:
    """Oraliqni `out_path` ga MP4 qilib yozadi. Bo'sh/yo'q natija — VideoReadError."""
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"]
    if feed is None:
        cmd.append("-nostdin")
    cmd += [*input_args, "-t", f"{duration:.3f}", *clip_output_args(height), str(out_path)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if feed is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise VideoReadError("ffmpeg topilmadi") from exc

    async def pump() -> None:
        assert proc.stdin is not None and feed is not None
        try:
            async for chunk in feed:
                proc.stdin.write(chunk)
                await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            try:
                proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass

    pump_task = asyncio.create_task(pump()) if feed is not None else None
    try:
        _out, err = await asyncio.wait_for(proc.communicate() if feed is None else _wait_stderr(proc), timeout)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise VideoReadError(f"klip kesish vaqti tugadi ({timeout:.0f} s){label}") from exc
    finally:
        if pump_task is not None:
            pump_task.cancel()
            await asyncio.gather(pump_task, return_exceptions=True)
    if proc.returncode != 0 or not out_path.exists() or out_path.stat().st_size < 1024:
        reason = _redact((err or b"").decode(errors="replace").strip())[-400:]
        raise VideoReadError(f"klip kesilmadi{label}: {reason or 'yozuv yo‘q'}")


async def _wait_stderr(proc) -> tuple[None, bytes]:
    assert proc.stderr is not None
    err = await proc.stderr.read()
    await proc.wait()
    return None, err


class PlaybackSource:
    """Bitta kameraning yozuvi."""

    label = ""

    async def available(self, start: datetime, end: datetime) -> list[RecordingSpan] | None:
        """Oraliqda yozuv bor bo'laklar; None — bilib bo'lmadi (baribir urinib ko'riladi)."""
        return None

    async def export(self, start: datetime, end: datetime, out_path: Path, *, height: int, timeout: float) -> None:
        """Oraliqni video fayl (dalil klipi) qilib yozadi."""
        raise NotImplementedError

    def clip(
        self,
        start: datetime,
        end: datetime,
        fps: float,
        *,
        max_side: int,
        timeout: float,
        should_stop: Callable[[], bool] | None = None,
    ) -> AsyncIterator[Frame]:
        raise NotImplementedError


class RtspPlaybackSource(PlaybackSource):
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        channel: int,
        stream: str,
        template: str,
        local_time: bool,
        isapi: IsapiClient | None = None,
    ) -> None:
        self.host, self.port, self.channel, self.stream = host, port, channel, stream
        self.username, self.password = username, password
        self.template, self.local_time, self.isapi = template, local_time, isapi
        self.label = f" (NVR {host}, kanal {channel})"

    def url(self, start: datetime, end: datetime) -> str:
        path = self.template.format(
            channel=self.channel,
            stream=2 if self.stream == "sub" else 1,
            start=format_nvr_time(start, local_time=self.local_time, compact=True),
            end=format_nvr_time(end, local_time=self.local_time, compact=True),
        )
        auth = ""
        if self.username:
            auth = f"{quote(self.username, safe='')}:{quote(self.password or '', safe='')}@"
        return f"rtsp://{auth}{self.host}:{self.port}{path}"

    async def available(self, start: datetime, end: datetime) -> list[RecordingSpan] | None:
        if self.isapi is None:
            return None
        try:
            return await self.isapi.search_recordings(self.channel, self.stream, start, end)
        except NvrError as exc:
            logger.warning("NVR recording search failed", extra={"error": str(exc), "channel": self.channel})
            return None

    async def export(self, start, end, out_path, *, height, timeout):
        args = ["-rtsp_transport", "tcp", "-timeout", "15000000", "-i", self.url(start, end)]
        await ffmpeg_export(
            args, out_path, duration=(end - start).total_seconds(), height=height, timeout=timeout, label=self.label
        )

    async def clip(self, start, end, fps, *, max_side, timeout, should_stop=None):
        args = ["-rtsp_transport", "tcp", "-timeout", "15000000", "-i", self.url(start, end)]
        async for frame in ffmpeg_frames(
            args,
            start=start,
            duration=(end - start).total_seconds(),
            fps=fps,
            max_side=max_side,
            timeout=timeout,
            should_stop=should_stop,
            label=self.label,
        ):
            yield frame


class DownloadSource(RtspPlaybackSource):
    """ISAPI download: oraliq disk tezligida keladi, ffmpeg stdin orqali
    dekodlaydi. Yuklab olish ishlamasa (eski firmware) — RTSP playback."""

    async def export(self, start, end, out_path, *, height, timeout):
        assert self.isapi is not None
        try:
            await ffmpeg_export(
                ["-i", "pipe:0"],
                out_path,
                duration=(end - start).total_seconds(),
                height=height,
                timeout=timeout,
                feed=self.isapi.download(self.channel, self.stream, start, end),
                label=self.label,
            )
        except VideoReadError as exc:
            logger.info("ISAPI download clip failed, falling back to RTSP playback", extra={"error": str(exc)})
            await super().export(start, end, out_path, height=height, timeout=timeout)

    async def clip(self, start, end, fps, *, max_side, timeout, should_stop=None):
        assert self.isapi is not None
        produced = 0
        try:
            async for frame in ffmpeg_frames(
                ["-i", "pipe:0"],
                start=start,
                duration=(end - start).total_seconds(),
                fps=fps,
                max_side=max_side,
                timeout=timeout,
                feed=self.isapi.download(self.channel, self.stream, start, end),
                should_stop=should_stop,
                label=self.label,
            ):
                produced += 1
                yield frame
            return
        except VideoReadError as exc:
            if produced:
                raise
            logger.info("ISAPI download failed, falling back to RTSP playback", extra={"error": str(exc)})
        async for frame in super().clip(start, end, fps, max_side=max_side, timeout=timeout, should_stop=should_stop):
            yield frame


_FILE_NAME = re.compile(r"^(\d{8})[_T-]?(\d{6})")


@dataclass(frozen=True)
class RecordingFile:
    path: Path
    start: datetime
    end: datetime


async def probe_duration(path: Path) -> float | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return None
    out, _ = await proc.communicate()
    try:
        return float(out.decode().strip())
    except ValueError:
        return None


class FolderSource(PlaybackSource):
    """Eksport qilingan yozuvlar: `<base>/<kanal>/<YYYYMMDD>_<HHMMSS>.<ext>`
    (fayl nomidagi vaqt — institut mahalliy soati)."""

    _durations: dict[tuple[str, float], float] = {}

    def __init__(self, base_path: str, channel: int) -> None:
        self.directory = Path(base_path) / str(channel)
        self.label = f" ({self.directory})"

    async def files(self) -> list[RecordingFile]:
        if not self.directory.is_dir():
            return []
        found: list[tuple[datetime, Path]] = []
        for path in sorted(self.directory.iterdir()):
            match = _FILE_NAME.match(path.name)
            if not match or not path.is_file():
                continue
            try:
                naive = datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
            except ValueError:
                continue
            found.append((naive.replace(tzinfo=INSTITUTE_TZ).astimezone(timezone.utc), path))
        out: list[RecordingFile] = []
        for start, path in found:
            key = (str(path), path.stat().st_mtime)
            duration = self._durations.get(key)
            if duration is None:
                duration = await probe_duration(path)
                if duration is None:
                    continue
                self._durations[key] = duration
            out.append(RecordingFile(path=path, start=start, end=start + timedelta(seconds=duration)))
        return out

    async def available(self, start: datetime, end: datetime) -> list[RecordingSpan] | None:
        spans = [
            RecordingSpan(max(f.start, start), min(f.end, end)) for f in await self.files() if f.end > start and f.start < end
        ]
        return merge_spans(spans)

    async def export(self, start, end, out_path, *, height, timeout):
        # Oraliqni eng ko'p qoplagan bitta fayl (dalil uchun bir fayl yetadi).
        best, best_overlap = None, 0.0
        for recording in await self.files():
            overlap = (min(end, recording.end) - max(start, recording.start)).total_seconds()
            if overlap > best_overlap:
                best, best_overlap = recording, overlap
        if best is None:
            raise VideoReadError(f"oraliqda yozuv yo'q{self.label}")
        piece_start = max(start, best.start)
        await ffmpeg_export(
            ["-ss", f"{(piece_start - best.start).total_seconds():.3f}", "-i", str(best.path)],
            out_path,
            duration=best_overlap,
            height=height,
            timeout=timeout,
            label=self.label,
        )

    async def clip(self, start, end, fps, *, max_side, timeout, should_stop=None):
        produced = 0
        for recording in await self.files():
            if recording.end <= start or recording.start >= end:
                continue
            piece_start = max(start, recording.start)
            piece_end = min(end, recording.end)
            offset = (piece_start - recording.start).total_seconds()
            try:
                async for frame in ffmpeg_frames(
                    ["-ss", f"{offset:.3f}", "-i", str(recording.path)],
                    start=piece_start,
                    duration=(piece_end - piece_start).total_seconds(),
                    fps=fps,
                    max_side=max_side,
                    timeout=timeout,
                    should_stop=should_stop,
                    label=self.label,
                ):
                    produced += 1
                    yield frame
            except VideoReadError:
                logger.info("recording file piece yielded no frames", extra={"path": str(recording.path)})
        if produced == 0:
            raise VideoReadError(f"oraliqda yozuv yo'q{self.label}")


def source_for(nvr, camera) -> PlaybackSource:
    """NvrDevice + Camera -> manba. Kanal bog'lanmagan bo'lsa ValueError."""
    if camera.nvr_channel is None:
        raise ValueError("kamera NVR kanaliga bog'lanmagan")
    if nvr.kind == "fayl":
        if not nvr.base_path:
            raise ValueError("NVR papkasi ko'rsatilmagan")
        return FolderSource(nvr.base_path, camera.nvr_channel)
    if not nvr.ip:
        raise ValueError("NVR IP manzili ko'rsatilmagan")
    password = decrypt(nvr.password) if nvr.password else None
    isapi = IsapiClient(
        host=nvr.ip, port=nvr.http_port, username=nvr.username, password=password, local_time=nvr.local_time
    )
    cls = DownloadSource if nvr.fetch_mode == "download" else RtspPlaybackSource
    return cls(
        host=nvr.ip,
        port=nvr.rtsp_port,
        username=nvr.username,
        password=password,
        channel=camera.nvr_channel,
        stream=nvr.stream,
        template=nvr.rtsp_path_template,
        local_time=nvr.local_time,
        isapi=isapi,
    )


def isapi_for(nvr) -> IsapiClient:
    return IsapiClient(
        host=nvr.ip or "",
        port=nvr.http_port,
        username=nvr.username,
        password=decrypt(nvr.password) if nvr.password else None,
        local_time=nvr.local_time,
    )
