"""Kirish/perimetr kameralarining oqimlarini ffprobe bilan o'lchaydi.

NEGA KERAK. 2026-09-17 da 11 ta kirish kamerasidan 7 tasining asosiy
oqimidan (Channels/101) AI kun bo'yi birorta kadr ololmagan. Taxminiy
sabab — H.265+ ("smart codec") yoki juda uzun kalit kadr oralig'i:
kesh faqat kalit kadrlarni dekodlasa (STREAM_CACHE_KEYFRAMES_ONLY), kalit
kadr kelguncha kadr "eskiradi". Bu skript taxminni o'lchov bilan
tasdiqlaydi yoki rad etadi.

Har bir kamera uchun asosiy va substream bo'yicha: kodek, o'lcham, fps va
~12 soniya ichidagi kalit kadrlar oralig'i. Login/parol chiqarilmaydi.

Ishga tushirish (serverda, API konteyneri ichida — ffprobe va bazaga
ulanish shu yerda bor):

    docker compose exec -T api python scripts/probe_camera_streams.py
    docker compose exec -T api python scripts/probe_camera_streams.py --all   # barcha faol kameralar
"""

import argparse
import asyncio
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import or_, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Camera  # noqa: E402
from app.services.frame_grabber import rtsp_url_for_camera  # noqa: E402

READ_SECONDS = 12
PROBE_TIMEOUT_SECONDS = READ_SECONDS + 20
CONCURRENCY = 4


async def _run(cmd: list[str]) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=PROBE_TIMEOUT_SECONDS)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "timeout"
    text = stdout.decode(errors="replace") if proc.returncode == 0 else stderr.decode(errors="replace")
    return proc.returncode, text


def _base(url: str) -> list[str]:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0"]
    if url.startswith("rtsp://"):
        cmd[1:1] = ["-rtsp_transport", "tcp", "-timeout", "8000000"]
    return cmd


async def probe(url: str) -> dict:
    code, text = await _run(
        _base(url) + ["-show_entries", "stream=codec_name,profile,width,height,avg_frame_rate", "-of", "json", url]
    )
    if code != 0:
        return {"error": text.strip().splitlines()[-1][:120] if text.strip() else f"ffprobe exit {code}"}
    streams = json.loads(text).get("streams") or []
    if not streams:
        return {"error": "video oqimi yo'q"}
    info = streams[0]

    code, text = await _run(
        _base(url)
        + [
            "-read_intervals", f"%+{READ_SECONDS}",
            "-show_entries", "packet=pts_time,dts_time,flags",
            "-of", "csv=p=0",
            url,
        ]
    )
    packets, keyframes, untimed_keyframes = parse_packets(text) if code == 0 else (0, [], 0)
    return {
        "codec": f"{info.get('codec_name')} {info.get('profile') or ''}".strip(),
        "size": f"{info.get('width')}x{info.get('height')}",
        "fps": info.get("avg_frame_rate"),
        "packets": packets,
        "keyframes": len(keyframes) + untimed_keyframes,
        "gop_seconds": keyframe_interval(keyframes, untimed_keyframes),
    }


def parse_packets(text: str) -> tuple[int, list[float], int]:
    """ffprobe `packet=pts_time,dts_time,flags` CSV -> (paketlar, kalit kadr vaqtlari, vaqtsiz kalit kadrlar).

    Ba'zi kameralar vaqt belgisini bermaydi — ffprobe "N/A" yozadi (2026-09-18
    da serverda skript shundan yiqilgan). Unda dts_time olinadi, u ham
    bo'lmasa kalit kadr faqat sanaladi."""
    packets = 0
    keyframes: list[float] = []
    untimed = 0
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        packets += 1
        if "K" not in parts[-1]:
            continue
        moment = next((float(value) for value in parts[:-1] if _is_number(value)), None)
        if moment is None:
            untimed += 1
        else:
            keyframes.append(moment)
    return packets, keyframes, untimed


def keyframe_interval(keyframes: list[float], untimed: int) -> float | None:
    gaps = [b - a for a, b in zip(keyframes, keyframes[1:], strict=False) if b > a]
    if gaps:
        return round(statistics.median(gaps), 2)
    total = len(keyframes) + untimed
    # Vaqt yo'q: o'qilgan oynaga necha kalit kadr sig'gani bo'yicha taxmin.
    return round(READ_SECONDS / total, 2) if total >= 2 else None


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _describe(result: dict) -> str:
    if "error" in result:
        return f"XATO: {result['error']}"
    gop = result["gop_seconds"]
    if gop is None:
        gop_text = f"kalit kadr {READ_SECONDS} s ichida {result['keyframes']} ta (oraliq o'lchanmadi)"
    else:
        gop_text = f"kalit kadr har {gop} s"
    return f"{result['codec']}, {result['size']}, {result['fps']} fps, {gop_text}"


async def main(all_cameras: bool) -> int:
    async with SessionLocal() as db:
        stmt = select(Camera).where(Camera.status == "faol").order_by(Camera.name)
        if not all_cameras:
            stmt = stmt.where(or_(Camera.is_entrance, Camera.is_perimeter))
        cameras = (await db.execute(stmt)).scalars().all()

    print(
        f"{len(cameras)} ta kamera. keyframes_only={settings.stream_cache_keyframes_only}, "
        f"kesh maks. yoshi={settings.stream_cache_max_age_seconds} s, "
        f"asosiy oqim ishlatiladi={settings.ai_entrance_use_main_stream}\n"
    )
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def safe_probe(url: str) -> dict:
        # Bitta kameradagi kutilmagan javob butun hisobotni to'xtatmasin.
        try:
            return await probe(url)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"[:120]}

    async def one(camera: Camera) -> str:
        async with semaphore:
            main_result, sub_result = await asyncio.gather(
                safe_probe(rtsp_url_for_camera(camera, substream=False)),
                safe_probe(rtsp_url_for_camera(camera, substream=True)),
            )
        warning = ""
        gop = main_result.get("gop_seconds")
        if "error" not in main_result and (gop is None or gop > settings.stream_cache_max_age_seconds):
            warning = "\n    ! asosiy oqimning kalit kadrlari kesh yoshidan siyrak — faqat kalit kadr rejimida kadr eskiradi"
        return (
            f"{camera.name} ({camera.ip})\n"
            f"    asosiy : {_describe(main_result)}\n"
            f"    sub    : {_describe(sub_result)}{warning}"
        )

    for line in await asyncio.gather(*(one(camera) for camera in cameras)):
        print(line)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="faqat kirish/perimetr emas, barcha faol kameralar")
    raise SystemExit(asyncio.run(main(parser.parse_args().all)))
