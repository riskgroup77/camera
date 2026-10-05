"""PTZ (burish / egish / yaqinlashtirish) kamera boshqaruvi.

Ikki protokol, ikkalasi ham to'g'ridan-to'g'ri httpx bilan (qo'shimcha
kutubxonasiz):

* **ONVIF** — SOAP 1.2 konvertlari. Autentifikatsiya WS-Security
  UsernameToken (PasswordDigest): Digest = Base64(SHA1(nonce + created +
  parol)). Kamera buni rad etib HTTP Digest talab qilsa, httpx.DigestAuth
  o'zi javob beradi. Birinchi murojaatda qurilma soati o'qiladi
  (GetSystemDateAndTime — autentifikatsiyasiz): kamera soati bir necha
  daqiqa farq qilsa, `Created` vaqti eskirgan deb rad etiladi.
  So'ng GetCapabilities -> Media/PTZ xizmat manzillari, GetProfiles ->
  PTZ sozlamasi bor birinchi profil tokeni. Bular kamera bo'yicha xotirada
  keshlanadi (har harakatda 3 ta qo'shimcha so'rov yubormaslik uchun).
* **Hikvision ISAPI** — XML ustida REST, HTTP Digest autentifikatsiya.
  /ISAPI/PTZCtrl/channels/1/continuous (pan/tilt/zoom -100..100),
  presetlar /ISAPI/PTZCtrl/channels/1/presets.

Login/parol — kameraning RTSP login/paroli (bazada shifrlangan,
app/crypto.py). Port — Camera.onvif_port (kameraning HTTP porti), bo'sh
bo'lsa 80.

Bitta kameraga buyruqlar ketma-ket yuboriladi (kamera bo'yicha qulf):
"harakat" va undan keyingi "to'xtash" kameraga teskari tartibda yetib
borsa, kamera to'xtamay aylanib qolardi.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.sax.saxutils import escape

import httpx

from app.config import settings

logger = logging.getLogger("app.ptz")

DEFAULT_HTTP_PORT = 80
PROTOCOLS = ("onvif", "isapi")

# Kamera javobi — kichik XML. Kattaroq javob (noto'g'ri qurilma yoki
# boshqa xizmat) o'qilmaydi.
MAX_RESPONSE_BYTES = 512 * 1024
# Auto-to'xtash chegarasi: brauzer "to'xtash"ni yubora olmay qolsa
# (tarmoq uzildi, varaq yopildi) kamera abadiy aylanib qolmasin.
MAX_MOVE_DURATION_MS = 10_000

SOAP_ENV = "http://www.w3.org/2003/05/soap-envelope"
NS_DEVICE = "http://www.onvif.org/ver10/device/wsdl"
NS_MEDIA = "http://www.onvif.org/ver10/media/wsdl"
NS_PTZ = "http://www.onvif.org/ver20/ptz/wsdl"
NS_SCHEMA = "http://www.onvif.org/ver10/schema"
NS_WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
NS_WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
PASSWORD_DIGEST_TYPE = (
    "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest"
)
NONCE_ENCODING = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary"
ISAPI_NS = "http://www.hikvision.com/ver20/XMLSchema"
ISAPI_CHANNEL = 1


# ---------------------------------------------------------------------------
# Xatolar — router ularni HTTP javobiga aylantiradi. 401 ATAYLAB
# ishlatilmaydi: frontend 401 ni "sessiya tugadi" deb tushunib,
# foydalanuvchini tizimdan chiqarib yuborardi — kamera paroli noto'g'ri
# bo'lsa ham.
# ---------------------------------------------------------------------------


class PtzError(Exception):
    http_status = 502

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PtzUnreachable(PtzError):
    http_status = 502


class PtzTimeout(PtzError):
    http_status = 504


class PtzAuthFailed(PtzError):
    http_status = 502


class PtzNotSupported(PtzError):
    http_status = 422


class PtzConfigError(PtzError):
    http_status = 409


@dataclass(frozen=True)
class PtzTarget:
    """Bitta kameraga ulanish uchun kerakli hamma narsa (ochilgan parol bilan)."""

    camera_id: str
    host: str
    port: int
    username: str
    password: str
    protocol: str

    @property
    def base_url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        return f"http://{host}:{self.port}"

    @property
    def cache_key(self) -> tuple:
        # Parol xeshi — admin parolni almashtirsa, kesh ham yangilanadi.
        return (self.host, self.port, self.username, hashlib.sha256(self.password.encode()).hexdigest())


@dataclass
class PtzPreset:
    token: str
    name: str


@dataclass
class PtzProbeResult:
    success: bool
    message: str
    protocol: str | None = None
    reachable: bool = False
    authenticated: bool = False
    ptz_supported: bool = False
    presets_supported: bool = False
    preset_count: int | None = None
    device_info: str | None = None
    latency_ms: int | None = None
    tried: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Kamera bo'yicha holat: ONVIF sessiya keshi, buyruqlar qulfi, auto-to'xtash.
# ---------------------------------------------------------------------------


@dataclass
class _OnvifSession:
    key: tuple
    ptz_url: str
    media_url: str
    profile_token: str
    time_offset: float  # kamera_soati - bizning_soat, soniya


_onvif_sessions: dict[str, _OnvifSession] = {}
_locks: dict[str, asyncio.Lock] = {}
_auto_stop_tasks: dict[str, asyncio.Task] = {}
# Testlar httpx.MockTransport o'rnatadi — haqiqiy kameraga hech qachon chiqilmaydi.
_transport: httpx.AsyncBaseTransport | None = None


def set_transport_for_tests(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


def reset_ptz_state_for_tests() -> None:
    for task in _auto_stop_tasks.values():
        task.cancel()
    _auto_stop_tasks.clear()
    _onvif_sessions.clear()
    _locks.clear()


def invalidate_camera(camera_id: str) -> None:
    """Kamera sozlamasi o'zgarganda (yoki probe) keshni tashlab yuborish."""
    _onvif_sessions.pop(camera_id, None)


