"""Productionga qo'lda deploy — GitHub Actions (.github/workflows/deploy.yml)
bilan AYNAN bir xil yo'l: serverga SSH orqali kirib deploy/server-pull.sh ni
ishga tushiradi. Deploy mantiqi faqat o'sha skriptda — bu yerda takrorlanmaydi.

    set DEPLOY_HOST=87.192.230.208
    set DEPLOY_PORT=2222
    set DEPLOY_USER=admin_root
    set DEPLOY_SSH_KEY=C:\\Users\\me\\.ssh\\camera_deploy      (yoki CAMERA_DEPLOY_PASSWORD)
    python scripts/deploy_now.py [--ref <commit-sha>]

DEPLOY_HOST vergul bilan bir nechta bo'lishi mumkin ("host:port" ham) —
birinchisi ulanmasa keyingisi sinaladi (masalan tashqi IP va LAN IP).
Parol kodda saqlanmaydi (u ilgari git tarixiga tushib qolgan edi).
"""

import argparse
import os
import re
import shlex
import sys

import paramiko

DEFAULT_HOSTS = "87.192.230.208:2222,192.168.0.101:22"
DEFAULT_USER = "admin_root"


def _hosts() -> list[tuple[str, int]]:
    raw = os.environ.get("DEPLOY_HOST") or DEFAULT_HOSTS
    default_port = int(os.environ.get("DEPLOY_PORT") or 22)
    hosts: list[tuple[str, int]] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        host, _, port = item.partition(":")
        hosts.append((host, int(port) if port else default_port))
    return hosts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ref", default="", help="joylanadigan commit SHA (standart: origin/main)")
    parser.add_argument("--path", default=os.environ.get("DEPLOY_PATH", "/opt/camera"), help="serverdagi repo papkasi")
    args = parser.parse_args()

    if args.ref and not re.fullmatch(r"[0-9a-fA-F]{7,40}", args.ref):
        print("XATO: --ref faqat commit SHA bo'lishi mumkin")
        return 2
    if not re.fullmatch(r"/[A-Za-z0-9._/-]+", args.path):
        print("XATO: --path noto'g'ri")
        return 2

    user = os.environ.get("DEPLOY_USER") or DEFAULT_USER
    key_path = os.environ.get("DEPLOY_SSH_KEY") or None
    password = os.environ.get("CAMERA_DEPLOY_PASSWORD") or None
    if not key_path and not password:
        print("XATO: DEPLOY_SSH_KEY (kalit fayli) yoki CAMERA_DEPLOY_PASSWORD bering.")
        return 2

    command = f"sudo -n bash {shlex.quote(args.path + '/deploy/server-pull.sh')}"
    if args.ref:
        command += f" --ref {shlex.quote(args.ref)}"
    if password and not key_path:
        # Parol bilan kirilganda sudo ham parol so'rashi mumkin — stdin orqali beriladi.
        command = command.replace("sudo -n", "sudo -S -p ''", 1)

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    # Birinchi ulanishda host kaliti ~/.ssh/known_hosts da bo'lmasa — ogohlantirib qabul qilinadi.
    client.set_missing_host_key_policy(paramiko.WarningPolicy())
    connected = None
    for host, port in _hosts():
        try:
            print(f"Ulanish: {host}:{port} ...")
            client.connect(host, port=port, username=user, key_filename=key_path, password=password, timeout=30)
            connected = f"{host}:{port}"
            break
        except Exception as exc:  # noqa: BLE001 — keyingi manzil sinaladi
            print(f"  bo'lmadi: {exc}")
    if connected is None:
        print("XATO: hech bir serverga ulanib bo'lmadi")
        return 1

    channel = client.get_transport().open_session(timeout=30)
    channel.settimeout(2400)
    channel.set_combine_stderr(True)
    channel.exec_command(command)
    if password and not key_path:
        channel.sendall((password + "\n").encode())
    channel.shutdown_write()
    output = channel.makefile("r", -1)
    for line in output:
        sys.stdout.write(line if isinstance(line, str) else line.decode("utf-8", errors="replace"))
        sys.stdout.flush()
    code = channel.recv_exit_status()
    client.close()
    print(f"Deploy {connected} da tugadi, kod {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
