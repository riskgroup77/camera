"""deploy/nginx_sync.py — production nginx fayllarini xavfsiz yangilash.

2026-09-18 dagi deploy'da serverdagi cam.fermi.uz.conf da
`listen 192.168.0.101:443` yo'q edi, bu manzilni takroriy fayl ushlab
turardi. Takroriy fayl o'chirilgach LAN'dan kirganlarga boshqa saytning
sertifikati chiqdi. Bu testlar o'sha holatni qayta tiklab tekshiradi.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "nginx_sync.py"
pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="deploy/ katalogi yo'q (konteyner ichida)")

# 2026-09-18 da serverda turgan fayl (bugungi o'zgarishlardan oldin).
SERVER_FILE = """server {
    listen 80;
    listen [::]:80;
    server_name cam.fermi.uz;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name cam.fermi.uz;

    ssl_certificate /etc/letsencrypt/live/cam.fermi.uz/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/cam.fermi.uz/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    root /var/www/cam.fermi.uz;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
}
"""

# Eski skriptlar server blokiga to'g'ridan-to'g'ri nusxalagan HLS bloklari.
OLD_INLINE_STREAM = """
# Include inside cam.fermi.uz HTTPS server { } block — HLS proxy (same origin as admin UI).
# Requires /etc/nginx/conf.d/camera-stream-shard-map.conf in http { }.

    location ~ ^/cam-[0-9a-f-]+ {
        return 301 https://$host/s$legacy_camera_shard$request_uri;
    }

    location /s0/ {
        proxy_pass http://127.0.0.1:8888/;
        proxy_set_header Authorization "Bearer fermi-hls-cdn-secret-2026";
    }

    location /s1/ {
        proxy_pass http://127.0.0.1:8889/;
    }
"""


@pytest.fixture(scope="module")
def sync():
    spec = importlib.util.spec_from_file_location("nginx_sync", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["nginx_sync"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("nginx_sync", None)


@pytest.fixture(scope="module")
def repo_frontend() -> str:
    return (SCRIPT.parent / "nginx" / "cam-fermi-frontend.conf").read_text(encoding="utf-8")


def _https_listens(sync, text: str) -> list[str]:
    return list(sync._listen_addresses(text, sync._https_server(text)))


class TestListenAddresses:
    def test_the_lan_address_missing_on_the_server_is_added(self, sync, repo_frontend):
        migrated = sync.migrate_frontend(SERVER_FILE, repo_frontend)

        assert _https_listens(sync, migrated) == ["443", "[::]:443", "192.168.0.101:443"]
        assert migrated.count("listen 192.168.0.101:443 ssl;") == 1
        # Port 80 bloki o'zgarmaydi.
        assert migrated.split("server {")[1] == SERVER_FILE.split("server {")[1]

    def test_running_twice_changes_nothing(self, sync, repo_frontend):
        once = sync.migrate_frontend(SERVER_FILE, repo_frontend)
        assert sync.migrate_frontend(once, repo_frontend) == once

    def test_an_address_with_other_options_is_not_duplicated(self, sync, repo_frontend):
        server = SERVER_FILE.replace("    listen 443 ssl;\n", "    listen 443 ssl http2;\n", 1)
        migrated = sync.migrate_frontend(server, repo_frontend)
        assert "listen 443 ssl http2;" in migrated
        assert "listen 443 ssl;" not in migrated

    def test_the_repo_file_already_listens_everywhere(self, sync, repo_frontend):
        assert sync.migrate_frontend(repo_frontend, repo_frontend) == repo_frontend


class TestStreamLocations:
    def test_inline_blocks_become_one_include(self, sync, repo_frontend):
        idx = SERVER_FILE.rfind("\n}")
        server = SERVER_FILE[:idx] + "\n" + OLD_INLINE_STREAM + SERVER_FILE[idx:]

        migrated = sync.migrate_frontend(server, repo_frontend)

        for stale in ("location /s0/", "location /s1/", "^/cam-", "fermi-hls-cdn", "Include inside"):
            assert stale not in migrated, stale
        assert migrated.count(sync.STREAM_INCLUDE) == 1
        assert migrated.count(sync.CSP_INCLUDE) == 1
        # Server darajasida va o'z add_header'i bor statik fayllar blokida.
        assert migrated.count(sync.SECURITY_INCLUDE) == 2

    def test_the_result_matches_the_repo_file(self, sync, repo_frontend):
        def meaningful(text):
            return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]

        migrated = sync.migrate_frontend(SERVER_FILE, repo_frontend)
        assert sorted(meaningful(migrated)) == sorted(meaningful(repo_frontend))


class TestCertificates:
    def test_server_paths_are_kept_when_the_repo_ones_are_not_on_this_server(self, sync):
        desired = (SCRIPT.parent / "nginx" / "cam-fermi-api.conf").read_text(encoding="utf-8")
        existing = desired.replace("/etc/letsencrypt/live/cam.fermi.uz/", "/etc/letsencrypt/live/camapi-0001/")

        kept = sync.keep_certificates(existing, desired, exists=lambda path: False)

        assert "live/camapi-0001/fullchain.pem" in kept
        assert "live/camapi-0001/privkey.pem" in kept
        assert "live/cam.fermi.uz/" not in kept

    def test_a_stale_server_path_gives_way_to_an_existing_repo_path(self, sync):
        """2026-09-18: serverdagi storage fayli /etc/ssl/camera-devflix ga ishora qilardi."""
        desired = (SCRIPT.parent / "nginx" / "cam-fermi-storage.conf").read_text(encoding="utf-8")
        existing = desired.replace("/etc/letsencrypt/live/storage.camapi.fermi.uz/", "/etc/ssl/camera-devflix/")

        kept = sync.keep_certificates(existing, desired, exists=lambda path: "letsencrypt" in path)

        assert "/etc/ssl/camera-devflix/" not in kept
        assert kept.count("/etc/letsencrypt/live/storage.camapi.fermi.uz/") == 2


class TestCertificateCheckTargets:
    def test_every_managed_domain_is_checked_on_every_listen_address(self, sync):
        texts = [(SCRIPT.parent / "nginx" / name).read_text(encoding="utf-8") for name in sync.SITES.values()]

        domains = sorted(domain for text in texts for domain in sync.https_domains(text))
        hosts = sync.listen_hosts(texts)

        assert domains == ["cam.fermi.uz", "camapi.fermi.uz", "storage.camapi.fermi.uz", "stream.cam.fermi.uz"]
        assert hosts == ["127.0.0.1", "192.168.0.101"]

    def test_every_repo_site_listens_on_the_lan_address(self, sync):
        for name in sync.SITES.values():
            text = (SCRIPT.parent / "nginx" / name).read_text(encoding="utf-8")
            assert "192.168.0.101:443" in sync._listen_addresses(text, sync._https_server(text)), name

    def test_an_unreachable_address_is_reported_not_raised(self, sync):
        problems = sync.certificate_problems([("cam.fermi.uz", "127.0.0.1")])
        # Test mashinasida 443 da hech narsa yo'q: xato — lekin istisno emas.
        assert set(problems) <= {"cam.fermi.uz @ 127.0.0.1"}