def _lock_for(camera_id: str) -> asyncio.Lock:
    lock = _locks.get(camera_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[camera_id] = lock
    return lock


def _client(auth: httpx.Auth | None) -> httpx.AsyncClient:
    timeout = httpx.Timeout(settings.ptz_timeout_seconds)
    kwargs: dict = {"timeout": timeout, "auth": auth, "follow_redirects": False}
    if _transport is not None:
        kwargs["transport"] = _transport
    return httpx.AsyncClient(**kwargs)


def _digest_auth(target: PtzTarget) -> httpx.Auth | None:
    if not target.username:
        return None
    return httpx.DigestAuth(target.username, target.password)


async def _send(
    target: PtzTarget,
    method: str,
    url: str,
    *,
    content: bytes | None = None,
    headers: dict[str, str] | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.Response:
    try:
        async with _client(auth) as client:
            response = await client.request(method, url, content=content, headers=headers)
    except httpx.TimeoutException as exc:
        raise PtzTimeout(
            f"Kamera {settings.ptz_timeout_seconds:g} soniya ichida javob bermadi ({target.host}:{target.port})"
        ) from exc
    except httpx.HTTPError as exc:
        raise PtzUnreachable(
            f"Kameraga ulanib bo'lmadi ({target.host}:{target.port}) — IP manzil va HTTP portni tekshiring"
        ) from exc
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise PtzError("Kamera javobi juda katta — bu PTZ xizmati emas")
    return response


def _parse_xml(content: bytes) -> ET.Element | None:
    """Xavfsiz XML o'qish: DTD/entity'li hujjat umuman o'qilmaydi."""
    if not content or b"<!DOCTYPE" in content[:4096].upper() or b"<!ENTITY" in content.upper():
        return None
    try:
        return ET.fromstring(content)
    except ET.ParseError:
        return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _iter_local(root: ET.Element, name: str):
    for element in root.iter():
        if _local(element.tag) == name:
            yield element


def _find_local(root: ET.Element, name: str) -> ET.Element | None:
    return next(_iter_local(root, name), None)


def _child_text(element: ET.Element, name: str) -> str | None:
    for child in element:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return None


# ---------------------------------------------------------------------------
# ONVIF
# ---------------------------------------------------------------------------


def password_digest(nonce: bytes, created: str, password: str) -> str:
    """WS-Security UsernameToken PasswordDigest (OASIS UsernameToken Profile 1.0)."""
    return base64.b64encode(hashlib.sha1(nonce + created.encode() + password.encode()).digest()).decode()


def _created_timestamp(time_offset: float) -> str:
    moment = datetime.fromtimestamp(time.time() + time_offset, tz=timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def security_header(username: str, password: str, time_offset: float = 0.0, nonce: bytes | None = None) -> str:
    nonce = nonce if nonce is not None else os.urandom(16)
    created = _created_timestamp(time_offset)
    digest = password_digest(nonce, created, password)
    return (
        f'<wsse:Security s:mustUnderstand="1" xmlns:wsse="{NS_WSSE}" xmlns:wsu="{NS_WSU}">'
        "<wsse:UsernameToken>"
        f"<wsse:Username>{escape(username)}</wsse:Username>"
        f'<wsse:Password Type="{PASSWORD_DIGEST_TYPE}">{digest}</wsse:Password>'
        f'<wsse:Nonce EncodingType="{NONCE_ENCODING}">{base64.b64encode(nonce).decode()}</wsse:Nonce>'
        f"<wsu:Created>{created}</wsu:Created>"
        "</wsse:UsernameToken>"
        "</wsse:Security>"
    )


def soap_envelope(body: str, header: str = "") -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<s:Envelope xmlns:s="{SOAP_ENV}" xmlns:tds="{NS_DEVICE}" xmlns:trt="{NS_MEDIA}" '
        f'xmlns:tptz="{NS_PTZ}" xmlns:tt="{NS_SCHEMA}">'
        f"<s:Header>{header}</s:Header>"
        f"<s:Body>{body}</s:Body>"
        "</s:Envelope>"
    ).encode()


def _fault_text(root: ET.Element | None) -> tuple[str, str]:
    """(subcode/code qiymatlari, sabab matni) — xatoni tasniflash uchun."""
    if root is None:
        return "", ""
    fault = _find_local(root, "Fault")
    if fault is None:
        return "", ""
    codes = " ".join((el.text or "").strip() for el in _iter_local(fault, "Value"))
    codes += " " + " ".join((el.text or "").strip() for el in _iter_local(fault, "faultcode"))
    reason = " ".join((el.text or "").strip() for el in _iter_local(fault, "Text"))
    reason += " " + " ".join((el.text or "").strip() for el in _iter_local(fault, "faultstring"))
    return codes.strip(), reason.strip()


_AUTH_MARKERS = ("notauthorized", "not authorized", "authentication", "unauthorized", "failedauthentication")
_UNSUPPORTED_MARKERS = (
    "actionnotsupported",
    "not supported",
    "notsupported",
    "noptzprofile",
    "noprofile",
    "noptz",
    "no ptz",
)


async def _soap(
    target: PtzTarget,
    url: str,
    body: str,
    *,
    authenticated: bool = True,
    time_offset: float = 0.0,
) -> ET.Element:
    header = security_header(target.username, target.password, time_offset) if authenticated and target.username else ""
    response = await _send(
        target,
        "POST",
        url,
        content=soap_envelope(body, header),
        headers={"Content-Type": "application/soap+xml; charset=utf-8"},
        auth=_digest_auth(target) if authenticated else None,
    )
    root = _parse_xml(response.content)
    if response.status_code == 200 and root is not None and _find_local(root, "Fault") is None:
        return root

    codes, reason = _fault_text(root)
    haystack = f"{codes} {reason}".lower()
    if response.status_code in (401, 403) or any(marker in haystack for marker in _AUTH_MARKERS):
        raise PtzAuthFailed("Kamera login yoki paroli noto'g'ri (ONVIF autentifikatsiyasi rad etildi)")
    if response.status_code in (404, 405) or any(marker in haystack for marker in _UNSUPPORTED_MARKERS):
        raise PtzNotSupported("Kamera bu PTZ amalini qo'llab-quvvatlamaydi (ONVIF)")
    if root is None:
        raise PtzError(f"Kamera ONVIF so'roviga tushunarsiz javob qaytardi (HTTP {response.status_code})")
    detail = reason or codes or f"HTTP {response.status_code}"
    raise PtzError(f"Kamera buyruqni rad etdi: {detail[:200]}")


def _parse_camera_time(root: ET.Element) -> float | None:
    """GetSystemDateAndTime javobidan UTC vaqtni (unix) o'qiydi."""
    utc = _find_local(root, "UTCDateTime")
    if utc is None:
        return None
    date = _find_local(utc, "Date")
    clock = _find_local(utc, "Time")
    if date is None or clock is None:
        return None
    try:
        moment = datetime(
            int(_child_text(date, "Year") or 0),
            int(_child_text(date, "Month") or 0),
            int(_child_text(date, "Day") or 0),
            int(_child_text(clock, "Hour") or 0),
            int(_child_text(clock, "Minute") or 0),
            int(_child_text(clock, "Second") or 0),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    return moment.timestamp()


def _same_host(url: str, target: PtzTarget) -> str:
    """Kamera NAT/boshqa IP ortida bo'lsa, u XAddr'da o'zining ichki
    manzilini qaytaradi — yo'lni olib, xostni biz ulangan manzil bilan
    almashtiramiz."""
    try:
        parsed = httpx.URL(url)
    except Exception:  # noqa: BLE001 — noto'g'ri URL
        return url
    path = parsed.raw_path.decode() if parsed.raw_path else "/"
    return f"{target.base_url}{path}"


async def _onvif_session(target: PtzTarget, *, refresh: bool = False) -> _OnvifSession:
    cached = _onvif_sessions.get(target.camera_id)
    if cached is not None and not refresh and cached.key == target.cache_key:
        return cached

    device_url = f"{target.base_url}/onvif/device_service"

    # 1) Kamera soati (autentifikatsiyasiz). O'qib bo'lmasa — farq 0.
    time_offset = 0.0
    try:
        root = await _soap(target, device_url, "<tds:GetSystemDateAndTime/>", authenticated=False)
        camera_time = _parse_camera_time(root)
        if camera_time is not None:
            time_offset = camera_time - time.time()
    except (PtzUnreachable, PtzTimeout):
        raise
    except PtzError:
        # Ba'zi kameralar bu so'rovga ham parol so'raydi — davom etamiz.
        pass

    # 2) Xizmat manzillari.
    capabilities = await _soap(
        target,
        device_url,
        "<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>",
        time_offset=time_offset,
    )
    media_url = ptz_url = None
    media_el = _find_local(capabilities, "Media")
    if media_el is not None:
        media_url = _child_text(media_el, "XAddr")
    ptz_el = _find_local(capabilities, "PTZ")
    if ptz_el is not None:
        ptz_url = _child_text(ptz_el, "XAddr")
    if not ptz_url:
        raise PtzNotSupported("Kamera PTZ xizmatini e'lon qilmaydi — bu kamera burilmaydigan (PTZ emas)")
    media_url = _same_host(media_url, target) if media_url else device_url
    ptz_url = _same_host(ptz_url, target)

    # 3) PTZ sozlamasi bor profil.
    profiles = await _soap(target, media_url, "<trt:GetProfiles/>", time_offset=time_offset)
    profile_token = None
    first_token = None
    for profile in _iter_local(profiles, "Profiles"):
        token = profile.get("token")
        if not token:
            continue
        first_token = first_token or token
        if any(_local(child.tag) == "PTZConfiguration" for child in profile):
            profile_token = token
            break
    if profile_token is None:
        if first_token is None:
            raise PtzNotSupported("Kamerada media profil topilmadi")
        raise PtzNotSupported("Kamera profillarida PTZ sozlamasi yo'q — bu kamera burilmaydigan (PTZ emas)")

    session = _OnvifSession(
        key=target.cache_key,
        ptz_url=ptz_url,
        media_url=media_url,
        profile_token=profile_token,
        time_offset=time_offset,
    )
    _onvif_sessions[target.camera_id] = session
    return session


async def _onvif_call(target: PtzTarget, build_body) -> ET.Element:
    """Sessiya keshi bilan chaqiruv; kesh eskirgan bo'lsa (masalan kamera
    qayta yuklanib profil tokeni o'zgargan) bir marta yangilab qaytadan."""
    cached = _onvif_sessions.get(target.camera_id)
    from_cache = cached is not None and cached.key == target.cache_key
    session = await _onvif_session(target)
    try:
        return await _soap(target, session.ptz_url, build_body(session), time_offset=session.time_offset)
    except (PtzUnreachable, PtzTimeout, PtzAuthFailed):
        raise
    except PtzError:
        if not from_cache:
            raise
        invalidate_camera(target.camera_id)
        session = await _onvif_session(target, refresh=True)
        return await _soap(target, session.ptz_url, build_body(session), time_offset=session.time_offset)


def _fmt(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".") if value else "0"


def _onvif_timeout(duration_ms: int | None) -> str:
    if not duration_ms:
        return ""
    seconds = min(max(duration_ms, 100), MAX_MOVE_DURATION_MS) / 1000
    return f"<tptz:Timeout>PT{seconds:g}S</tptz:Timeout>"


async def _onvif_move(target: PtzTarget, pan: float, tilt: float, zoom: float, duration_ms: int | None) -> None:
    def body(session: _OnvifSession) -> str:
        return (
            "<tptz:ContinuousMove>"
            f"<tptz:ProfileToken>{escape(session.profile_token)}</tptz:ProfileToken>"
            "<tptz:Velocity>"
            f'<tt:PanTilt x="{_fmt(pan)}" y="{_fmt(tilt)}"/>'
            f'<tt:Zoom x="{_fmt(zoom)}"/>'
            "</tptz:Velocity>"
            f"{_onvif_timeout(duration_ms)}"
            "</tptz:ContinuousMove>"
        )

    await _onvif_call(target, body)


async def _onvif_stop(target: PtzTarget) -> None:
    def body(session: _OnvifSession) -> str:
        return (
            "<tptz:Stop>"
            f"<tptz:ProfileToken>{escape(session.profile_token)}</tptz:ProfileToken>"
            "<tptz:PanTilt>true</tptz:PanTilt>"
            "<tptz:Zoom>true</tptz:Zoom>"
            "</tptz:Stop>"
        )

    await _onvif_call(target, body)


async def _onvif_presets(target: PtzTarget) -> list[PtzPreset]:
    def body(session: _OnvifSession) -> str:
        return f"<tptz:GetPresets><tptz:ProfileToken>{escape(session.profile_token)}</tptz:ProfileToken></tptz:GetPresets>"

    root = await _onvif_call(target, body)
    presets: list[PtzPreset] = []
    for preset in _iter_local(root, "Preset"):
        token = preset.get("token")
        if not token:
            continue
        name = _child_text(preset, "Name") or f"Preset {token}"
        presets.append(PtzPreset(token=token, name=name))
    return presets


async def _onvif_goto(target: PtzTarget, preset_token: str) -> None:
    def body(session: _OnvifSession) -> str:
        return (
            "<tptz:GotoPreset>"
            f"<tptz:ProfileToken>{escape(session.profile_token)}</tptz:ProfileToken>"
            f"<tptz:PresetToken>{escape(preset_token)}</tptz:PresetToken>"
            "</tptz:GotoPreset>"
        )

    await _onvif_call(target, body)


async def _onvif_set_preset(target: PtzTarget, name: str) -> PtzPreset:
    def body(session: _OnvifSession) -> str:
        return (
            "<tptz:SetPreset>"
            f"<tptz:ProfileToken>{escape(session.profile_token)}</tptz:ProfileToken>"
            f"<tptz:PresetName>{escape(name)}</tptz:PresetName>"
            "</tptz:SetPreset>"
        )

    root = await _onvif_call(target, body)
    token_el = _find_local(root, "PresetToken")
    token = (token_el.text or "").strip() if token_el is not None else ""
    if not token:
        raise PtzError("Kamera presetni saqladi, lekin uning tokenini qaytarmadi")
    return PtzPreset(token=token, name=name)


# ---------------------------------------------------------------------------
# Hikvision ISAPI
# ---------------------------------------------------------------------------


def _isapi_url(target: PtzTarget, path: str) -> str:
    return f"{target.base_url}/ISAPI/PTZCtrl/channels/{ISAPI_CHANNEL}{path}"


def _xml_text(root: ET.Element | None, name: str) -> str:
    if root is None:
        return ""
    element = _find_local(root, name)
    return (element.text or "").strip() if element is not None else ""


def _isapi_raise(response: httpx.Response) -> None:
    if 200 <= response.status_code < 300:
        return
    root = _parse_xml(response.content)
    status_string = _xml_text(root, "statusString")
    sub_status = _xml_text(root, "subStatusCode")
    marker = f"{status_string} {sub_status}".lower()
    if response.status_code == 401:
        raise PtzAuthFailed("Kamera login yoki paroli noto'g'ri (ISAPI Digest autentifikatsiyasi rad etildi)")
    if response.status_code == 404 or "notsupport" in marker or "invalid operation" in marker:
        raise PtzNotSupported("Kamera bu PTZ amalini qo'llab-quvvatlamaydi (ISAPI)")
    if response.status_code == 403:
        raise PtzAuthFailed("Kamera foydalanuvchisida PTZ boshqaruv huquqi yo'q (ISAPI 403)")
    detail = (status_string or sub_status or f"HTTP {response.status_code}").strip()
    raise PtzError(f"Kamera buyruqni rad etdi: {detail[:200]}")


async def _isapi(target: PtzTarget, method: str, path: str, xml_body: str | None = None) -> httpx.Response:
    content = xml_body.encode() if xml_body is not None else None
    headers = {"Content-Type": "application/xml; charset=utf-8"} if content is not None else None
    response = await _send(target, method, _isapi_url(target, path), content=content, headers=headers, auth=_digest_auth(target))
    _isapi_raise(response)
    return response


def _isapi_speed(value: float) -> int:
    return max(-100, min(100, round(value * 100)))


def isapi_ptz_data(pan: float, tilt: float, zoom: float) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><PTZData version="2.0" xmlns="{ISAPI_NS}">'
        f"<pan>{_isapi_speed(pan)}</pan><tilt>{_isapi_speed(tilt)}</tilt><zoom>{_isapi_speed(zoom)}</zoom>"
        "</PTZData>"
    )


async def _isapi_move(target: PtzTarget, pan: float, tilt: float, zoom: float) -> None:
    await _isapi(target, "PUT", "/continuous", isapi_ptz_data(pan, tilt, zoom))


async def _isapi_stop(target: PtzTarget) -> None:
    await _isapi(target, "PUT", "/continuous", isapi_ptz_data(0, 0, 0))


def _isapi_parse_presets(content: bytes) -> list[PtzPreset]:
    root = _parse_xml(content)
    if root is None:
        raise PtzError("Kamera presetlar ro'yxatini tushunarsiz shaklda qaytardi")
    presets: list[PtzPreset] = []
    for preset in _iter_local(root, "PTZPreset"):
        preset_id = _child_text(preset, "id")
        if not preset_id:
            continue
        # Hikvision barcha raqamlarni qaytaradi — faqat haqiqatan saqlanganlari
        # (enabled=true) kerak. enabled bo'lmasa (eski proshivka) — saqlangan deb olamiz.
        enabled = _child_text(preset, "enabled")
        if enabled is not None and enabled.lower() != "true":
            continue
        name = _child_text(preset, "presetName") or f"Preset {preset_id}"
        presets.append(PtzPreset(token=preset_id, name=name))
    return presets


async def _isapi_presets(target: PtzTarget) -> list[PtzPreset]:
    response = await _isapi(target, "GET", "/presets")
    return _isapi_parse_presets(response.content)


async def _isapi_goto(target: PtzTarget, preset_token: str) -> None:
    if not preset_token.isdigit():
        raise PtzNotSupported("ISAPI preset raqami butun son bo'lishi kerak")
    await _isapi(target, "PUT", f"/presets/{int(preset_token)}/goto")


# Hikvision'da 33-45 va 92-105 raqamli presetlar maxsus buyruqlar
# (avto-aylantirish, kun/tun rejimi, patrul...). Yangi preset faqat oddiy
# raqamlarga yoziladi.
ISAPI_USER_PRESET_IDS = [*range(1, 33), *range(46, 92), *range(106, 256)]


async def _isapi_set_preset(target: PtzTarget, name: str) -> PtzPreset:
    existing = {int(p.token) for p in await _isapi_presets(target) if p.token.isdigit()}
    free = next((pid for pid in ISAPI_USER_PRESET_IDS if pid not in existing), None)
    if free is None:
        raise PtzError("Kamerada bo'sh preset raqami qolmagan — avval keraksizlarini o'chiring")
    body = (
        f'<?xml version="1.0" encoding="UTF-8"?><PTZPreset version="2.0" xmlns="{ISAPI_NS}">'
        f"<enabled>true</enabled><id>{free}</id><presetName>{escape(name)}</presetName>"
        "</PTZPreset>"
    )
    await _isapi(target, "PUT", f"/presets/{free}", body)
    return PtzPreset(token=str(free), name=name)


# ---------------------------------------------------------------------------
# Umumiy API (router shu funksiyalarni chaqiradi)
# ---------------------------------------------------------------------------


def _check_protocol(target: PtzTarget) -> None:
    if target.protocol not in PROTOCOLS:
        raise PtzConfigError("Kamera uchun PTZ protokoli tanlanmagan (ONVIF yoki Hikvision ISAPI)")


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, float(value)))


