"""Hikvision NVR ISAPI mijozi — kanal ro'yxati, yozuv qidiruvi, yuklab olish.

Faqat kunlik video tahlilga kerak bo'lgan uchta so'rov:

  * GET  /ISAPI/ContentMgmt/InputProxy/channels — NVR'ga ulangan IP
    kameralar (kanal raqami, nomi, kameraning IP manzili). Kameralar
    tizimdagi yozuvga IP manzil bo'yicha bog'lanadi.
  * POST /ISAPI/ContentMgmt/search — berilgan oraliqda yozuv bormi
    (qaysi bo'laklar). Yozuv yo'q oraliq tahlil qilinmaydi va natijada
    "aniqlanmadi" bo'ladi — "kelmadi" emas.
  * GET  /ISAPI/ContentMgmt/download — oraliqni fayl sifatida (PS oqim)
    disk tezligida beradi; RTSP playback esa real vaqt tezligida.

XML nomlar fazosi (xmlns) firmware versiyasiga qarab har xil — tahlil
nomlar fazosiga qaramaydi (`_local`).
"""

from __future__ import annotations

import logging
import uuid
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.timezone import INSTITUTE_TZ

logger = logging.getLogger("app.nvr")

TIMEOUT = httpx.Timeout(20.0, read=60.0)


@dataclass(frozen=True)
class NvrChannel:
    channel: int
    name: str
    ip: str | None
    online: bool | None = None


@dataclass(frozen=True)
class RecordingSpan:
    start: datetime
    end: datetime


class NvrError(Exception):
    """NVR bilan bog'lanib bo'lmadi yoki u kutilmagan javob berdi."""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(node: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in node.iter() if _local(child.tag) == name]


def _text(node: ET.Element, name: str) -> str | None:
    for child in node.iter():
        if _local(child.tag) == name and child.text is not None:
            return child.text.strip()
    return None


def format_nvr_time(moment: datetime, *, local_time: bool, compact: bool) -> str:
    """NVR so'rovidagi vaqt. Ko'p Hikvision modellari vaqtni o'z mahalliy
    soatida kutadi va oxiriga baribir "Z" qo'yadi (local_time=True)."""
    value = moment.astimezone(INSTITUTE_TZ if local_time else timezone.utc)
    if compact:
        return value.strftime("%Y%m%dT%H%M%SZ")
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_nvr_time(raw: str, *, local_time: bool) -> datetime:
    """`2026-10-04T08:00:00Z` yoki `...+05:00`. "Z" mahalliy soat bo'lishi
    mumkin (format_nvr_time ga qarang)."""
    value = raw.strip()
    if value.endswith("Z"):
        naive = datetime.fromisoformat(value[:-1])
        return naive.replace(tzinfo=INSTITUTE_TZ if local_time else timezone.utc).astimezone(timezone.utc)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=INSTITUTE_TZ if local_time else timezone.utc)
    return parsed.astimezone(timezone.utc)


def track_id(channel: int, stream: str) -> int:
    """Hikvision trek raqami: 1-kanal asosiy oqim — 101, sub — 102."""
    return channel * 100 + (2 if stream == "sub" else 1)


def parse_channels(xml_text: str) -> list[NvrChannel]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise NvrError(f"kanal ro'yxati XML emas: {exc}") from exc
    out: list[NvrChannel] = []
    for node in _children(root, "InputProxyChannel"):
        raw_id = _text(node, "id")
        if raw_id is None or not raw_id.isdigit():
            continue
        out.append(
            NvrChannel(
                channel=int(raw_id),
                name=_text(node, "name") or f"Kanal {raw_id}",
                ip=_text(node, "ipAddress"),
            )
        )
    return out


def parse_channel_status(xml_text: str) -> dict[int, bool]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}
    status: dict[int, bool] = {}
    for node in _children(root, "InputProxyChannelStatus"):
        raw_id = _text(node, "id")
        online = _text(node, "online")
        if raw_id and raw_id.isdigit() and online is not None:
            status[int(raw_id)] = online.lower() == "true"
    return status


def search_body(track: int, start: datetime, end: datetime, *, local_time: bool, position: int = 0) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<CMSearchDescription version="1.0" xmlns="http://www.isapi.org/ver20/XMLSchema">'
        f"<searchID>{uuid.uuid4()}</searchID>"
        f"<trackList><trackID>{track}</trackID></trackList>"
        "<timeSpanList><timeSpan>"
        f"<startTime>{format_nvr_time(start, local_time=local_time, compact=False)}</startTime>"
        f"<endTime>{format_nvr_time(end, local_time=local_time, compact=False)}</endTime>"
        "</timeSpan></timeSpanList>"
        "<maxResults>100</maxResults>"
        f"<searchResultPostion>{position}</searchResultPostion>"
        "<metadataList><metadataDescriptor>//recordType.meta.std-cgi.com</metadataDescriptor></metadataList>"
        "</CMSearchDescription>"
    )


