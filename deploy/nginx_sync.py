#!/usr/bin/env python3
"""Production nginx sozlamalarini repodagi holatga keltirish — xavfsiz.

    sudo python3 /opt/camera/deploy/nginx_sync.py            # qo'llash
    sudo python3 /opt/camera/deploy/nginx_sync.py --dry-run  # faqat farq

Nima qiladi:
  * cam.fermi.uz — faylni ALMASHTIRMAYDI. Unga ilgari to'g'ridan-to'g'ri
    nusxalangan HLS location bloklarini (scripts/deploy_quick_fixes.py)
    olib tashlaydi, o'rniga repodagi fayllarni `include` qiladi va
    repodagi `listen` manzillaridan yo'qlarini qo'shadi.
  * camapi, stream.cam, storage.camapi — repodagi fayl bilan
    almashtiriladi. Sertifikat: repodagi yo'l shu serverda bor bo'lsa
    o'sha, bo'lmasa serverdagisi qoladi.

Har bir fayldan zaxira olinadi; `nginx -t` xato bersa hammasi avvalgi
holatiga qaytariladi. Qayta yuklangandan keyin har bir domen har bir
tinglash manzilida HAQIQATAN o'z sertifikatini berayotgani tekshiriladi:
avval ishlagan domen buzilsa — yana avvalgi holatga qaytariladi.
(2026-09-18: `listen 192.168.0.101:443` yo'qligi sababli LAN'dan
kirganlarga boshqa saytning sertifikati chiqqan, `nginx -t` esa buni
ko'rmagan edi.)
"""

from __future__ import annotations

import argparse
import difflib
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

APP_DIR = Path("/opt/camera")
REPO_NGINX = APP_DIR / "deploy" / "nginx"
AVAILABLE = Path("/etc/nginx/sites-available")
ENABLED = Path("/etc/nginx/sites-enabled")

SECURITY_INCLUDE = f"include {REPO_NGINX.as_posix()}/cam-security-headers.conf;"
CSP_INCLUDE = f"include {REPO_NGINX.as_posix()}/cam-frontend-csp.conf;"
STREAM_INCLUDE = f"include {REPO_NGINX.as_posix()}/cam-fermi-stream-locations.conf;"

# Eski nusxalangan HLS bloklari va ularning sarlavha izohlari.
_STREAM_LOCATION = re.compile(r'^location\s+(?:~\s+\^/cam-|/s[0-9]+/|~\s+"\^/s[0-9]+/)')
_STREAM_COMMENTS = (
    "# Include inside cam.fermi.uz HTTPS server",
    "# Requires /etc/nginx/conf.d/camera-stream-shard-map.conf",
)


@dataclass
class Block:
    header: str  # masalan "server" yoki "location /s0/"
    start: int  # sarlavha boshlanadigan qator boshi
    open: int  # "{" indeksi
    close: int  # "}" indeksi
    depth: int


def parse_blocks(text: str) -> list[Block]:
    """Qavslarni sanab bloklarni topadi; izoh va qo'shtirnoq ichidagi
    qavslarni hisobga olmaydi (masalan regex'dagi `{22}`)."""
    blocks: list[Block] = []
    stack: list[tuple[int, int]] = []
    stmt_start = 0
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch == "#":
            newline = text.find("\n", i)
            i = len(text) if newline == -1 else newline
            continue
        elif ch in "\"'":
            quote = ch
        elif ch == "{":
            stack.append((stmt_start, i))
            stmt_start = i + 1
        elif ch == "}":
            start, open_idx = stack.pop()
            header = " ".join(re.sub(r"#[^\n]*", "", text[start:open_idx]).split())
            # Sarlavhadan oldingi izoh/bo'sh qatorlarni o'tkazib yuboramiz.
            header_lines = text[start:open_idx].splitlines(keepends=True)
            offset = start
            for line in header_lines:
                if line.strip() and not line.strip().startswith("#"):
                    break
                offset += len(line)
            blocks.append(Block(header, text.rfind("\n", 0, offset) + 1, open_idx, i, len(stack)))
            stmt_start = i + 1
        elif ch == ";":
            stmt_start = i + 1
        i += 1
    if stack or quote:
        raise ValueError("nginx faylida qavslar yoki qo'shtirnoqlar juftlashmagan")
    return sorted(blocks, key=lambda b: b.open)


