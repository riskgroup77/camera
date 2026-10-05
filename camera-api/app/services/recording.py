"""Video arxivi — MediaMTX yozuvi va playback server.

NIMA UCHUN MediaMTX. Kameralarda xotira kartasi yo'q (ISAPI
ContentMgmt/Storage bo'sh, 2026-09-24), NVR ham tizimga ulanmagan — arxiv
bo'lmasa operator hodisa kadridan boshqa hech narsa ko'ra olmaydi.
MediaMTX (v1.20) oqimni o'zi fMP4 bo'laklariga yozadi va playback server
(:9996) orqali /list (qaysi oraliqlar bor) va /get (oraliqni MP4 qilib
berish) xizmatini ko'rsatadi — qo'shimcha dastur kerak emas.

HAJM. 95 ta substream jami ~52 Mbit/s (o'lchangan) — soatiga ~23,5 GB.
Ajratilgan ~100 GB → barcha kameralar uchun oxirgi `recording_retention_hours`
(standart 4) soat. Muhim lahzalar hodisa klipi sifatida MinIO'da
`event_clip_retention_days` kun saqlanadi (app/jobs/event_clips.py).

YOZUV YO'LI ALOHIDA. Jonli ko'rish yo'li (cam-<id>) talab bo'yicha
ochiladi va H.265 kameralarda brauzer uchun transkod qilinadi. Yozuv
uchun `rec-<id>` yo'li kameraning substream'ini TO'G'RIDAN-TO'G'RI,
transkodsiz va doimiy (sourceOnDemand: false) oladi — CPU sarflanmaydi,
yozuvda uzilish bo'lmaydi.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx

from app.config import settings
from app.services.video_gateway import _shard_for, _upsert_path

logger = logging.getLogger("app.recording")


def rec_path_name(camera_id: str) -> str:
    return f"rec-{camera_id}"


def recording_payload(rtsp_url: str) -> dict:
    return {
        "source": rtsp_url,
        "rtspTransport": "tcp",
        "sourceOnDemand": False,
        "record": True,
        "recordPath": "/recordings/%path/%Y-%m-%d_%H-%M-%S-%f",
        "recordFormat": "fmp4",
        # Kichik bo'lak — eski yozuv bir tekis o'chadi, disk "sakramaydi".
        "recordSegmentDuration": f"{max(1, settings.recording_segment_minutes)}m",
        "recordDeleteAfter": f"{max(1, settings.recording_retention_hours)}h",
    }


def playback_base(camera_id: str) -> str:
    """Kamera yo'li turgan MediaMTX shard'ining playback manzili."""
    api = urlsplit(_shard_for(camera_id).api_url)
    host = api.hostname or "localhost"
    return urlunsplit((api.scheme or "http", f"{host}:{settings.mediamtx_playback_port}", "", "", ""))


async def register_recording(camera_id: str, rtsp_url: str) -> None:
    shard = _shard_for(camera_id)
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await _upsert_path(client, shard.api_url, rec_path_name(camera_id), recording_payload(rtsp_url))
        except httpx.HTTPError as exc:
            logger.error("recording registration failed", extra={"camera_id": camera_id, "error": str(exc)})


async def unregister_recording(camera_id: str) -> None:
    """Yozuv yo'lini o'chiradi (mavjud bo'lmasa — jim). Diskdagi eski
    bo'laklar recordDeleteAfter bo'yicha o'z-o'zidan tozalanmaydi, lekin
    yozuv to'xtaydi."""
    shard = _shard_for(camera_id)
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            existing = await client.get(f"{shard.api_url}/v3/config/paths/get/{rec_path_name(camera_id)}")
            if existing.status_code == 200:
                await client.delete(f"{shard.api_url}/v3/config/paths/delete/{rec_path_name(camera_id)}")
        except httpx.HTTPError as exc:
            logger.warning("recording unregister failed", extra={"camera_id": camera_id, "error": str(exc)})


def _rfc3339(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def list_segments(camera_id: str, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """[start, end] ichidagi yozilgan oraliqlar (bir-biriga ulashganlari
    MediaMTX'ning o'zida birlashtirilgan). Yozuv bo'lmasa — bo'sh ro'yxat."""
    query = urlencode({"path": rec_path_name(camera_id), "start": _rfc3339(start), "end": _rfc3339(end)})
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{playback_base(camera_id)}/list?{query}")
        except httpx.HTTPError as exc:
            logger.warning("playback list failed", extra={"camera_id": camera_id, "error": str(exc)})
            return []
    if resp.status_code != 200:
        return []
    ranges: list[tuple[datetime, datetime]] = []
    for item in resp.json():
        try:
            begin = _parse_time(item["start"])
            ranges.append((begin, begin + timedelta(seconds=float(item["duration"]))))
        except (KeyError, TypeError, ValueError):
            continue
    return ranges


def get_url(camera_id: str, start: datetime, duration_seconds: float) -> str:
    """MediaMTX /get — oraliqni MP4 (fragmentlangan) qilib beradi."""
    query = urlencode(
        {
            "path": rec_path_name(camera_id),
            "start": _rfc3339(start),
            "duration": f"{max(1.0, duration_seconds):.0f}s",
            "format": "mp4",
        }
    )
    return f"{playback_base(camera_id)}/get?{query}"


async def fetch_clip(camera_id: str, start: datetime, duration_seconds: float, *, max_bytes: int) -> bytes | None:
    """Qisqa oraliqni butunlay yuklab oladi (hodisa klipi uchun)."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            async with client.stream("GET", get_url(camera_id, start, duration_seconds)) as resp:
                if resp.status_code != 200:
                    return None
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        return None
                    chunks.append(chunk)
                return b"".join(chunks) or None
        except httpx.HTTPError as exc:
            logger.warning("playback clip fetch failed", extra={"camera_id": camera_id, "error": str(exc)})
            return None
