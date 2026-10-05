"""Skaner ramkasini brauzerdagi video kadriga aniq moslash.

Brauzer videoni MediaMTX'ning HLS oqimidan ko'radi (u kamerani qayta
kodlaydi), AI esa kameradan to'g'ridan-to'g'ri o'qiydi. Ikkala yo'lning
kechikishi har xil va barqaror emas: 2026-09-24 da o'lchandi — farq bir
kamerada -1.7 s, boshqasida +4.9 s chiqdi. Qo'lda qo'yilgan bitta
tuzatish ramkani yurib ketayotgan odamdan bir necha yuz kengligicha
adashtirardi.

Shuning uchun farq avtomatik o'lchanadi: operator kamerani ko'rib
turganda vaqti-vaqti bilan brauzer oladigan HLS bo'lagi olinadi, uning
har kadri (EXT-X-PROGRAM-DATE-TIME + kadr o'rni bo'yicha vaqti bilan) AI
kadri bilan taqqoslanadi va eng o'xshash kadrning vaqti topiladi.
Sahnada harakat bo'lmasa o'lchov o'tkazib yuboriladi — lekin u holda
farqning ahamiyati ham yo'q: hech narsa qimirlamayapti.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime

import cv2
import httpx
import numpy as np

logger = logging.getLogger("app.live_clock")

_SIZE = (160, 90)
# Eng yaxshi moslik boshqalardan shunchalik ajralib turishi kerak (harakat bor).
_DISTINCT_RATIO = 0.8
_MOVING_STD = 12.0  # piksel kadrlar bo'yicha shunchalik o'zgarsa — "harakatli"
_MIN_MOVING_FRACTION = 0.004  # harakatli piksellar ulushi — bundan kam: sahna jim
_SEARCH_BEFORE = 4.0
_SEARCH_AFTER = 7.0
_WAIT_SECONDS = 12.0


@dataclass
class Segment:
    uri: str
    start: float  # epoch, soniya
    duration: float


def parse_media_playlist(text: str) -> tuple[str | None, list[Segment]]:
    """(init bo'lagi, bo'laklar). PROGRAM-DATE-TIME har bo'lakda bo'lmasa,
    oldingisidan EXTINF davomiyliklari qo'shib hisoblanadi."""
    init = None
    segments: list[Segment] = []
    clock: float | None = None
    duration = 0.0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-MAP:"):
            match = re.search(r'URI="([^"]+)"', line)
            init = match.group(1) if match else None
        elif line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            value = line.split(":", 1)[1].replace("Z", "+00:00")
            clock = datetime.fromisoformat(value).timestamp()
        elif line.startswith("#EXTINF:"):
            duration = float(line.split(":", 1)[1].split(",")[0])
        elif not line.startswith("#"):
            if clock is not None:
                segments.append(Segment(uri=line, start=clock, duration=duration))
                clock += duration
    return init, segments