def _https_server(text: str) -> Block:
    for block in parse_blocks(text):
        if block.depth == 0 and block.header == "server" and re.search(r"\blisten\s+443\b", text[block.open : block.close]):
            return block
    raise ValueError("443-portdagi server bloki topilmadi")


def _line_end(text: str, index: int) -> int:
    newline = text.find("\n", index)
    return len(text) if newline == -1 else newline + 1


def _insert_before_line(text: str, index: int, line: str) -> str:
    line_start = text.rfind("\n", 0, index) + 1
    return text[:line_start] + line + "\n" + text[line_start:]


def _collapse_blank_lines(text: str) -> str:
    text = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text)
    # Yopuvchi qavsdan oldin bo'sh qator qolmasin.
    return re.sub(r"\n[ \t]*\n([ \t]*\})", r"\n\1", text)


_LISTEN = re.compile(r"^[ \t]*listen[ \t]+([^;]+);", re.MULTILINE)


def _listen_addresses(text: str, server: Block) -> dict[str, str]:
    """server blokining `listen` qatorlari: manzil -> to'liq qiymat."""
    listens = {}
    for match in _LISTEN.finditer(text, server.open, server.close):
        value = " ".join(match.group(1).split())
        listens.setdefault(value.split()[0], value)
    return listens


def _add_missing_listens(text: str, desired: str) -> str:
    """Repodagi 443-server tinglaydigan manzillar serverdagi faylda ham bo'lsin.

    2026-09-18: serverdagi cam.fermi.uz.conf da `listen 192.168.0.101:443`
    yo'q edi — bu manzilda cam.fermi.uz ni takroriy cam-fermi-frontend.conf
    ushlab turardi. Takroriy fayl o'chirilgach, LAN'dan kirganlarga boshqa
    saytning sertifikati chiqdi. Faqat manzil taqqoslanadi: `443 ssl http2`
    bor joyga `443 ssl` qo'shilmaydi (nginx takroriy listen'ni rad etadi)."""
    server = _https_server(text)
    have = _listen_addresses(text, server)
    missing = [value for address, value in _listen_addresses(desired, _https_server(desired)).items() if address not in have]
    if not missing:
        return text
    last = list(_LISTEN.finditer(text, server.open, server.close))[-1]
    insert_at = _line_end(text, last.end())
    return text[:insert_at] + "".join(f"    listen {value};\n" for value in missing) + text[insert_at:]


def migrate_frontend(text: str, desired: str | None = None) -> str:
    """cam.fermi.uz: nusxalangan HLS bloklari -> include, xavfsizlik sarlavhalari.

    `desired` — repodagi fayl: undan faqat `listen` manzillari olinadi."""
    # 0) Tinglash manzillari.
    if desired is not None:
        text = _add_missing_listens(text, desired)

    # 1) Eski HLS bloklarini olib tashlash (oxiridan boshlab — indekslar siljimasin).
    server = _https_server(text)
    stale = [
        b for b in parse_blocks(text)
        if b.depth == 1 and server.open < b.open < server.close and _STREAM_LOCATION.match(b.header)
    ]
    for block in sorted(stale, key=lambda b: b.open, reverse=True):
        end = _line_end(text, block.close)
        text = text[: block.start] + text[end:]
    text = "".join(
        line for line in text.splitlines(keepends=True) if not line.strip().startswith(_STREAM_COMMENTS)
    )
    text = _collapse_blank_lines(text)

    # 2) Server darajasidagi include'lar — birinchi location'dan oldin.
    server = _https_server(text)
    missing = [inc for inc in (SECURITY_INCLUDE, CSP_INCLUDE) if inc not in text[server.open : server.close]]
    if missing:
        first_location = next(
            (b for b in parse_blocks(text) if b.depth == 1 and server.open < b.open < server.close), None
        )
        anchor = first_location.start if first_location else server.close
        text = _insert_before_line(text, anchor, "".join(f"    {inc}\n" for inc in missing))

    # 3) O'z add_header'i bor location'lar tashqi sarlavhalarni meros
    #    qilmaydi — ularga ham qo'shamiz.
    while True:
        server = _https_server(text)
        missing = next(
            (
                b for b in parse_blocks(text)
                if b.depth == 1
                and server.open < b.open < server.close
                and "add_header" in text[b.open : b.close]
                and SECURITY_INCLUDE not in text[b.open : b.close]
            ),
            None,
        )
        if missing is None:
            break
        text = _insert_before_line(text, missing.close, f"        {SECURITY_INCLUDE}")

    # 4) HLS — server blokining oxirida.
    server = _https_server(text)
    if STREAM_INCLUDE not in text[server.open : server.close]:
        text = _insert_before_line(
            text, server.close, f"\n    # Jonli video (HLS) — admin paneli bilan bir xil manzilda.\n    {STREAM_INCLUDE}"
        )
    return _collapse_blank_lines(text)


