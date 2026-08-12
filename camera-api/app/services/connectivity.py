"""Real camera connectivity testing — replaces the frontend's old
Math.random()-based simulation (see camera/src/components/admin/AddCameraModal.tsx)
with genuine network checks.

Two stages:
  1. TCP connect to ip:port — proves the device is reachable at all.
  2. RTSP handshake via `ffprobe` — proves an actual video stream can be
     negotiated, not just that *something* is listening on the port.

Stage 2 requires ffprobe (part of the FFmpeg suite) to be on PATH.
"""

import asyncio
import json
import shutil
import time

from app.rtsp import build_rtsp_url
from app.schemas.camera import ConnectionTestOut

TCP_TIMEOUT_SECONDS = 3.0
RTSP_PROBE_TIMEOUT_SECONDS = 6.0


async def tcp_check(ip: str, port: int) -> tuple[bool, float]:
    """Public alias of the TCP-reachability half of test_camera_connection()
    — used by app/jobs/camera_health.py's periodic sweep, which deliberately
    skips the heavier ffprobe RTSP handshake (stage 2) to stay cheap enough
    to run every camera_health_interval_seconds across every camera."""
    return await _tcp_check(ip, port)


async def _tcp_check(ip: str, port: int) -> tuple[bool, float]:
    start = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=TCP_TIMEOUT_SECONDS
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True, (time.monotonic() - start) * 1000
    except (TimeoutError, OSError):
        return False, (time.monotonic() - start) * 1000


async def _rtsp_probe(url: str) -> tuple[bool, str | None]:
    """Runs ffprobe against the RTSP URL and returns (success, description)."""
    cmd = [
        "ffprobe",
        "-rtsp_transport", "tcp",
        "-timeout", str(int(RTSP_PROBE_TIMEOUT_SECONDS * 1_000_000)),  # microseconds
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,avg_frame_rate",
        "-of", "json",
        url,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=RTSP_PROBE_TIMEOUT_SECONDS + 2)
    except (TimeoutError, FileNotFoundError):
        return False, None

    if proc.returncode != 0:
        return False, stderr.decode(errors="ignore").strip()[:300] or None

    try:
        data = json.loads(stdout.decode(errors="ignore"))
        streams = data.get("streams") or []
        if not streams:
            return False, "Video oqim topilmadi"
        s = streams[0]
        desc = f"{s.get('codec_name', '?')} {s.get('width', '?')}x{s.get('height', '?')} @ {s.get('avg_frame_rate', '?')}"
        return True, desc
    except (json.JSONDecodeError, KeyError, IndexError):
        return False, None


async def test_camera_connection(
    ip: str,
    port: int = 554,
    rtsp_path: str | None = None,
    username: str | None = None,
    password: str | None = None,
) -> ConnectionTestOut:
    tcp_ok, latency_ms = await _tcp_check(ip, port)
    if not tcp_ok:
        return ConnectionTestOut(
            success=False,
            message=f"{ip}:{port} manziliga TCP ulanish o'rnatilmadi — kamera ochiq/tarmoqda emas yoki port noto'g'ri",
            method="tcp-only",
            latency_ms=round(latency_ms),
        )

    if shutil.which("ffprobe") is None:
        return ConnectionTestOut(
            success=True,
            message=(
                f"{ip}:{port} port ochiq (TCP ulanish muvaffaqiyatli), lekin RTSP oqim "
                "tekshiruvi o'tkazilmadi — serverda ffprobe topilmadi"
            ),
            method="tcp-only",
            latency_ms=round(latency_ms),
        )

    url = build_rtsp_url(ip, port, rtsp_path, username, password)
    rtsp_ok, info = await _rtsp_probe(url)

    if rtsp_ok:
        return ConnectionTestOut(
            success=True,
            message="RTSP oqim muvaffaqiyatli aniqlandi — kamera video uzatishga tayyor",
            method="rtsp-probe",
            latency_ms=round(latency_ms),
            video_info=info,
        )

    return ConnectionTestOut(
        success=False,
        message=(
            f"{ip}:{port} port ochiq, lekin RTSP handshake muvaffaqiyatsiz "
            f"({info or 'javob bermadi'}) — RTSP yo'li, login yoki parolni tekshiring"
        ),
        method="rtsp-probe",
        latency_ms=round(latency_ms),
    )
