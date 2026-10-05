"""Brauzerga beriladigan HLS havolalarini imzolash.

MediaMTX'ning o'zida foydalanuvchi tekshiruvi yo'q — ilgari
`cam.fermi.uz/s0/cam-<uuid>/index.m3u8` ni bilgan har kim kamerani
login qilmasdan ko'ra olardi. Endi nginx
(deploy/nginx/cam-fermi-stream-locations.conf) faqat shu yerda
imzolangan havolalarni o'tkazadi. Imzo havola YO'LIDA turadi:

    /s0/cam-<uuid>/index.m3u8  ->  /s0/<md5>,<muddat>/cam-<uuid>/index.m3u8

Pleylist ichidagi segment havolalari nisbiy, shuning uchun ular shu
prefiksni o'zi meros qiladi: hls.js ham, Safari'ning o'z pleyeri ham
qo'shimcha sarlavhasiz ishlaydi, nginx esa har bir segment uchun API'ga
murojaat qilmaydi. Imzo bitta kamera va bitta shardga bog'langan.

Bazadagi Camera.stream_url imzosiz qoladi — AI kadr oluvchi uni ichki
manzilga aylantiradi (video_gateway.public_hls_to_internal). Imzo faqat
API javobiga qo'shiladi.
"""

import base64
import hashlib
import re
import time

from app.config import settings

# nginx'dagi regex bilan bir xil shakl (tests/test_stream_links.py ikkalasini
# solishtiradi).
_SHARD_URL = re.compile(r"^(?P<origin>https?://[^/]+)?(?P<shard>/s[0-9]+)/(?P<cam>cam-[0-9a-f-]+)(?P<tail>/.*)$")
# Havola shu oraliq ichida o'zgarmaydi: monitoring devori kamera ro'yxatini
# qayta yuklaganda pleyerlar qayta ulanib, tasvir "miltillamaydi".
BUCKET_SECONDS = 6 * 3600


def link_expiry(now: float) -> int:
    """Oraliq oxiridan kamida bitta sessiya (JWT) uzunligicha keyin.

    Ya'ni havola foydalanuvchining login muddatidan oldin eskirmaydi —
    tizimga kirgan odamning devori tunda o'zi o'chib qolmaydi.
    """
    bucket_end = (int(now) // BUCKET_SECONDS + 1) * BUCKET_SECONDS
    return bucket_end + settings.jwt_ttl_hours * 3600


def stream_signature(shard: str, cam: str, expires: int, secret: str) -> str:
    """nginx `secure_link_md5 "$exp/sN/$cam $secret"` bilan aynan bir xil.

    MD5 — nginx secure_link modulining o'z algoritmi; sir oxirida turgani
    uchun uzunlik kengaytirish hujumi bu yerda ishlamaydi.
    """
    digest = hashlib.md5(f"{expires}{shard}/{cam} {secret}".encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def signed_stream_url(url: str | None, *, now: float | None = None) -> str | None:
    """Sir sozlanmagan bo'lsa (lokal ishlab chiqish) havola o'zgarmaydi."""
    secret = settings.stream_url_secret
    if not url or not secret:
        return url
    match = _SHARD_URL.match(url)
    if match is None:
        return url
    expires = link_expiry(time.time() if now is None else now)
    signature = stream_signature(match["shard"], match["cam"], expires, secret)
    return f"{match['origin'] or ''}{match['shard']}/{signature},{expires}/{match['cam']}{match['tail']}"