def _cancel_auto_stop(camera_id: str) -> None:
    task = _auto_stop_tasks.pop(camera_id, None)
    if task is not None and not task.done() and task is not asyncio.current_task():
        task.cancel()


async def _auto_stop(target: PtzTarget, delay_s: float) -> None:
    try:
        await asyncio.sleep(delay_s)
        async with _lock_for(target.camera_id):
            if target.protocol == "onvif":
                await _onvif_stop(target)
            else:
                await _isapi_stop(target)
    except asyncio.CancelledError:
        raise
    except PtzError as exc:
        logger.warning("PTZ auto-to'xtatish bajarilmadi (kamera %s): %s", target.camera_id, exc.message)
    finally:
        if _auto_stop_tasks.get(target.camera_id) is asyncio.current_task():
            _auto_stop_tasks.pop(target.camera_id, None)


async def move(target: PtzTarget, pan: float, tilt: float, zoom: float, duration_ms: int | None = None) -> None:
    """Uzluksiz harakat (tezlik -1..1). duration_ms berilsa, shu vaqtdan
    keyin server kamerani o'zi to'xtatadi (brauzer "to'xtash"ni yubora
    olmay qolsa ham)."""
    _check_protocol(target)
    pan, tilt, zoom = _clamp(pan), _clamp(tilt), _clamp(zoom)
    _cancel_auto_stop(target.camera_id)
    async with _lock_for(target.camera_id):
        if target.protocol == "onvif":
            await _onvif_move(target, pan, tilt, zoom, duration_ms)
        else:
            await _isapi_move(target, pan, tilt, zoom)
    if duration_ms:
        delay = min(max(duration_ms, 100), MAX_MOVE_DURATION_MS) / 1000
        _auto_stop_tasks[target.camera_id] = asyncio.create_task(_auto_stop(target, delay))