_CERT = re.compile(r"^(\s*)(ssl_certificate(?:_key)?)\s+([^;]+);", re.MULTILINE)


def keep_certificates(existing: str, desired: str, exists=lambda path: Path(path).exists()) -> str:
    """Repodagi faylni oladi. Sertifikat yo'li: repodagisi shu serverda
    bor bo'lsa — o'sha (serverdagi fayl eskirgan bo'lishi mumkin, masalan
    2026-09-18 dagi /etc/ssl/camera-devflix), aks holda serverdagisi."""
    current = {}
    for _, name, value in _CERT.findall(existing):
        current.setdefault(name, value.strip())
    if not current:
        return desired

    def choose(match: re.Match) -> str:
        wanted = match[3].strip()
        path = wanted if exists(wanted) else current.get(match[2], wanted)
        return f"{match[1]}{match[2]} {path};"

    return _CERT.sub(choose, desired)


SITES = {
    "cam.fermi.uz.conf": "cam-fermi-frontend.conf",
    "camapi.fermi.uz.conf": "cam-fermi-api.conf",
    "stream.cam.fermi.uz.conf": "cam-fermi-stream.conf",
    "storage.camapi.fermi.uz.conf": "cam-fermi-storage.conf",
}


def effective_path(site: str) -> Path:
    """nginx aslida o'qiydigan fayl: sites-enabled dagi havola nishoni yoki
    (ba'zi serverlarda) u yerdagi oddiy nusxaning o'zi."""
    enabled = ENABLED / site
    return enabled.resolve() if enabled.exists() else AVAILABLE / site


def planned_changes() -> dict[str, tuple[Path, str]]:
    changes: dict[str, tuple[Path, str]] = {}
    for site, repo_name in SITES.items():
        target = effective_path(site)
        desired = (REPO_NGINX / repo_name).read_text()
        if not target.exists():
            text = desired
        elif site == "cam.fermi.uz.conf":
            text = migrate_frontend(target.read_text(), desired)
        else:
            text = keep_certificates(target.read_text(), desired)
        changes[site] = (target, text)
    return changes


def _nginx_ok() -> bool:
    result = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    sys.stdout.write(result.stderr)
    return result.returncode == 0


def https_domains(text: str) -> list[str]:
    server = _https_server(text)
    match = re.search(r"^[ \t]*server_name[ \t]+([^;]+);", text[server.open : server.close], re.MULTILINE)
    return match.group(1).split() if match else []


def listen_hosts(texts: list[str]) -> list[str]:
    """Tekshiriladigan IPv4 manzillar: 127.0.0.1 va `listen IP:443` dagilar."""
    hosts = {"127.0.0.1"}
    for text in texts:
        for value in _LISTEN.findall(text):
            first = value.split()[0]
            if ":" in first and not first.startswith("["):
                host = first.rsplit(":", 1)[0]
                if host not in ("*", "0.0.0.0"):
                    hosts.add(host)
    return sorted(hosts)