def _gray(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    return cv2.GaussianBlur(cv2.resize(gray, _SIZE, interpolation=cv2.INTER_AREA), (3, 3), 0).astype(np.float32)


def decode_segment_frames(init: bytes, data: bytes, start: float) -> list[tuple[float, np.ndarray]]:
    """fMP4 bo'lakning kadrlari: (epoch vaqti, kichik kulrang tasvir)."""
    handle, path = tempfile.mkstemp(suffix=".mp4")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(init + data)
        capture = cv2.VideoCapture(path)
        frames: list[tuple[float, np.ndarray]] = []
        first_ms: float | None = None
        while True:
            ok, image = capture.read()
            if not ok:
                break
            position = float(capture.get(cv2.CAP_PROP_POS_MSEC))
            if first_ms is None:
                first_ms = position
            frames.append((start + (position - first_ms) / 1000.0, _gray(image)))
        capture.release()
        return frames
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def best_match_time(target: np.ndarray, frames: list[tuple[float, np.ndarray]]) -> float | None:
    """AI kadriga eng o'xshash HLS kadrining vaqti yoki None (jim sahna,
    ajralib turadigan moslik yo'q).

    Taqqoslash faqat kadrlar orasida O'ZGARADIGAN piksellarda: koridorda
    yurgan odam kadrning bir necha foizini egallaydi, qolgan qismdagi
    siqish shovqini esa butun kadr bo'yicha farqni bosib ketardi."""
    if len(frames) < 3:
        return None
    stack = np.stack([image for _, image in frames])
    moving = stack.std(axis=0) > _MOVING_STD
    if moving.mean() < _MIN_MOVING_FRACTION:
        return None
    # Yorug'lik/siqish farqini kamaytirish uchun har kadr o'z o'rtachasiga keltiriladi.
    target = target - target.mean()
    scores = [float(np.abs((image - image.mean()) - target)[moving].mean()) for image in stack]
    best = int(np.argmin(scores))
    if scores[best] > _DISTINCT_RATIO * float(np.median(scores)):
        return None
    return frames[best][0]


async def measure_offset(hls_url: str, frame_bytes: bytes, captured_at: float) -> float | None:
    """HLS vaqti minus AI vaqti (soniya) — bitta o'lchov yoki None."""
    image = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_REDUCED_COLOR_4)
    if image is None:
        return None
    target = await asyncio.to_thread(_gray, image)
    base = hls_url.rsplit("/", 1)[0] + "/"
    deadline = time.time() + _WAIT_SECONDS
    # Cookie'lar mijozda saqlanadi — MediaMTX sessiya tekshiruvi (?cookieCheck) o'tadi.
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        master = (await client.get(hls_url)).text
        media = next((line for line in master.splitlines() if line and not line.startswith("#")), None)
        if media is None:
            return None
        media_url = base + media if "://" not in media else media
        while True:
            init_uri, segments = parse_media_playlist((await client.get(media_url)).text)
            window = [
                s for s in segments
                if s.start + s.duration >= captured_at - _SEARCH_BEFORE and s.start <= captured_at + _SEARCH_AFTER
            ]
            covered = segments and segments[-1].start + segments[-1].duration >= captured_at + 2.0
            if (covered and window) or time.time() > deadline:
                break
            await asyncio.sleep(1.0)
        if not window or init_uri is None:
            return None
        init = (await client.get(base + init_uri)).content
        frames: list[tuple[float, np.ndarray]] = []
        for segment in window:
            data = (await client.get(base + segment.uri)).content
            frames.extend(await asyncio.to_thread(decode_segment_frames, init, data, segment.start))
    matched = await asyncio.to_thread(best_match_time, target, frames)
    return None if matched is None else matched - captured_at


class ClockCalibrator:
    """Kamera bo'yicha farq (ms), silliqlangan. Bir kamerada bir vaqtda
    bittadan ortiq o'lchov yo'q, oraliq — `interval` soniya."""

    def __init__(self, interval: float = 6.0) -> None:
        self.interval = interval
        self._offset: dict[str, float] = {}
        self._last: dict[str, float] = {}
        self._running: dict[str, asyncio.Task] = {}

    def offset_ms(self, camera_id: str) -> int | None:
        value = self._offset.get(camera_id)
        return None if value is None else int(round(value))

    def maybe_measure(self, camera_id: str, hls_url: str | None, frame_bytes: bytes, captured_at: float | None) -> None:
        if not hls_url or captured_at is None:
            return
        running = self._running.get(camera_id)
        if running is not None and not running.done():
            return
        now = time.monotonic()
        if now - self._last.get(camera_id, 0.0) < self.interval:
            return
        self._last[camera_id] = now

        async def run() -> None:
            try:
                seconds = await measure_offset(hls_url, frame_bytes, captured_at)
            except Exception:
                logger.warning("live clock measurement failed", exc_info=True, extra={"camera_id": camera_id})
                return
            if seconds is None:
                return
            measured = seconds * 1000.0
            previous = self._offset.get(camera_id)
            # Bitta noto'g'ri moslik ramkani sakratib yubormasin: silliqlash,
            # lekin birinchi o'lchov darhol qabul qilinadi.
            self._offset[camera_id] = measured if previous is None else previous * 0.6 + measured * 0.4
            logger.info(
                "live clock offset measured",
                extra={"camera_id": camera_id, "measured_ms": round(measured), "offset_ms": self.offset_ms(camera_id)},
            )

        self._running[camera_id] = asyncio.create_task(run(), name=f"live-clock:{camera_id}")


calibrator = ClockCalibrator()
