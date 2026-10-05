"""app/services/ptz.py — ONVIF (SOAP + WS-Security) va Hikvision ISAPI
(HTTP Digest) protokollari soxta kameralarga qarshi (tarmoqsiz)."""

import asyncio
import base64
import hashlib
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx
import pytest

from app.config import settings
from app.services import ptz
from tests.ptz_fake_camera import FakeIsapiCamera, FakeOnvifCamera, router_transport

HOST = "10.20.0.7"


@pytest.fixture(autouse=True)
def _reset_ptz():
    ptz.reset_ptz_state_for_tests()
    yield
    ptz.set_transport_for_tests(None)
    ptz.reset_ptz_state_for_tests()


def onvif_target(cam: FakeOnvifCamera, *, camera_id: str = "cam-1", password: str | None = None) -> ptz.PtzTarget:
    return ptz.PtzTarget(
        camera_id=camera_id,
        host=HOST,
        port=80,
        username=cam.username,
        password=cam.password if password is None else password,
        protocol="onvif",
    )


def isapi_target(cam: FakeIsapiCamera, *, password: str | None = None) -> ptz.PtzTarget:
    return ptz.PtzTarget(
        camera_id="cam-isapi",
        host=HOST,
        port=8080,
        username=cam.username,
        password=cam.password if password is None else password,
        protocol="isapi",
    )


def use(routes: dict) -> None:
    ptz.set_transport_for_tests(router_transport(routes))