async def stop(target: PtzTarget) -> None:
    _check_protocol(target)
    _cancel_auto_stop(target.camera_id)
    async with _lock_for(target.camera_id):
        if target.protocol == "onvif":
            await _onvif_stop(target)
        else:
            await _isapi_stop(target)


async def get_presets(target: PtzTarget) -> list[PtzPreset]:
    _check_protocol(target)
    async with _lock_for(target.camera_id):
        if target.protocol == "onvif":
            return await _onvif_presets(target)
        return await _isapi_presets(target)


async def goto_preset(target: PtzTarget, preset_token: str) -> None:
    _check_protocol(target)
    _cancel_auto_stop(target.camera_id)
    async with _lock_for(target.camera_id):
        if target.protocol == "onvif":
            await _onvif_goto(target, preset_token)
        else:
            await _isapi_goto(target, preset_token)


async def set_preset(target: PtzTarget, name: str) -> PtzPreset:
    """Kameraning HOZIRGI holatini yangi preset sifatida saqlaydi."""
    _check_protocol(target)
    async with _lock_for(target.camera_id):
        if target.protocol == "onvif":
            return await _onvif_set_preset(target, name)
        return await _isapi_set_preset(target, name)


def _join(*parts: str) -> str | None:
    return " ".join(p for p in parts if p) or None


