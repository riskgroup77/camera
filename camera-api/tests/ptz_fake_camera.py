"""PTZ testlari uchun soxta kameralar (httpx.MockTransport ishlovchilari).

Haqiqiy tarmoqqa hech narsa chiqmaydi. Soxta kameralar haqiqiy
qurilma kabi QATTIQ tekshiradi: ONVIF — WS-Security PasswordDigest'ni
nonce/created/paroldan qayta hisoblab solishtiradi; ISAPI — RFC 2617
HTTP Digest javobini (qop=auth) qayta hisoblaydi. Shunda sarlavha
formatidagi har qanday xato test yiqilishiga olib keladi.
"""

from __future__ import annotations

import base64
import hashlib
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

SOAP_ENV = "http://www.w3.org/2003/05/soap-envelope"
PASSWORD_DIGEST = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(root: ET.Element, name: str) -> ET.Element | None:
    for el in root.iter():
        if _local(el.tag) == name:
            return el
    return None


def soap(body: str, status: int = 200) -> httpx.Response:
    xml = (
        f'<?xml version="1.0" encoding="UTF-8"?><env:Envelope xmlns:env="{SOAP_ENV}" '
        'xmlns:tds="http://www.onvif.org/ver10/device/wsdl" xmlns:trt="http://www.onvif.org/ver10/media/wsdl" '
        'xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema" '
        'xmlns:ter="http://www.onvif.org/ver10/error">'
        f"<env:Body>{body}</env:Body></env:Envelope>"
    )
    return httpx.Response(status, content=xml.encode(), headers={"Content-Type": "application/soap+xml"})


def soap_fault(subcode: str, reason: str, status: int = 400) -> httpx.Response:
    return soap(
        "<env:Fault><env:Code><env:Value>env:Sender</env:Value>"
        f"<env:Subcode><env:Value>{subcode}</env:Value></env:Subcode></env:Code>"
        f'<env:Reason><env:Text xml:lang="en">{reason}</env:Text></env:Reason></env:Fault>',
        status,
    )


@dataclass
class OnvifCall:
    path: str
    host: str
    action: str
    body: ET.Element
    username: str | None
    created: str | None