def certificate_problems(targets: list[tuple[str, str]]) -> dict[str, str]:
    """"domen @ manzil" -> xato. Bo'sh — hammasi o'z sertifikatini beryapti."""
    context = ssl.create_default_context()
    problems: dict[str, str] = {}
    for domain, host in targets:
        key = f"{domain} @ {host}"
        try:
            with socket.create_connection((host, 443), timeout=5) as raw:
                with context.wrap_socket(raw, server_hostname=domain):
                    pass
        except ssl.SSLCertVerificationError as exc:
            problems[key] = exc.verify_message or str(exc)
        except OSError as exc:
            problems[key] = f"{type(exc).__name__}: {exc}"
    return problems


def _restore(backups: dict[Path, Path | None], removed_links: dict[Path, Path]) -> None:
    for path, backup in backups.items():
        if backup is None:
            path.unlink(missing_ok=True)
        else:
            shutil.copy2(backup, path)
    for link, target in removed_links.items():
        if not link.exists() and not link.is_symlink():
            link.symlink_to(target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="faqat farqni ko'rsatish")
    args = parser.parse_args()

    changes = planned_changes()
    changed = {p: t for p, t in changes.values() if not p.exists() or p.read_text() != t}
    for path, text in changed.items():
        old = path.read_text().splitlines(keepends=True) if path.exists() else []
        sys.stdout.writelines(difflib.unified_diff(old, text.splitlines(keepends=True), str(path), f"{path} (yangi)"))
    if not changed:
        print("[nginx-sync] o'zgarish yo'q")

    desired_texts = [text for _, text in changes.values()]
    targets = [(domain, host) for text in desired_texts for domain in https_domains(text) for host in listen_hosts(desired_texts)]
    before = certificate_problems(targets)
    for key, problem in before.items():
        print(f"[nginx-sync] OGOHLANTIRISH (hozir ham): {key}: {problem}")
    if args.dry_run:
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backups: dict[Path, Path | None] = {}
    for path, text in changed.items():
        if path.exists():
            # Zaxira HAR DOIM sites-available da: sites-enabled dagi har bir
            # fayl nginx'ga yuklanadi, u yerdagi .bak ham.
            backup = AVAILABLE / f"{path.name}.bak.{stamp}"
            shutil.copy2(path, backup)
            backups[path] = backup
        else:
            backups[path] = None
        path.write_text(text)

    # Eski takroriy nomlar (cam-fermi-*.conf) — bir server_name ikki marta bo'lmasin.
    removed_links: dict[Path, Path] = {}
    for duplicate in ("cam-fermi-frontend", "cam-fermi-api", "cam-fermi-storage", "cam-fermi-stream"):
        link = ENABLED / f"{duplicate}.conf"
        if link.exists() or link.is_symlink():
            print(f"[nginx-sync] takroriy sayt o'chirildi: {link} (nishoni: {link.resolve()})")
            if link.is_symlink():
                removed_links[link] = Path(link.readlink())
            else:
                backup = AVAILABLE / f"{link.name}.enabled-copy.{stamp}"
                shutil.copy2(link, backup)
                removed_links[link] = backup
            link.unlink()
    for site, (target, _) in changes.items():
        link = ENABLED / site
        if not link.exists() and not link.is_symlink():
            link.symlink_to(target)

    if not _nginx_ok():
        _restore(backups, removed_links)
        print("[nginx-sync] XATO: nginx -t o'tmadi — barcha fayllar avvalgi holatiga qaytarildi", file=sys.stderr)
        return 1
    subprocess.run(["systemctl", "reload", "nginx"], check=True)
    time.sleep(1)

    after = certificate_problems(targets)
    broken = {key: problem for key, problem in after.items() if key not in before}
    if broken:
        for key, problem in broken.items():
            print(f"[nginx-sync] XATO: {key}: {problem}", file=sys.stderr)
        _restore(backups, removed_links)
        if _nginx_ok():
            subprocess.run(["systemctl", "reload", "nginx"], check=True)
        print("[nginx-sync] ishlab turgan domen buzildi — barcha fayllar avvalgi holatiga qaytarildi", file=sys.stderr)
        return 1
    for key, problem in after.items():
        print(f"[nginx-sync] OGOHLANTIRISH (avvaldan bor): {key}: {problem}")
    print(f"[nginx-sync] qo'llandi ({len(changed)} fayl), zaxiralar: *.bak.{stamp}; sertifikatlar tekshirildi")
    return 0


if __name__ == "__main__":
    sys.exit(main())