async def _probe_onvif(target: PtzTarget, result: PtzProbeResult) -> None:
    invalidate_camera(target.camera_id)
    session = await _onvif_session(target, refresh=True)
    result.reachable = result.authenticated = result.ptz_supported = True
    try:
        info = await _soap(
            target,
            f"{target.base_url}/onvif/device_service",
            "<tds:GetDeviceInformation/>",
            time_offset=session.time_offset,
        )
        result.device_info = _join(_xml_text(info, "Manufacturer"), _xml_text(info, "Model"))
    except PtzError:
        # Qurilma nomi — qo'shimcha ma'lumot, PTZ ishlashiga ta'sir qilmaydi.
        pass
    try:
        presets = await _onvif_presets(target)
        result.presets_supported = True
        result.preset_count = len(presets)
    except PtzNotSupported:
        result.presets_supported = False


async def _probe_isapi(target: PtzTarget, result: PtzProbeResult) -> None:
    info = await _send(target, "GET", f"{target.base_url}/ISAPI/System/deviceInfo", auth=_digest_auth(target))
    result.reachable = True
    if info.status_code == 401:
        raise PtzAuthFailed("Kamera login yoki paroli noto'g'ri (ISAPI Digest autentifikatsiyasi rad etildi)")
    if info.status_code == 404:
        raise PtzNotSupported("Qurilma Hikvision ISAPI'ni qo'llab-quvvatlamaydi")
    if info.status_code == 200:
        root = _parse_xml(info.content)
        result.device_info = _join(_xml_text(root, "deviceName"), _xml_text(root, "model"))
    result.authenticated = True
    await _isapi(target, "GET", "/capabilities")
    result.ptz_supported = True
    try:
        presets = await _isapi_presets(target)
        result.presets_supported = True
        result.preset_count = len(presets)
    except PtzNotSupported:
        result.presets_supported = False