@dataclass
class FakeOnvifCamera:
    username: str = "admin"
    password: str = "Parol-123"
    ptz: bool = True
    clock_offset: float = 0.0
    profile_token: str = "Profile_1"
    # XAddr'larda kamera o'zining ICHKI manzilini qaytaradi (NAT ortida).
    advertised_host: str = "192.168.100.50"
    presets: dict[str, str] = field(default_factory=lambda: {"1": "Kirish eshigi", "2": "Hovli"})
    calls: list[OnvifCall] = field(default_factory=list)
    # Birinchi ContinuousMove'da eski token uchun NoProfile qaytarish (kesh eskirishi).
    reject_token: str | None = None
    max_clock_skew: float = 300.0

    def actions(self) -> list[str]:
        return [c.action for c in self.calls]

    def _check_auth(self, root: ET.Element) -> tuple[bool, str | None, str | None]:
        token = _find(root, "UsernameToken")
        if token is None:
            return False, None, None
        username = _find(token, "Username").text
        password_el = _find(token, "Password")
        nonce_b64 = _find(token, "Nonce").text
        created = _find(token, "Created").text
        if password_el.get("Type") != PASSWORD_DIGEST:
            return False, username, created
        expected = base64.b64encode(
            hashlib.sha1(base64.b64decode(nonce_b64) + created.encode() + self.password.encode()).digest()
        ).decode()
        if username != self.username or password_el.text != expected:
            return False, username, created
        # Kamera soatiga nisbatan Created tekshiruvi — haqiqiy qurilmalar kabi.
        created_ts = datetime.strptime(created, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()
        camera_now = time.time() + self.clock_offset
        if abs(created_ts - camera_now) > self.max_clock_skew:
            return False, username, created
        return True, username, created

    def handler(self, request: httpx.Request) -> httpx.Response:
        if not request.url.path.startswith("/onvif/") or not request.content:
            return httpx.Response(404)  # boshqa xizmat (masalan ISAPI) — bu kamerada yo'q
        root = ET.fromstring(request.content)
        body = _find(root, "Body")
        action_el = next(iter(body))
        action = _local(action_el.tag)
        ok, username, created = self._check_auth(root)
        self.calls.append(OnvifCall(request.url.path, request.url.host, action, action_el, username, created))

        if action == "GetSystemDateAndTime":
            now = datetime.fromtimestamp(time.time() + self.clock_offset, tz=timezone.utc)
            return soap(
                "<tds:GetSystemDateAndTimeResponse><tds:SystemDateAndTime><tt:UTCDateTime>"
                f"<tt:Time><tt:Hour>{now.hour}</tt:Hour><tt:Minute>{now.minute}</tt:Minute><tt:Second>{now.second}</tt:Second></tt:Time>"
                f"<tt:Date><tt:Year>{now.year}</tt:Year><tt:Month>{now.month}</tt:Month><tt:Day>{now.day}</tt:Day></tt:Date>"
                "</tt:UTCDateTime></tds:SystemDateAndTime></tds:GetSystemDateAndTimeResponse>"
            )
        if not ok:
            return soap_fault("ter:NotAuthorized", "Sender not Authorized")

        base = f"http://{self.advertised_host}"
        if request.url.path == "/onvif/device_service":
            if action == "GetCapabilities":
                ptz = f"<tt:PTZ><tt:XAddr>{base}/onvif/PTZ</tt:XAddr></tt:PTZ>" if self.ptz else ""
                return soap(
                    "<tds:GetCapabilitiesResponse><tds:Capabilities>"
                    f"<tt:Device><tt:XAddr>{base}/onvif/device_service</tt:XAddr></tt:Device>"
                    f"<tt:Media><tt:XAddr>{base}/onvif/Media</tt:XAddr></tt:Media>"
                    f"{ptz}</tds:Capabilities></tds:GetCapabilitiesResponse>"
                )
            if action == "GetDeviceInformation":
                return soap(
                    "<tds:GetDeviceInformationResponse><tds:Manufacturer>HIKVISION</tds:Manufacturer>"
                    "<tds:Model>DS-2DE4425IW-DE</tds:Model></tds:GetDeviceInformationResponse>"
                )
        if request.url.path == "/onvif/Media" and action == "GetProfiles":
            ptz_conf = '<tt:PTZConfiguration token="PTZToken"><tt:Name>PTZ</tt:Name></tt:PTZConfiguration>' if self.ptz else ""
            return soap(
                "<trt:GetProfilesResponse>"
                f'<trt:Profiles token="{self.profile_token}" fixed="true"><tt:Name>mainStream</tt:Name>{ptz_conf}</trt:Profiles>'
                '<trt:Profiles token="Profile_2" fixed="true"><tt:Name>subStream</tt:Name></trt:Profiles>'
                "</trt:GetProfilesResponse>"
            )
        if request.url.path == "/onvif/PTZ":
            profile = _find(action_el, "ProfileToken")
            if profile is None or profile.text != self.profile_token or profile.text == self.reject_token:
                return soap_fault("ter:NoProfile", "The requested profile token does not exist")
            if action == "ContinuousMove":
                return soap("<tptz:ContinuousMoveResponse/>")
            if action == "Stop":
                return soap("<tptz:StopResponse/>")
            if action == "GetPresets":
                items = "".join(
                    f'<tptz:Preset token="{token}"><tt:Name>{name}</tt:Name></tptz:Preset>'
                    for token, name in self.presets.items()
                )
                return soap(f"<tptz:GetPresetsResponse>{items}</tptz:GetPresetsResponse>")
            if action == "GotoPreset":
                token = _find(action_el, "PresetToken").text
                if token not in self.presets:
                    return soap_fault("ter:NoToken", "No such preset")
                return soap("<tptz:GotoPresetResponse/>")
            if action == "SetPreset":
                name = _find(action_el, "PresetName").text
                token = str(max((int(t) for t in self.presets), default=0) + 1)
                self.presets[token] = name
                return soap(f"<tptz:SetPresetResponse><tptz:PresetToken>{token}</tptz:PresetToken></tptz:SetPresetResponse>")
        return soap_fault("ter:ActionNotSupported", "Action not supported")


def _md5(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()


@dataclass
class IsapiCall:
    method: str
    path: str
    body: str


@dataclass
class FakeIsapiCamera:
    username: str = "admin"
    password: str = "Hik-Parol-1"
    realm: str = "IP Camera(C12345)"
    nonce: str = "4e6a41354f5445314e7a4d364f4749774e6d45304f444d3d"
    ptz: bool = True
    presets: dict[int, str] = field(default_factory=lambda: {1: "Asosiy kirish", 3: "Avtoturargoh"})
    calls: list[IsapiCall] = field(default_factory=list)
    digest_failures: int = 0

    def _challenge(self) -> httpx.Response:
        return httpx.Response(
            401,
            headers={
                "WWW-Authenticate": f'Digest qop="auth", realm="{self.realm}", nonce="{self.nonce}", stale="FALSE"'
            },
        )

    def _authorized(self, request: httpx.Request) -> bool:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Digest "):
            return False
        fields = dict(re.findall(r'(\w+)="?([^",]+)"?', header[len("Digest "):]))
        if fields.get("username") != self.username or fields.get("realm") != self.realm or fields.get("nonce") != self.nonce:
            self.digest_failures += 1
            return False
        uri = fields.get("uri", "")
        expected_uri = request.url.raw_path.decode()
        if uri != expected_uri:
            self.digest_failures += 1
            return False
        ha1 = _md5(f"{self.username}:{self.realm}:{self.password}")
        ha2 = _md5(f"{request.method}:{uri}")
        expected = _md5(f"{ha1}:{self.nonce}:{fields.get('nc')}:{fields.get('cnonce')}:{fields.get('qop')}:{ha2}")
        if fields.get("qop") != "auth" or fields.get("response") != expected:
            self.digest_failures += 1
            return False
        return True

    def handler(self, request: httpx.Request) -> httpx.Response:
        if not self._authorized(request):
            return self._challenge()
        body = request.content.decode() if request.content else ""
        self.calls.append(IsapiCall(request.method, request.url.path, body))
        path = request.url.path
        if path == "/ISAPI/System/deviceInfo":
            return httpx.Response(
                200,
                content=b'<?xml version="1.0"?><DeviceInfo xmlns="http://www.hikvision.com/ver20/XMLSchema">'
                b"<deviceName>Hovli PTZ</deviceName><model>DS-2DE2A404IW-DE3</model></DeviceInfo>",
            )
        if not self.ptz and path.startswith("/ISAPI/PTZCtrl"):
            return httpx.Response(
                403,
                content=b'<?xml version="1.0"?><ResponseStatus><statusCode>4</statusCode>'
                b"<statusString>Invalid Operation</statusString><subStatusCode>notSupport</subStatusCode></ResponseStatus>",
            )
        if path == "/ISAPI/PTZCtrl/channels/1/capabilities":
            return httpx.Response(200, content=b"<PTZChanelCap><AbsolutePanTiltPositionSpace/></PTZChanelCap>")
        if path == "/ISAPI/PTZCtrl/channels/1/continuous" and request.method == "PUT":
            return httpx.Response(200, content=b"<ResponseStatus><statusCode>1</statusCode></ResponseStatus>")
        if path == "/ISAPI/PTZCtrl/channels/1/presets" and request.method == "GET":
            items = "".join(
                f"<PTZPreset><enabled>{'true' if pid in self.presets else 'false'}</enabled><id>{pid}</id>"
                f"<presetName>{self.presets.get(pid, '')}</presetName></PTZPreset>"
                for pid in range(1, 6)
            )
            return httpx.Response(200, content=f'<?xml version="1.0"?><PTZPresetList>{items}</PTZPresetList>'.encode())
        match = re.fullmatch(r"/ISAPI/PTZCtrl/channels/1/presets/(\d+)(/goto)?", path)
        if match and request.method == "PUT":
            pid = int(match.group(1))
            if match.group(2):
                if pid not in self.presets:
                    return httpx.Response(
                        400,
                        content=b"<ResponseStatus><statusCode>4</statusCode><statusString>Invalid XML Content</statusString></ResponseStatus>",
                    )
                return httpx.Response(200, content=b"<ResponseStatus><statusCode>1</statusCode></ResponseStatus>")
            name = re.search(r"<presetName>(.*?)</presetName>", body)
            self.presets[pid] = name.group(1) if name else ""
            return httpx.Response(200, content=b"<ResponseStatus><statusCode>1</statusCode></ResponseStatus>")
        return httpx.Response(404, content=b"<ResponseStatus><statusCode>4</statusCode></ResponseStatus>")


def router_transport(routes: dict[str, callable]) -> httpx.MockTransport:
    """Xost:port bo'yicha turli soxta kameralarga yo'naltiradi; noma'lum
    manzil — ulanish xatosi (haqiqiy tarmoqdagi yopiq port kabi)."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = f"{request.url.host}:{request.url.port or 80}"
        target = routes.get(key)
        if target is None:
            raise httpx.ConnectError("Connection refused", request=request)
        return target(request)

    return httpx.MockTransport(handler)
