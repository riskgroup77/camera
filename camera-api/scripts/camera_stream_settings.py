"""Kamera oqim sozlamalarini Hikvision ISAPI orqali tekshirish va to'g'rilash.

NEGA KERAK. 2026-09-18 dagi o'lchov (scripts/probe_camera_streams.py):
kameralar kalit kadrni 4-8 s da bir beradi, AI esa faqat kalit kadrlarni
dekodlaydi (STREAM_CACHE_KEYFRAMES_ONLY) — ya'ni 4-8 s da bitta kadr ko'radi.
Odam eshikdan 2-3 s da o'tadi. Ikki kadrli tekshiruvlar (jang, tartib,
yong'in) "1 s oraliq" deb hisoblaydi, aslida kadrlar 4-8 s oraliqda. Qo'shimcha
oqim H.265 bo'lgani uchun brauzerga ko'rsatish har safar transkod talab qiladi.

Maqsadli qiymatlar:
  * asosiy va qo'shimcha oqim: kalit kadr oralig'i (GovLength) = fps, ya'ni
    har soniyada bitta kalit kadr;
  * H.264+/H.265+ ("Smart Codec") o'chiq — u kalit kadr oralig'ini o'zi
    cho'zib yuboradi;
  * qo'shimcha oqim (102) kodeki H.264 (--sub-h265-qolsin bilan o'chiriladi).

XAVFSIZLIK. Standart rejim — faqat o'qish: har kameraning hozirgi va
maqsadli qiymatlari chiqariladi, hech narsa yozilmaydi. --qollash bilan
yoziladi. Login/parol hech qachon chiqarilmaydi. Kamera o'zgarishni rad
etsa (masalan H.264 ni qo'llamasa) — xabari ko'rsatiladi, boshqa
kameralar davom etadi.

Ishga tushirish (serverda, API konteyneri ichida — baza va kamera tarmog'i shu yerda):

    C="docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.mediamtx-shard.yml"
    sudo $C exec -T api python scripts/camera_stream_settings.py                 # faqat ko'rish
    sudo $C exec -T api python scripts/camera_stream_settings.py --ip 192.168.0.107   # bitta kamera
    sudo $C exec -T api python scripts/camera_stream_settings.py --qollash       # yozish
    sudo $C exec -T api python scripts/camera_stream_settings.py --faqat-sub --qollash   # xona kameralari

--faqat-sub — faqat qo'shimcha oqim (102): H.264 va GOP=fps. Asosiy oqimga
(xona kameralarida hali AI uchun ishlatilmaydi, yozuv esa NVR'da) tegilmaydi.
Substream H.264 bo'lgach, MEDIAMTX_RELAY_PROBE_CODEC=true brauzerga uni
transkodsiz uzatadi (app/services/video_gateway.py) — MediaMTX'dagi ffmpeg
enkoderlari o'z-o'zidan kamayadi.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.crypto import decrypt  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Camera  # noqa: E402

CHANNELS = {"asosiy": "101", "sub": "102"}
TIMEOUT_SECONDS = 8.0
CONCURRENCY = 4


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(root: ET.Element, *path: str) -> ET.Element | None:
    """Nomlar maydoni (xmlns) va harf kattaligidan qat'i nazar yo'l bo'yicha
    element — firmware versiyalari ver10/ver20 va SmartCodec/smartCodec deb yozadi."""
    node: ET.Element | None = root
    for name in path:
        if node is None:
            return None
        node = next((child for child in node if _local(child.tag).lower() == name.lower()), None)
    return node


@dataclass
class StreamState:
    codec: str | None = None
    width: str | None = None
    height: str | None = None
    fps: float | None = None
    gov: int | None = None
    smart: str | None = None  # "true"/"false"/None (element yo'q)

    def describe(self) -> str:
        fps = f"{self.fps:g}" if self.fps else "?"
        smart = {"true": "yoqiq", "false": "o'chiq"}.get(self.smart or "", "yo'q")
        return (
            f"{self.codec or '?'} {self.width or '?'}x{self.height or '?'} {fps}fps "
            f"GOP={self.gov if self.gov is not None else '?'} smart={smart}"
        )


def read_state(root: ET.Element) -> StreamState:
    video = _find(root, "Video")
    state = StreamState()
    if video is None:
        return state
    text = lambda *path: (_find(video, *path).text or "").strip() if _find(video, *path) is not None else None  # noqa: E731
    state.codec = text("videoCodecType")
    state.width = text("videoResolutionWidth")
    state.height = text("videoResolutionHeight")
    raw_fps = text("maxFrameRate")
    if raw_fps and raw_fps.isdigit():
        state.fps = int(raw_fps) / 100  # ISAPI fps*100 da beradi: 2500 = 25
    raw_gov = text("GovLength")
    if raw_gov and raw_gov.isdigit():
        state.gov = int(raw_gov)
    state.smart = (text("SmartCodec", "enabled") or "").lower() or None
    return state


@dataclass
class Plan:
    changes: list[str] = field(default_factory=list)


def _set(video: ET.Element, name: str, value: str) -> bool:
    node = _find(video, name)
    if node is None or (node.text or "").strip() == value:
        return False
    node.text = value
    return True


def plan_resolution(root: ET.Element, caps_text: str, width: int, height: int, min_kbps: int) -> list[str]:
    """Qo'shimcha oqimni katta o'lchamga (masalan 1280x720) ko'tarish — kamera
    imkoniyatlari (capabilities) ruxsat bersa. Yuz tanish uchun: 640x360 da
    auditoriyadagi yuzlar 8–20 px, tanish uchun 40 px kerak (2026-09-19 o'lchovi)."""
    import re

    video = _find(root, "Video")
    if video is None:
        return []
    widths = re.search(r'videoResolutionWidth[^>]*opt="([^"]+)"', caps_text)
    heights = re.search(r'videoResolutionHeight[^>]*opt="([^"]+)"', caps_text)
    if not widths or not heights or str(width) not in widths.group(1).split(",") or str(height) not in heights.group(1).split(","):
        return [f"! {width}x{height} qo'llab-quvvatlanmaydi — tegilmaydi"]
    changes: list[str] = []
    state = read_state(root)
    if _set(video, "videoResolutionWidth", str(width)) | _set(video, "videoResolutionHeight", str(height)):
        changes.append(f"o'lcham {state.width}x{state.height} -> {width}x{height}")
    for name in ("vbrUpperCap", "constantBitRate"):
        node = _find(video, name)
        if node is not None and (node.text or "").strip().isdigit() and int(node.text) < min_kbps:
            changes.append(f"{name} {node.text} -> {min_kbps} kbps")
            node.text = str(min_kbps)
    return changes


def plan_changes(root: ET.Element, *, want_h264: bool) -> Plan:
    """XML ni JOYIDA maqsadli qiymatlarga keltiradi va nima o'zgarganini qaytaradi."""
    plan = Plan()
    video = _find(root, "Video")
    if video is None:
        plan.changes.append("! Video bo'limi yo'q — tegilmaydi")
        return plan
    state = read_state(root)

    if want_h264 and state.codec and state.codec.upper() != "H.264":
        _find(video, "videoCodecType").text = "H.264"
        plan.changes.append(f"kodek {state.codec} -> H.264")

    fps = int(round(state.fps)) if state.fps else None
    gov = _find(video, "GovLength")
    if fps and gov is not None and state.gov != fps:
        gov.text = str(fps)
        plan.changes.append(f"GOP {state.gov} -> {fps} (har soniyada kalit kadr)")

    smart = _find(video, "SmartCodec", "enabled")
    if smart is not None and (smart.text or "").strip().lower() == "true":
        smart.text = "false"
        plan.changes.append("Smart Codec (H.264+/H.265+) -> o'chiq")
    return plan


def to_xml(root: ET.Element) -> bytes:
    """Kameraga qaytariladigan XML — asl ko'rinishida (standart xmlns bilan).

    ElementTree standart bo'yicha nomlar maydonini `ns0:` prefiksiga
    aylantiradi (`<ns0:GovLength>`). 2026-09-18 da 19 ta kamera shunday
    XML ga "OK" deb javob berdi, lekin hech bir sozlamani qo'llamadi —
    firmware prefiksli elementlarni tanimaydi va jimgina e'tiborsiz
    qoldiradi."""
    tag = root.tag
    if tag.startswith("{"):
        ET.register_namespace("", tag[1:].split("}", 1)[0])
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def not_applied(wanted: StreamState, actual: StreamState) -> list[str]:
    """Yozilgandan keyin qayta o'qilgan holatda nima qo'llanmay qolgan."""
    missing: list[str] = []
    if wanted.codec and (actual.codec or "").upper() != wanted.codec.upper():
        missing.append(f"kodek {actual.codec}")
    if wanted.gov is not None and actual.gov != wanted.gov:
        missing.append(f"GOP {actual.gov}")
    if wanted.width and actual.width != wanted.width:
        missing.append(f"o'lcham {actual.width}x{actual.height}")
    if wanted.smart == "false" and actual.smart == "true":
        missing.append("Smart Codec hali yoqiq")
    return missing


def _response_message(text: str) -> str:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return text.strip()[:120]
    status = _find(root, "statusString")
    sub = _find(root, "subStatusCode")
    return " / ".join(x.text.strip() for x in (status, sub) if x is not None and x.text)


def channels_for(args: argparse.Namespace) -> dict[str, str]:
    """--faqat-sub: faqat qo'shimcha oqim (102)."""
    if getattr(args, "faqat_sub", False):
        return {"sub": CHANNELS["sub"]}
    return dict(CHANNELS)


async def handle_camera(camera: Camera, args: argparse.Namespace, semaphore: asyncio.Semaphore) -> list[str]:
    lines = [f"{camera.ip:<16} {camera.name}"]
    username = decrypt(camera.rtsp_username) if camera.rtsp_username else None
    password = decrypt(camera.rtsp_password) if camera.rtsp_password else None
    if not username or not password:
        return lines + ["    ! login/parol saqlanmagan — o'tkazib yuborildi"]
    base = f"http://{camera.ip}:{args.port}"
    async with semaphore, httpx.AsyncClient(
        auth=httpx.DigestAuth(username, password), timeout=TIMEOUT_SECONDS
    ) as client:
        for label, channel in channels_for(args).items():
            url = f"{base}/ISAPI/Streaming/channels/{channel}"
            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                lines.append(f"    {label:<7} ! ulanib bo'lmadi: {type(exc).__name__}")
                continue
            if response.status_code != 200:
                lines.append(f"    {label:<7} ! HTTP {response.status_code} {_response_message(response.text)}")
                continue
            try:
                root = ET.fromstring(response.content)
            except ET.ParseError:
                lines.append(f"    {label:<7} ! javobni o'qib bo'lmadi")
                continue
            before = read_state(root).describe()
            plan = plan_changes(root, want_h264=(label == "sub" and not args.sub_h265_qolsin))
            if label == "sub" and args.sub_olcham:
                width, height = (int(x) for x in args.sub_olcham.lower().split("x"))
                try:
                    caps = await client.get(f"{url}/capabilities")
                    plan.changes.extend(plan_resolution(root, caps.text, width, height, args.sub_bitrate))
                except httpx.HTTPError as exc:
                    plan.changes.append(f"! imkoniyatlarni o'qib bo'lmadi: {type(exc).__name__}")
                if all(c.startswith("!") for c in plan.changes):
                    lines.append(f"    {label:<7} {before}  " + "; ".join(plan.changes or ["— to'g'ri"]))
                    continue
            if not plan.changes:
                lines.append(f"    {label:<7} {before}  — to'g'ri")
                continue
            lines.append(f"    {label:<7} {before}")
            lines.extend(f"            -> {change}" for change in plan.changes)
            if not args.qollash:
                continue
            wanted = read_state(root)
            try:
                put = await client.put(url, content=to_xml(root), headers={"Content-Type": "application/xml"})
            except httpx.HTTPError as exc:
                lines.append(f"            ! yozib bo'lmadi: {type(exc).__name__}")
                continue
            message = _response_message(put.text)
            if put.status_code != 200:
                lines.append(f"            ! RAD ETILDI: {message or put.status_code}")
                continue
            # "OK" javobining o'ziga ishonilmaydi — sozlama qayta o'qiladi.
            try:
                check = await client.get(url)
                missing = not_applied(wanted, read_state(ET.fromstring(check.content)))
            except (httpx.HTTPError, ET.ParseError) as exc:
                lines.append(f"            YOZILDI ({message}), lekin qayta o'qib bo'lmadi: {type(exc).__name__}")
                continue
            if missing:
                lines.append(f"            ! KAMERA QO'LLAMADI ({message}): {', '.join(missing)}")
            else:
                lines.append(f"            QO'LLANDI (qayta o'qib tasdiqlandi){' — ' + message if message else ''}")
    return lines


async def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kamera oqim sozlamalari (ISAPI): GOP=fps, Smart Codec o'chiq, sub H.264")
    parser.add_argument("--ip", action="append", default=[], help="faqat shu IP (bir necha marta berish mumkin)")
    parser.add_argument("--faqat-kirish", action="store_true", help="faqat kirish/chiqish va perimetr kameralari")
    parser.add_argument(
        "--faqat-sub", action="store_true", help="faqat qo'shimcha oqim (102) — asosiy oqimga tegilmaydi"
    )
    parser.add_argument(
        "--xonalar", action="store_true", help="faqat kirish/chiqish/perimetr BO'LMAGAN kameralar (xona, koridor)"
    )
    parser.add_argument("--port", type=int, default=80, help="kameraning veb (ISAPI) porti, standart 80")
    parser.add_argument("--sub-h265-qolsin", action="store_true", help="qo'shimcha oqim kodekini o'zgartirmaslik")
    parser.add_argument("--sub-olcham", help="qo'shimcha oqim o'lchami, masalan 1280x720 (kamera qo'llasa)")
    parser.add_argument("--sub-bitrate", type=int, default=1536, help="--sub-olcham bilan: bitreyt kamida shuncha kbps")
    parser.add_argument("--qollash", action="store_true", help="o'zgarishlarni kameralarga yozish (standart: faqat ko'rish)")
    args = parser.parse_args(argv)

    async with SessionLocal() as db:
        stmt = select(Camera).where(Camera.status == "faol").order_by(Camera.ip)
        cameras = list((await db.execute(stmt)).scalars().all())
    if args.ip:
        wanted = set(args.ip)
        cameras = [camera for camera in cameras if camera.ip in wanted]
    if args.faqat_kirish and args.xonalar:
        print("--faqat-kirish va --xonalar birga berilmaydi.")
        return 2
    if args.faqat_kirish:
        cameras = [c for c in cameras if c.is_entrance or c.is_exit or c.is_perimeter]
    if args.xonalar:
        cameras = [c for c in cameras if not (c.is_entrance or c.is_exit or c.is_perimeter)]
    if not cameras:
        print("Mos kamera topilmadi.")
        return 1

    semaphore = asyncio.Semaphore(CONCURRENCY)
    results = await asyncio.gather(*(handle_camera(camera, args, semaphore) for camera in cameras))
    for lines in results:
        print("\n".join(lines))
    print()
    if args.qollash:
        print("Yozildi. Tekshirish: scripts/probe_camera_streams.py (kalit kadr oralig'i ~1 s bo'lishi kerak).")
    else:
        print(f"{len(cameras)} ta kamera tekshirildi, hech narsa yozilmadi. Yozish uchun --qollash qo'shing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
