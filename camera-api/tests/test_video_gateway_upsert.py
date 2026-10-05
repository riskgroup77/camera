"""MediaMTX yo'lini yozish: o'zgarish bo'lmasa hech narsa yuborilmaydi
(har add/patch MediaMTX konfiguratsiyasini qayta yuklab, oqimlarni silkitardi),
rejim almashsa esa eski rejim kalitlari tozalanadi."""

import httpx

from app.services import video_gateway as vg

RELAY = {
    "source": "rtsp://cam/102",
    "sourceOnDemand": True,
    "sourceOnDemandStartTimeout": "45s",
    "sourceOnDemandCloseAfter": "300s",
}
TRANSCODE = {"runOnDemand": "/ffmpeg ...", "runOnDemandRestart": True}


def _client(state: dict | None, calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.startswith("/v3/config/paths/get/"):
            return httpx.Response(200, json=state) if state is not None else httpx.Response(404, json={})
        return httpx.Response(200, json={})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://mtx")


async def test_unchanged_path_is_not_touched():
    calls: list = []
    current = {**RELAY, "runOnDemand": "", "name": "cam-1", "record": False}
    async with _client(current, calls) as client:
        await vg._upsert_path(client, "http://mtx", "cam-1", RELAY)
    assert calls == [("GET", "/v3/config/paths/get/cam-1")]


async def test_missing_path_is_added():
    calls: list = []
    async with _client(None, calls) as client:
        await vg._upsert_path(client, "http://mtx", "cam-1", RELAY)
    assert ("POST", "/v3/config/paths/add/cam-1") in calls


async def test_switch_from_transcode_to_relay_clears_encoder():
    sent: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"source": "publisher", **TRANSCODE})
        sent.append((request.method, request.url.path, request.content))
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await vg._upsert_path(client, "http://mtx", "cam-1", RELAY)
    assert len(sent) == 1
    method, path, body = sent[0]
    assert method == "PATCH" and path.endswith("/patch/cam-1")
    assert b'"runOnDemand":""' in body.replace(b" ", b"")


def test_same_config_detects_leftover_mode():
    assert vg._same_config({**RELAY, "runOnDemand": ""}, RELAY)
    assert not vg._same_config({**RELAY, "runOnDemand": "/ffmpeg"}, RELAY)
    assert vg._same_config({"source": "publisher", **TRANSCODE}, TRANSCODE)
    assert not vg._same_config({"source": "rtsp://old", **TRANSCODE}, TRANSCODE)