class TestWsSecurity:
    def test_password_digest_matches_oasis_formula(self):
        nonce = bytes(range(16))
        created = "2026-09-19T08:30:00.000Z"
        expected = base64.b64encode(hashlib.sha1(nonce + created.encode() + b"secret").digest()).decode()
        assert ptz.password_digest(nonce, created, "secret") == expected

    def test_security_header_is_well_formed(self):
        header = ptz.security_header("ad<min", "p@ss", nonce=b"\x01" * 16)
        root = ET.fromstring(ptz.soap_envelope("<tds:GetCapabilities/>", header))
        ns = {"wsse": ptz.NS_WSSE, "wsu": ptz.NS_WSU}
        token = root.find(".//wsse:UsernameToken", ns)
        assert token.find("wsse:Username", ns).text == "ad<min"  # XML-escaped, qayta o'qilganda asl
        password = token.find("wsse:Password", ns)
        assert password.get("Type").endswith("#PasswordDigest")
        nonce = token.find("wsse:Nonce", ns)
        assert base64.b64decode(nonce.text) == b"\x01" * 16
        created = token.find("wsu:Created", ns).text
        assert created.endswith("Z")
        assert password.text == ptz.password_digest(b"\x01" * 16, created, "p@ss")

    def test_created_uses_camera_clock_offset(self):
        header = ptz.security_header("u", "p", time_offset=3600)
        created = ET.fromstring(ptz.soap_envelope("", header)).find(f".//{{{ptz.NS_WSU}}}Created").text
        created_ts = datetime.strptime(created, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()
        assert abs(created_ts - (time.time() + 3600)) < 5


class TestOnvif:
    async def test_move_discovers_profile_and_caches_session(self):
        cam = FakeOnvifCamera()
        use({f"{HOST}:80": cam.handler})
        target = onvif_target(cam)

        await ptz.move(target, 0.5, -0.25, 0)
        assert cam.actions() == ["GetSystemDateAndTime", "GetCapabilities", "GetProfiles", "ContinuousMove"]
        move = cam.calls[-1]
        # XAddr'dagi ichki IP emas — biz ulangan manzil ishlatiladi.
        assert move.host == HOST and move.path == "/onvif/PTZ"
        ns = {"tt": ptz.NS_SCHEMA, "tptz": ptz.NS_PTZ}
        assert move.body.find("tptz:ProfileToken", ns).text == "Profile_1"
        pan_tilt = move.body.find("tptz:Velocity/tt:PanTilt", ns)
        assert (pan_tilt.get("x"), pan_tilt.get("y")) == ("0.5", "-0.25")
        assert move.body.find("tptz:Velocity/tt:Zoom", ns).get("x") == "0"
        assert move.username == cam.username

        await ptz.move(target, -1, 0, 0)
        await ptz.stop(target)
        # Ikkinchi va keyingi buyruqlar — kesh: qayta aniqlash yo'q.
        assert cam.actions()[4:] == ["ContinuousMove", "Stop"]
        stop = cam.calls[-1].body
        assert [(_c.tag.rsplit("}", 1)[-1], _c.text) for _c in stop] == [
            ("ProfileToken", "Profile_1"),
            ("PanTilt", "true"),
            ("Zoom", "true"),
        ]

    async def test_camera_clock_skew_is_compensated(self):
        # Kamera soati 2 soat oldinda; soxta kamera 5 daqiqadan katta farqni rad etadi.
        cam = FakeOnvifCamera(clock_offset=7200)
        use({f"{HOST}:80": cam.handler})
        await ptz.move(onvif_target(cam), 0, 0, 0.3)
        assert cam.actions()[-1] == "ContinuousMove"

    async def test_duration_adds_timeout_and_server_auto_stop(self):
        cam = FakeOnvifCamera()
        use({f"{HOST}:80": cam.handler})
        await ptz.move(onvif_target(cam), 0.2, 0, 0, duration_ms=150)
        timeout = cam.calls[-1].body.find(f"{{{ptz.NS_PTZ}}}Timeout")
        assert timeout is not None and timeout.text == "PT0.15S"
        await asyncio.sleep(0.5)
        assert cam.actions()[-1] == "Stop"

    async def test_new_move_cancels_pending_auto_stop(self):
        cam = FakeOnvifCamera()
        use({f"{HOST}:80": cam.handler})
        target = onvif_target(cam)
        await ptz.move(target, 0.2, 0, 0, duration_ms=200)
        await ptz.move(target, 0.4, 0, 0)  # davomiyliksiz — to'xtatilmasligi kerak
        await asyncio.sleep(0.45)
        assert "Stop" not in cam.actions()

    async def test_wrong_password_is_auth_error(self):
        cam = FakeOnvifCamera()
        use({f"{HOST}:80": cam.handler})
        with pytest.raises(ptz.PtzAuthFailed) as exc:
            await ptz.move(onvif_target(cam, password="notogri"), 0.5, 0, 0)
        assert "login yoki paroli noto'g'ri" in exc.value.message
        assert exc.value.http_status != 401  # frontend sessiyani tugatmasin

    async def test_camera_without_ptz_is_not_supported(self):
        cam = FakeOnvifCamera(ptz=False)
        use({f"{HOST}:80": cam.handler})
        with pytest.raises(ptz.PtzNotSupported) as exc:
            await ptz.move(onvif_target(cam), 0.5, 0, 0)
        assert "PTZ" in exc.value.message

    async def test_unreachable_and_timeout(self):
        use({})  # hech qanday kamera — ulanish rad etiladi
        cam = FakeOnvifCamera()
        with pytest.raises(ptz.PtzUnreachable) as exc:
            await ptz.stop(onvif_target(cam))
        assert "ulanib bo'lmadi" in exc.value.message

        def slow(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out", request=request)

        use({f"{HOST}:80": slow})
        with pytest.raises(ptz.PtzTimeout) as exc:
            await ptz.stop(onvif_target(cam))
        assert f"{settings.ptz_timeout_seconds:g} soniya" in exc.value.message
        assert exc.value.http_status == 504

    async def test_presets_goto_and_save(self):
        cam = FakeOnvifCamera()
        use({f"{HOST}:80": cam.handler})
        target = onvif_target(cam)
        presets = await ptz.get_presets(target)
        assert [(p.token, p.name) for p in presets] == [("1", "Kirish eshigi"), ("2", "Hovli")]

        await ptz.goto_preset(target, "2")
        goto = cam.calls[-1]
        assert goto.action == "GotoPreset"
        assert goto.body.find(f"{{{ptz.NS_PTZ}}}PresetToken").text == "2"

        saved = await ptz.set_preset(target, "Zal <markaz>")
        assert saved.token == "3" and cam.presets["3"] == "Zal <markaz>"

    async def test_stale_cached_profile_is_rediscovered_once(self):
        cam = FakeOnvifCamera()
        use({f"{HOST}:80": cam.handler})
        target = onvif_target(cam)
        await ptz.stop(target)
        # Kamera qayta yuklandi — profil tokeni o'zgardi.
        cam.profile_token = "Profile_NEW"
        cam.calls.clear()
        await ptz.stop(target)
        assert cam.actions() == ["Stop", "GetSystemDateAndTime", "GetCapabilities", "GetProfiles", "Stop"]

    async def test_changed_credentials_invalidate_cache(self):
        cam = FakeOnvifCamera()
        use({f"{HOST}:80": cam.handler})
        await ptz.stop(onvif_target(cam))
        cam.calls.clear()
        cam.password = "yangi-parol"
        await ptz.stop(onvif_target(cam))
        assert cam.actions()[0] == "GetSystemDateAndTime"


class TestIsapi:
    async def test_continuous_move_with_digest_auth(self):
        cam = FakeIsapiCamera()
        use({f"{HOST}:8080": cam.handler})
        target = isapi_target(cam)
        await ptz.move(target, 0.5, -1, 0.333)
        await ptz.stop(target)
        assert cam.digest_failures == 0
        assert [(c.method, c.path) for c in cam.calls] == [
            ("PUT", "/ISAPI/PTZCtrl/channels/1/continuous"),
            ("PUT", "/ISAPI/PTZCtrl/channels/1/continuous"),
        ]
        move = ET.fromstring(cam.calls[0].body)
        values = {child.tag.rsplit("}", 1)[-1]: child.text for child in move}
        assert values == {"pan": "50", "tilt": "-100", "zoom": "33"}
        stop = {child.tag.rsplit("}", 1)[-1]: child.text for child in ET.fromstring(cam.calls[1].body)}
        assert stop == {"pan": "0", "tilt": "0", "zoom": "0"}

    async def test_wrong_password_maps_to_auth_error(self):
        cam = FakeIsapiCamera()
        use({f"{HOST}:8080": cam.handler})
        with pytest.raises(ptz.PtzAuthFailed) as exc:
            await ptz.move(isapi_target(cam, password="xato"), 0.1, 0, 0)
        assert "ISAPI" in exc.value.message
        assert cam.digest_failures >= 1

    async def test_presets_only_enabled_ones(self):
        cam = FakeIsapiCamera()
        use({f"{HOST}:8080": cam.handler})
        presets = await ptz.get_presets(isapi_target(cam))
        assert [(p.token, p.name) for p in presets] == [("1", "Asosiy kirish"), ("3", "Avtoturargoh")]

    async def test_goto_and_save_picks_first_free_user_slot(self):
        cam = FakeIsapiCamera()
        use({f"{HOST}:8080": cam.handler})
        target = isapi_target(cam)
        await ptz.goto_preset(target, "3")
        assert (cam.calls[-1].method, cam.calls[-1].path) == ("PUT", "/ISAPI/PTZCtrl/channels/1/presets/3/goto")

        saved = await ptz.set_preset(target, "Dahliz & zina")
        assert saved.token == "2"
        assert cam.presets[2] == "Dahliz &amp; zina"  # kameraga XML-escape bilan yetib boradi
        put = cam.calls[-1]
        assert put.path == "/ISAPI/PTZCtrl/channels/1/presets/2"
        body = ET.fromstring(put.body)
        assert {c.tag.rsplit("}", 1)[-1]: c.text for c in body}["presetName"] == "Dahliz & zina"

    async def test_non_numeric_preset_rejected(self):
        cam = FakeIsapiCamera()
        use({f"{HOST}:8080": cam.handler})
        with pytest.raises(ptz.PtzNotSupported):
            await ptz.goto_preset(isapi_target(cam), "abc")

    async def test_not_supported_response(self):
        cam = FakeIsapiCamera(ptz=False)
        use({f"{HOST}:8080": cam.handler})
        with pytest.raises(ptz.PtzNotSupported) as exc:
            await ptz.move(isapi_target(cam), 0.3, 0, 0)
        assert exc.value.http_status == 422


class TestProbe:
    async def test_autodetects_isapi_when_onvif_missing(self):
        cam = FakeIsapiCamera()

        def isapi_only(request: httpx.Request) -> httpx.Response:
            if request.url.path.startswith("/onvif"):
                return httpx.Response(404)
            return cam.handler(request)

        use({f"{HOST}:80": isapi_only})
        target = ptz.PtzTarget("cam-x", HOST, 80, cam.username, cam.password, protocol="")
        result = await ptz.probe(target)
        assert result.success and result.protocol == "isapi"
        assert result.tried == ["onvif", "isapi"]
        assert result.preset_count == 2
        assert result.device_info == "Hovli PTZ DS-2DE2A404IW-DE3"

    async def test_onvif_probe_reports_capabilities(self):
        cam = FakeOnvifCamera()
        use({f"{HOST}:80": cam.handler})
        result = await ptz.probe(onvif_target(cam))
        assert result.success and result.protocol == "onvif"
        assert result.reachable and result.authenticated and result.ptz_supported and result.presets_supported
        assert result.preset_count == 2
        assert result.device_info == "HIKVISION DS-2DE4425IW-DE"
        assert "ONVIF" in result.message

    async def test_most_meaningful_error_wins(self):
        cam = FakeOnvifCamera()
        # ONVIF paroli noto'g'ri; ISAPI esa yo'q (404) — "parol" xabari ko'rsatiladi.
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.startswith("/onvif"):
                return cam.handler(request)
            return httpx.Response(404)

        use({f"{HOST}:80": handler})
        target = ptz.PtzTarget("cam-y", HOST, 80, cam.username, "xato", protocol="")
        result = await ptz.probe(target)
        assert not result.success
        assert result.protocol == "onvif" and result.reachable and not result.authenticated
        assert "paroli noto'g'ri" in result.message

    async def test_unreachable(self):
        use({})
        result = await ptz.probe(ptz.PtzTarget("cam-z", HOST, 80, "a", "b", protocol="onvif"))
        assert not result.success and not result.reachable
        assert "ulanib bo'lmadi" in result.message


def test_missing_protocol_is_config_error():
    target = ptz.PtzTarget("c", HOST, 80, "u", "p", protocol="")
    with pytest.raises(ptz.PtzConfigError):
        asyncio.run(ptz.stop(target))


def test_doctype_responses_are_not_parsed():
    assert ptz._parse_xml(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>') is None
    assert ptz._parse_xml(b"<x>ok</x>").tag == "x"