def parse_search(xml_text: str, *, local_time: bool) -> tuple[list[RecordingSpan], bool]:
    """(bo'laklar, yana bormi)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise NvrError(f"qidiruv javobi XML emas: {exc}") from exc
    spans: list[RecordingSpan] = []
    for item in _children(root, "searchMatchItem"):
        start = _text(item, "startTime")
        end = _text(item, "endTime")
        if not start or not end:
            continue
        try:
            spans.append(
                RecordingSpan(parse_nvr_time(start, local_time=local_time), parse_nvr_time(end, local_time=local_time))
            )
        except ValueError:
            continue
    more = (_text(root, "responseStatusStrg") or "").upper() == "MORE"
    return spans, more


def merge_spans(spans: list[RecordingSpan], gap_seconds: float = 2.0) -> list[RecordingSpan]:
    ordered = sorted(spans, key=lambda span: span.start)
    merged: list[RecordingSpan] = []
    for span in ordered:
        if merged and (span.start - merged[-1].end).total_seconds() <= gap_seconds:
            if span.end > merged[-1].end:
                merged[-1] = RecordingSpan(merged[-1].start, span.end)
            continue
        merged.append(span)
    return merged


class IsapiClient:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        local_time: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base = f"http://{host}:{port}"
        self._host = host
        self._auth = httpx.DigestAuth(username or "", password or "") if username else None
        self._local_time = local_time
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base, auth=self._auth, timeout=TIMEOUT, transport=self._transport)

    async def _get_text(self, client: httpx.AsyncClient, path: str) -> str:
        try:
            response = await client.get(path)
        except httpx.HTTPError as exc:
            raise NvrError(f"NVR javob bermadi: {exc.__class__.__name__}") from exc
        if response.status_code == 401:
            raise NvrError("NVR login yoki paroli noto'g'ri")
        if response.status_code >= 400:
            raise NvrError(f"NVR xatosi: HTTP {response.status_code} ({path})")
        return response.text

    async def device_info(self) -> dict[str, str | None]:
        async with self._client() as client:
            text = await self._get_text(client, "/ISAPI/System/deviceInfo")
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise NvrError("qurilma ma'lumoti XML emas") from exc
        return {
            "model": _text(root, "model"),
            "serial": _text(root, "serialNumber"),
            "firmware": _text(root, "firmwareVersion"),
            "name": _text(root, "deviceName"),
        }

    async def list_channels(self) -> list[NvrChannel]:
        async with self._client() as client:
            channels = parse_channels(await self._get_text(client, "/ISAPI/ContentMgmt/InputProxy/channels"))
            try:
                status = parse_channel_status(
                    await self._get_text(client, "/ISAPI/ContentMgmt/InputProxy/channels/status")
                )
            except NvrError:
                status = {}
        return [
            NvrChannel(channel=c.channel, name=c.name, ip=c.ip, online=status.get(c.channel)) for c in channels
        ]

    async def search_recordings(self, channel: int, stream: str, start: datetime, end: datetime) -> list[RecordingSpan]:
        track = track_id(channel, stream)
        spans: list[RecordingSpan] = []
        position = 0
        async with self._client() as client:
            for _page in range(50):  # bir kunda bo'laklar odatda o'nlab
                body = search_body(track, start, end, local_time=self._local_time, position=position)
                try:
                    response = await client.post(
                        "/ISAPI/ContentMgmt/search", content=body, headers={"Content-Type": "application/xml"}
                    )
                except httpx.HTTPError as exc:
                    raise NvrError(f"yozuv qidiruvi javob bermadi: {exc.__class__.__name__}") from exc
                if response.status_code >= 400:
                    raise NvrError(f"yozuv qidiruvi xatosi: HTTP {response.status_code}")
                page, more = parse_search(response.text, local_time=self._local_time)
                spans.extend(page)
                if not more or not page:
                    break
                position += len(page)
        clipped = [
            RecordingSpan(max(span.start, start), min(span.end, end)) for span in spans if span.end > start and span.start < end
        ]
        return merge_spans(clipped)

    def playback_uri(self, channel: int, stream: str, start: datetime, end: datetime) -> str:
        return (
            f"rtsp://{self._host}/Streaming/tracks/{track_id(channel, stream)}/"
            f"?starttime={format_nvr_time(start, local_time=self._local_time, compact=True)}"
            f"&endtime={format_nvr_time(end, local_time=self._local_time, compact=True)}"
        )

    async def download(
        self, channel: int, stream: str, start: datetime, end: datetime, chunk_size: int = 256 * 1024
    ) -> AsyncIterator[bytes]:
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<downloadRequest version="1.0" xmlns="http://www.isapi.org/ver20/XMLSchema">'
            f"<playbackURI>{self.playback_uri(channel, stream, start, end).replace('&', '&amp;')}</playbackURI>"
            "</downloadRequest>"
        )
        async with self._client() as client:
            try:
                async with client.stream(
                    "GET",
                    "/ISAPI/ContentMgmt/download",
                    content=body,
                    headers={"Content-Type": "application/xml"},
                    timeout=httpx.Timeout(30.0, read=120.0),
                ) as response:
                    if response.status_code >= 400:
                        raise NvrError(f"yuklab olish xatosi: HTTP {response.status_code}")
                    content_type = response.headers.get("content-type", "")
                    first = True
                    async for chunk in response.aiter_bytes(chunk_size):
                        if first:
                            first = False
                            # Xato javobi ham 200 bilan XML bo'lib kelishi mumkin.
                            if "xml" in content_type or chunk.lstrip().startswith(b"<?xml"):
                                raise NvrError("NVR yuklab berish o'rniga xato qaytardi")
                        yield chunk
            except httpx.HTTPError as exc:
                raise NvrError(f"yuklab olish uzildi: {exc.__class__.__name__}") from exc
