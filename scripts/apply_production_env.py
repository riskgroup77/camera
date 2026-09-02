"""Merge deploy/env.production.scale into server camera-api/.env and restart API."""
import os
import sys
from pathlib import Path

import paramiko

HOSTS = [("87.192.230.208", 2222), ("192.168.0.101", 22)]
USER = "admin_root"
PASSWORD = os.environ.get("CAMERA_DEPLOY_PASSWORD")
if not PASSWORD:
    sys.exit(
        "CAMERA_DEPLOY_PASSWORD muhit ozgaruvchisi ornatilmagan. "
        "Server paroli endi kodda saqlanmaydi - u git tarixiga tushib qolgan edi. "
        "Ishlatishdan oldin uni muhit ozgaruvchisi sifatida bering."
    )

SCALE_FILE = Path(__file__).resolve().parent.parent / "deploy" / "env.production.scale"

APPLY = r"""
set -e
cd /opt/camera
git -c safe.directory=/opt/camera fetch origin main
git -c safe.directory=/opt/camera reset --hard origin/main

ENV_FILE=/opt/camera/camera-api/.env
SCALE_FILE=/opt/camera/deploy/env.production.scale
touch "$ENV_FILE"

if [ ! -f "$SCALE_FILE" ]; then
  echo "ERROR: missing $SCALE_FILE"
  exit 1
fi

echo "=== Applying production scale env ==="
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    ""|\#*) continue ;;
  esac
  key="${line%%=*}"
  val="${line#*=}"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    echo "${key}=${val}" >> "$ENV_FILE"
  fi
  echo "  set ${key}=${val}"
done < "$SCALE_FILE"

echo "=== Compose overrides ==="
cp deploy/docker-compose.override.yml camera-api/docker-compose.override.yml
cp deploy/docker-compose.mediamtx-shard.yml camera-api/docker-compose.mediamtx-shard.yml
cp deploy/docker-compose.gpu.yml camera-api/docker-compose.gpu.yml

echo "=== Recreate API (pick up new env) ==="
cd camera-api
USE_GPU=0
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then USE_GPU=1; fi
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.mediamtx-shard.yml)
if [ "$USE_GPU" -eq 1 ]; then COMPOSE+=(-f docker-compose.gpu.yml); fi
docker stop camera-api-mediamtx-1 2>/dev/null || true
docker rm camera-api-mediamtx-1 2>/dev/null || true
"${COMPOSE[@]}" up -d --build api

echo "=== Health ==="
sleep 18
curl -sf http://127.0.0.1:18080/health; echo
"${COMPOSE[@]}" ps api
"""


def main() -> int:
    if not SCALE_FILE.is_file():
        print(f"ERROR: {SCALE_FILE} not found locally")
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    for host, port in HOSTS:
        try:
            print(f"Trying {host}:{port}...")
            client.connect(host, port=port, username=USER, password=PASSWORD, timeout=30)
            print(f"Connected to {host}:{port}")
            break
        except Exception as exc:
            print(f"Failed {host}:{port}: {exc}")
    else:
        print("ERROR: Could not connect to any server")
        return 1

    stdin, stdout, stderr = client.exec_command("bash -s", timeout=600)
    stdin.write(APPLY)
    stdin.channel.shutdown_write()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    print(out)
    if err.strip():
        print("STDERR:", err)
    client.close()
    print(f"apply_production_env finished with exit code {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
