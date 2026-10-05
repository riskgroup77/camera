"""NVR integratsiyasi: ISAPI (soxta NVR bilan) va yozuvdan kadr o'qish
(haqiqiy ffmpeg bilan yaratilgan video fayllarda)."""

import asyncio
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app.services.nvr.isapi import (
    IsapiClient,
    NvrError,
    RecordingSpan,
    format_nvr_time,
    merge_spans,
    parse_channels,
    parse_nvr_time,
    parse_search,
    track_id,
)
from app.services.nvr.sources import FolderSource, RtspPlaybackSource, VideoReadError, ffmpeg_frames, source_for
from app.timezone import INSTITUTE_TZ

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg o'rnatilmagan")

CHANNELS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<InputProxyChannelList version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <InputProxyChannel><id>1</id><name>Asosiy kirish</name>
    <sourceInputPortDescriptor><proxyProtocol>HIKVISION</proxyProtocol><ipAddress>192.168.0.11</ipAddress></sourceInputPortDescriptor>
  </InputProxyChannel>
  <InputProxyChannel><id>2</id><name>201-xona</name>
    <sourceInputPortDescriptor><ipAddress>192.168.0.12</ipAddress></sourceInputPortDescriptor>
  </InputProxyChannel>
  <InputProxyChannel><id>x</id><name>buzuq</name></InputProxyChannel>
</InputProxyChannelList>"""

STATUS_XML = """<InputProxyChannelStatusList xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <InputProxyChannelStatus><id>1</id><online>true</online></InputProxyChannelStatus>
  <InputProxyChannelStatus><id>2</id><online>false</online></InputProxyChannelStatus>
