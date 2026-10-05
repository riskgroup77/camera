"""Imzolangan HLS havolalari: API bergan imzoni nginx qabul qilishi shart.

nginx'ning o'zini bu yerda ishga tushirib bo'lmaydi, shuning uchun
deploy/nginx/cam-fermi-stream-locations.conf dagi regex va
`secure_link_md5` ifodasi to'g'ridan-to'g'ri o'qib olinib, API yasagan
havolaga qo'llanadi — ikki tomon bir-biridan ajrab ketsa, test yiqiladi.
"""

import re
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.models import Building, Camera
from app.services.stream_links import BUCKET_SECONDS, link_expiry, signed_stream_url, stream_signature
from tests.conftest import auth_headers

SECRET = "test-secret"
CAMERA = "cam-3a36558e-cb3e-4ef7-b13a-abce86db8669"
NOW = 1_789_000_000.0
LOCATIONS = Path(__file__).resolve().parents[2] / "deploy" / "nginx" / "cam-fermi-stream-locations.conf"


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setattr(settings, "stream_url_secret", SECRET)


class TestSigning:
    def test_without_a_secret_links_are_left_alone(self, monkeypatch):
        monkeypatch.setattr(settings, "stream_url_secret", "")
        url = f"/s1/{CAMERA}/index.m3u8"
        assert signed_stream_url(url) == url
        assert signed_stream_url(None) is None

    def test_matches_the_openssl_recipe_from_the_nginx_docs(self):
        # echo -n '1789000000/s1/<kamera> test-secret' | openssl md5 -binary \
        #   | openssl base64 | tr +/ -_ | tr -d =
        assert stream_signature("/s1", CAMERA, 1_789_000_000, SECRET) == "Xv6iZVCRwP-2CqeG-EiXqw"

    def test_signature_sits_in_the_path_so_segments_inherit_it(self, secret):
        signed = signed_stream_url(f"/s1/{CAMERA}/index.m3u8", now=NOW)
        expires = link_expiry(NOW)
        signature = stream_signature("/s1", CAMERA, expires, SECRET)
        assert signed == f"/s1/{signature},{expires}/{CAMERA}/index.m3u8"

    def test_absolute_links_keep_their_origin(self, secret):
        signed = signed_stream_url(f"https://stream.cam.fermi.uz/s2/{CAMERA}/index.m3u8", now=NOW)
        assert signed.startswith("https://stream.cam.fermi.uz/s2/")
        assert signed.endswith(f"/{CAMERA}/index.m3u8")

    @pytest.mark.parametrize(
        "url",
        [
            f"/{CAMERA}/index.m3u8",  # shardsiz eski havola
            "http://127.0.0.1:8888/cam-1/index.m3u8",  # lokal
            "rtsp://10.0.0.5/Streaming/Channels/101",
        ],
    )
    def test_links_nginx_does_not_guard_are_not_touched(self, secret, url):
        assert signed_stream_url(url) == url

    def test_link_is_stable_within_a_bucket_so_players_do_not_restart(self, secret):
        bucket_start = (int(NOW) // BUCKET_SECONDS) * BUCKET_SECONDS
        url = f"/s0/{CAMERA}/index.m3u8"
        assert signed_stream_url(url, now=bucket_start) == signed_stream_url(url, now=bucket_start + BUCKET_SECONDS - 1)
        assert signed_stream_url(url, now=bucket_start) != signed_stream_url(url, now=bucket_start + BUCKET_SECONDS)

    def test_link_outlives_the_login_that_fetched_it(self):
        for now in (NOW, NOW + 1, NOW + BUCKET_SECONDS - 1):
            assert link_expiry(now) >= now + settings.jwt_ttl_hours * 3600

    def test_signature_is_bound_to_camera_and_shard(self):
        base = stream_signature("/s0", CAMERA, 1_789_000_000, SECRET)
        assert stream_signature("/s1", CAMERA, 1_789_000_000, SECRET) != base
        assert stream_signature("/s0", "cam-00000000-0000-0000-0000-000000000000", 1_789_000_000, SECRET) != base
        assert stream_signature("/s0", CAMERA, 1_789_000_001, SECRET) != base


def _nginx_signed_locations() -> list[tuple[str, str, str]]:
    """(shard, regex, secure_link_md5 ifodasi) — nginx faylidan."""
    text = LOCATIONS.read_text(encoding="utf-8")
    found = re.findall(
        r'location ~ "(\^/(s[0-9]+)/[^"]+)" \{.*?secure_link_md5 "([^"]+)";', text, flags=re.DOTALL
    )
    return [(shard, regex, expression) for regex, shard, expression in found]


@pytest.mark.skipif(not LOCATIONS.exists(), reason="deploy/ katalogi yo'q (konteyner ichida)")
class TestNginxAgreesWithTheApi:
    def test_every_shard_has_a_signed_location(self):
        assert [shard for shard, _, _ in _nginx_signed_locations()] == ["s0", "s1", "s2"]

    @pytest.mark.parametrize("tail", ["/index.m3u8", "/video1_stream.m3u8", "/video1_s_1_seg12.mp4"])
    def test_nginx_accepts_what_the_api_signs(self, secret, tail):
        for shard, regex, expression in _nginx_signed_locations():
            signed = signed_stream_url(f"/{shard}/{CAMERA}{tail}", now=NOW)
            match = re.match(regex.replace("(?<", "(?P<"), signed)
            assert match is not None, (shard, signed)
            assert match["cam_link_camera"] == CAMERA
            assert match["cam_link_tail"] == tail
            # nginx ifodasidagi o'zgaruvchilarni o'rniga qo'yib, xuddi nginx
            # kabi MD5 hisoblaymiz.
            hashed = (
                expression.replace("$cam_link_expires", match["cam_link_expires"])
                .replace("$cam_link_camera", match["cam_link_camera"])
                .replace("$cam_stream_secret", SECRET)
            )
            expires, rest = hashed.split("/", 1)
            path, key = rest.rsplit(" ", 1)
            assert stream_signature(f"/{path.split('/')[0]}", path.split("/", 1)[1], int(expires), key) == match[
                "cam_link_hash"
            ]

    def test_a_forged_hash_does_not_reach_the_signed_location(self, secret):
        _, regex, _ = _nginx_signed_locations()[0]
        signed = signed_stream_url(f"/s0/{CAMERA}/index.m3u8", now=NOW)
        forged = signed.replace(",", "x,", 1)
        assert re.match(regex.replace("(?<", "(?P<"), forged) is None


class TestApiReturnsSignedLinks:
    @pytest.fixture
    async def camera(self, db_session, seeded):
        building = (await db_session.execute(select(Building))).scalars().first()
        camera_id = uuid.UUID(CAMERA.removeprefix("cam-"))
        camera = Camera(id=camera_id, name="Kirish-1", ip="10.1.0.1", building_id=building.id, zone="Asosiy kirish",
                        resolution="1080p", status="faol", stream_url=f"/s1/{CAMERA}/index.m3u8")
        db_session.add(camera)
        await db_session.commit()
        return camera

    async def test_admin_and_monitoring_lists_carry_the_signature(self, client: AsyncClient, camera, secret):
        headers = await auth_headers(client, "admin", "admin123")
        for path in ("/api/cameras", "/api/public/cameras"):
            resp = await client.get(path, headers=headers)
            assert resp.status_code == 200, resp.text
            url = resp.json()["items"][0]["streamUrl"]
            assert re.fullmatch(rf"/s1/[A-Za-z0-9_-]{{22}},[0-9]+/{CAMERA}/index\.m3u8", url), (path, url)

    async def test_the_stored_link_stays_unsigned(self, client: AsyncClient, db_session, camera, secret):
        headers = await auth_headers(client, "admin", "admin123")
        await client.get("/api/cameras", headers=headers)
        await db_session.refresh(camera)
        assert camera.stream_url == f"/s1/{CAMERA}/index.m3u8"