async def probe(target: PtzTarget) -> PtzProbeResult:
    """Ulanish, autentifikatsiya va PTZ imkoniyatlarini tekshiradi.

    target.protocol bo'sh bo'lsa — avval ONVIF, keyin ISAPI sinaladi va
    ishlagani qaytariladi. Ikkalasi ham ishlamasa, foydalanuvchiga ENG
    MA'NOLI xato ko'rsatiladi (parol > qo'llab-quvvatlamaydi > boshqa >
    ulanish): masalan ONVIF paroli rad etilgan, ISAPI porti yopiq bo'lsa,
    "parol noto'g'ri" — haqiqiy muammo shu."""
    protocols = [target.protocol] if target.protocol in PROTOCOLS else list(PROTOCOLS)
    started = time.perf_counter()
    failures: list[tuple[PtzError, PtzProbeResult]] = []
    for protocol in protocols:
        candidate = PtzTarget(
            camera_id=target.camera_id,
            host=target.host,
            port=target.port,
            username=target.username,
            password=target.password,
            protocol=protocol,
        )
        result = PtzProbeResult(success=False, message="", protocol=protocol, tried=list(protocols))
        try:
            async with _lock_for(target.camera_id):
                if protocol == "onvif":
                    await _probe_onvif(candidate, result)
                else:
                    await _probe_isapi(candidate, result)
        except PtzError as exc:
            if isinstance(exc, PtzAuthFailed):
                result.reachable = True
            if isinstance(exc, PtzNotSupported):
                result.reachable = result.authenticated = True
            result.message = exc.message
            failures.append((exc, result))
            continue
        result.success = True
        result.latency_ms = round((time.perf_counter() - started) * 1000)
        label = "ONVIF" if protocol == "onvif" else "Hikvision ISAPI"
        presets = f", {result.preset_count} ta preset" if result.preset_count is not None else ""
        result.message = f"PTZ ishlaydi ({label}{presets})"
        return result

    def rank(item: tuple[PtzError, PtzProbeResult]) -> int:
        exc = item[0]
        if isinstance(exc, PtzAuthFailed):
            return 0
        if isinstance(exc, PtzNotSupported):
            return 1
        if isinstance(exc, (PtzUnreachable, PtzTimeout)):
            return 3
        return 2

    _, best = min(failures, key=rank)
    best.latency_ms = round((time.perf_counter() - started) * 1000)
    return best