</InputProxyChannelStatusList>"""


def search_xml(spans, more=False):
    items = "".join(
        f"<searchMatchItem><timeSpan><startTime>{s}</startTime><endTime>{e}</endTime></timeSpan></searchMatchItem>"
        for s, e in spans
    )
    status = "MORE" if more else "OK"
    return (
        '<CMSearchResult xmlns="http://www.isapi.org/ver20/XMLSchema">'
        f"<responseStatusStrg>{status}</responseStatusStrg><matchList>{items}</matchList></CMSearchResult>"
    )


def test_track_ids():
    assert track_id(1, "main") == 101
    assert track_id(12, "sub") == 1202


def test_nvr_time_is_local_by_default():
    moment = datetime(2026, 10, 5, 3, 0, tzinfo=timezone.utc)  # 08:00 Toshkent
    assert format_nvr_time(moment, local_time=True, compact=True) == "20261005T080000Z"
    assert format_nvr_time(moment, local_time=False, compact=False) == "2026-10-05T03:00:00Z"
    assert parse_nvr_time("2026-10-05T08:00:00Z", local_time=True) == moment
    assert parse_nvr_time("2026-10-05T03:00:00Z", local_time=False) == moment
    assert parse_nvr_time("2026-10-05T08:00:00+05:00", local_time=False) == moment


def test_parse_channels_ignores_namespaces_and_garbage():
    channels = parse_channels(CHANNELS_XML)
    assert [(c.channel, c.name, c.ip) for c in channels] == [
        (1, "Asosiy kirish", "192.168.0.11"),
        (2, "201-xona", "192.168.0.12"),
    ]
    with pytest.raises(NvrError):
        parse_channels("<html>not xml")


def test_parse_search_and_merge():
    spans, more = parse_search(
        search_xml([("2026-10-05T08:00:00Z", "2026-10-05T09:00:00Z"), ("2026-10-05T09:00:01Z", "2026-10-05T10:00:00Z")]),
        local_time=True,
    )
    assert not more and len(spans) == 2
    merged = merge_spans(spans)
    assert len(merged) == 1
    assert merged[0].end - merged[0].start == timedelta(hours=2)


def mock_nvr(search_pages=None, download_body=b"\x00\x00\x01\xba" * 10, download_type="video/mpeg"):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/ISAPI/ContentMgmt/InputProxy/channels":
            return httpx.Response(200, text=CHANNELS_XML)
        if request.url.path == "/ISAPI/ContentMgmt/InputProxy/channels/status":
            return httpx.Response(200, text=STATUS_XML)
        if request.url.path == "/ISAPI/System/deviceInfo":
            return httpx.Response(200, text="<DeviceInfo><model>DS-96256NXI-I16</model><serialNumber>X</serialNumber></DeviceInfo>")
        if request.url.path == "/ISAPI/ContentMgmt/search":
            body = request.content.decode()
            assert "<trackID>101</trackID>" in body
            page = search_pages.pop(0)
            return httpx.Response(200, text=page)
        if request.url.path == "/ISAPI/ContentMgmt/download":
            assert b"starttime=" in request.content
            return httpx.Response(200, content=download_body, headers={"content-type": download_type})
        return httpx.Response(404)

    return httpx.MockTransport(handler), calls


def client(transport) -> IsapiClient:
    return IsapiClient(host="10.0.0.5", port=80, username="admin", password="p@ss", transport=transport)


async def test_list_channels_with_online_status():
    transport, _ = mock_nvr()
    channels = await client(transport).list_channels()
    assert [(c.channel, c.online) for c in channels] == [(1, True), (2, False)]


async def test_device_info():
    transport, _ = mock_nvr()
    info = await client(transport).device_info()
    assert info["model"] == "DS-96256NXI-I16"


async def test_search_pages_are_followed_and_clipped():
    pages = [
        search_xml([("2026-10-05T06:00:00Z", "2026-10-05T08:30:00Z")], more=True),
        search_xml([("2026-10-05T12:00:00Z", "2026-10-05T23:00:00Z")]),
    ]
    transport, calls = mock_nvr(search_pages=pages)
    start = datetime(2026, 10, 5, 7, 0, tzinfo=INSTITUTE_TZ)
    end = datetime(2026, 10, 5, 20, 0, tzinfo=INSTITUTE_TZ)
    spans = await client(transport).search_recordings(1, "main", start, end)
    assert [c for c in calls if c[1].endswith("search")] == [("POST", "/ISAPI/ContentMgmt/search")] * 2
    assert spans[0].start == start and spans[-1].end == end
    assert spans[0].end == datetime(2026, 10, 5, 8, 30, tzinfo=INSTITUTE_TZ)


async def test_wrong_password_is_reported_clearly():
    transport = httpx.MockTransport(lambda request: httpx.Response(401))
    with pytest.raises(NvrError, match="parol"):
        await client(transport).list_channels()


async def test_unreachable_nvr():
    def boom(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(NvrError, match="javob bermadi"):
        await client(httpx.MockTransport(boom)).list_channels()


async def test_download_streams_bytes_and_rejects_xml_errors():
    transport, _ = mock_nvr()
    start = datetime(2026, 10, 5, 8, 0, tzinfo=INSTITUTE_TZ)
    chunks = [c async for c in client(transport).download(1, "main", start, start + timedelta(minutes=1))]
    assert b"".join(chunks).startswith(b"\x00\x00\x01\xba")
    transport, _ = mock_nvr(download_body=b"<?xml version='1.0'?><ResponseStatus/>", download_type="application/xml")
    with pytest.raises(NvrError):
        async for _ in client(transport).download(1, "main", start, start + timedelta(minutes=1)):
            pass


def test_rtsp_playback_url_escapes_credentials():
    source = RtspPlaybackSource(
        host="10.0.0.5", port=554, username="admin", password="p@ss:w/rd", channel=3, stream="sub",
        template="/Streaming/tracks/{channel}0{stream}?starttime={start}&endtime={end}", local_time=True,
    )
    start = datetime(2026, 10, 5, 8, 0, tzinfo=INSTITUTE_TZ)
    url = source.url(start, start + timedelta(minutes=30))
    assert url == (
        "rtsp://admin:p%40ss%3Aw%2Frd@10.0.0.5:554/Streaming/tracks/302"
        "?starttime=20261005T080000Z&endtime=20261005T083000Z"
    )


def test_source_for_requires_mapping():
    class Nvr:
        kind = "fayl"
        base_path = "/tmp/x"

    class Cam:
        nvr_channel = None

    with pytest.raises(ValueError):
        source_for(Nvr(), Cam())


# ── haqiqiy ffmpeg ──────────────────────────────────────────────────────


def make_video(path: Path, seconds: int, color_changes: list[tuple[float, str]] | None = None) -> None:
    """lavfi bilan 10 kadr/s sinov videosi."""
    path.parent.mkdir(parents=True, exist_ok=True)
    filters = "format=yuv420p"
    for begin, color in color_changes or []:
        filters += f",drawbox=x=0:y=0:w=64:h=64:color={color}:t=fill:enable='gte(t,{begin})'"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
            "-i", f"testsrc=size=320x240:rate=10:duration={seconds}",
            "-vf", filters, "-c:v", "libx264", "-preset", "ultrafast", "-g", "10", str(path),
        ],
        check=True,
    )


@needs_ffmpeg
async def test_folder_source_reads_frames_with_timestamps(tmp_path):
    start = datetime(2026, 10, 5, 8, 0, 0, tzinfo=INSTITUTE_TZ)
    make_video(tmp_path / "3" / "20261005_080000.mp4", 20)
    make_video(tmp_path / "3" / "20261005_080030.mp4", 20)  # 10 s bo'shliq
    source = FolderSource(str(tmp_path), 3)

    spans = await source.available(start, start + timedelta(minutes=5))
    assert [(s.start, s.end) for s in spans] == [
        (start.astimezone(timezone.utc), (start + timedelta(seconds=20)).astimezone(timezone.utc)),
        ((start + timedelta(seconds=30)).astimezone(timezone.utc), (start + timedelta(seconds=50)).astimezone(timezone.utc)),
    ]

    frames = [f async for f in source.clip(start + timedelta(seconds=5), start + timedelta(seconds=9), 2.0,
                                            max_side=0, timeout=30)]
    assert len(frames) == 8
    assert frames[0].at == start + timedelta(seconds=5)
    assert frames[-1].at == start + timedelta(seconds=8.5)
    assert all(f.jpeg[:2] == b"\xff\xd8" and f.jpeg[-2:] == b"\xff\xd9" for f in frames)

    # Ikki fayl chegarasidan o'tuvchi oraliq: bo'shliq tashlab o'tiladi.
    frames = [f async for f in source.clip(start + timedelta(seconds=15), start + timedelta(seconds=35), 1.0,
                                            max_side=0, timeout=30)]
    times = [(f.at - start).total_seconds() for f in frames]
    assert times[:5] == [15, 16, 17, 18, 19]
    assert times[5:] == [30, 31, 32, 33, 34]


@needs_ffmpeg
async def test_folder_source_without_recording_raises(tmp_path):
    make_video(tmp_path / "1" / "20261005_080000.mp4", 5)
    source = FolderSource(str(tmp_path), 1)
    start = datetime(2026, 10, 5, 12, 0, tzinfo=INSTITUTE_TZ)
    with pytest.raises(VideoReadError):
        async for _ in source.clip(start, start + timedelta(seconds=5), 1.0, max_side=0, timeout=10):
            pass
    assert await FolderSource(str(tmp_path), 9).available(start, start + timedelta(hours=1)) == []


@needs_ffmpeg
async def test_frames_are_downscaled(tmp_path):
    import cv2
    import numpy as np

    make_video(tmp_path / "1" / "20261005_080000.mp4", 3)
    source = FolderSource(str(tmp_path), 1)
    start = datetime(2026, 10, 5, 8, 0, tzinfo=INSTITUTE_TZ)
    frame = [f async for f in source.clip(start, start + timedelta(seconds=1), 1.0, max_side=160, timeout=10)][0]
    image = cv2.imdecode(np.frombuffer(frame.jpeg, np.uint8), cv2.IMREAD_COLOR)
    assert image.shape[1] == 160 and image.shape[0] == 120


@needs_ffmpeg
async def test_ffmpeg_reader_stops_early_and_kills_process(tmp_path):
    make_video(tmp_path / "v.mp4", 30)
    start = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)
    stop = {"now": False}
    taken = 0
    async for _frame in ffmpeg_frames(["-i", str(tmp_path / "v.mp4")], start=start, duration=30, fps=5, max_side=0,
                                      timeout=30, should_stop=lambda: stop["now"]):
        taken += 1
        if taken == 3:
            stop["now"] = True
    assert taken == 3


@needs_ffmpeg
async def test_ffmpeg_reader_from_pipe(tmp_path):
    make_video(tmp_path / "v.ts", 4)
    data = (tmp_path / "v.ts").read_bytes()

    async def feed():
        for i in range(0, len(data), 4096):
            yield data[i : i + 4096]
            await asyncio.sleep(0)

    start = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)
    frames = [f async for f in ffmpeg_frames(["-i", "pipe:0"], start=start, duration=4, fps=1, max_side=0,
                                              timeout=30, feed=feed())]
    assert len(frames) == 4


@needs_ffmpeg
async def test_ffmpeg_reader_reports_errors(tmp_path):
    start = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)
    with pytest.raises(VideoReadError):
        async for _ in ffmpeg_frames(["-i", str(tmp_path / "missing.mp4")], start=start, duration=2, fps=1,
                                     max_side=0, timeout=10):
            pass
