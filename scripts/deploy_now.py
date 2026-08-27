"""Pull latest from GitHub and deploy on production server."""
import sys

import paramiko

HOSTS = [
    ("87.192.230.208", 2222),
    ("192.168.0.101", 22),
]
USER = "admin_root"
PASSWORD = "qazxsw123@!"

DEPLOY = """
set -e
cd /opt/camera
git -c safe.directory=/opt/camera fetch origin main
git -c safe.directory=/opt/camera reset --hard origin/main
echo "=== Git at: $(git -c safe.directory=/opt/camera rev-parse --short HEAD) ==="

ENV_FILE=/opt/camera/camera-api/.env
SCALE_FILE=/opt/camera/deploy/env.production.scale
touch "$ENV_FILE"
if [ -f "$SCALE_FILE" ]; then
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
  done < "$SCALE_FILE"
else
  echo "WARN: $SCALE_FILE missing — applying legacy env defaults"
  grep -q '^MEDIAMTX_HLS_INTERNAL_BASE_URL=' "$ENV_FILE" || echo 'MEDIAMTX_HLS_INTERNAL_BASE_URL=http://mediamtx:8888' >> "$ENV_FILE"
  grep -q '^UNIFIED_FACE_SWEEP_ENABLED=' "$ENV_FILE" || echo 'UNIFIED_FACE_SWEEP_ENABLED=true' >> "$ENV_FILE"
  grep -q '^EVENT_RETENTION_DAYS=' "$ENV_FILE" || echo 'EVENT_RETENTION_DAYS=180' >> "$ENV_FILE"
  grep -q '^REDIS_URL=' "$ENV_FILE" || echo 'REDIS_URL=redis://redis:6379/0' >> "$ENV_FILE"
fi

echo "=== Frontend build ==="
npm run build
rsync -a --delete dist/ /var/www/cam.fermi.uz/

echo "=== Compose overrides ==="
cp deploy/docker-compose.override.yml camera-api/docker-compose.override.yml
cp deploy/docker-compose.mediamtx-shard.yml camera-api/docker-compose.mediamtx-shard.yml
cp deploy/docker-compose.gpu.yml camera-api/docker-compose.gpu.yml

echo "=== Docker rebuild ==="
cd camera-api
USE_GPU=0
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then USE_GPU=1; fi
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.mediamtx-shard.yml)
if [ "$USE_GPU" -eq 1 ]; then COMPOSE+=(-f docker-compose.gpu.yml); echo "GPU build enabled"; fi
docker stop camera-api-mediamtx-1 2>/dev/null || true
docker rm camera-api-mediamtx-1 2>/dev/null || true
"${COMPOSE[@]}" up -d --build

echo "=== Alembic migrate ==="
sleep 12
"${COMPOSE[@]}" exec -T api alembic upgrade head

echo "=== Health ==="
sleep 5
curl -sf http://127.0.0.1:18080/health
echo
"${COMPOSE[@]}" ps

echo "=== Backup timer ==="
if [ -f /opt/camera/deploy/enable-backup-timer.sh ]; then
  bash /opt/camera/deploy/enable-backup-timer.sh || echo "WARN: backup timer setup skipped"
fi

echo "=== Pytest (changed modules) ==="
"${COMPOSE[@]}" exec -T api python -m pytest tests/test_p0_fixes.py tests/test_lesson_sessions.py -q --tb=line 2>&1 | tail -12 || echo "WARN: pytest skipped"
"""


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connected_host = None
    for host, port in HOSTS:
        try:
            print(f"Trying {host}:{port}...")
            client.connect(host, port=port, username=USER, password=PASSWORD, timeout=30)
            connected_host = f"{host}:{port}"
            print(f"Connected to {connected_host}")
            break
        except Exception as exc:
            print(f"Failed {host}:{port}: {exc}")
    else:
        print("ERROR: Could not connect to any server")
        return 1

    stdin, stdout, stderr = client.exec_command("bash -s", timeout=900)
    stdin.write(DEPLOY)
    stdin.channel.shutdown_write()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
    if err.strip():
        sys.stdout.buffer.write(b"\nSTDERR:\n")
        sys.stdout.buffer.write(err.encode("utf-8", errors="replace"))
    client.close()
    print(f"Deploy finished on {connected_host} with exit code {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
