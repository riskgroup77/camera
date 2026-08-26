#!/usr/bin/env bash
# GPU + MediaMTX 3-shard setup on production server.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/camera}"
ENV_FILE="${APP_DIR}/camera-api/.env"
SCALE_FILE="${APP_DIR}/deploy/env.production.scale"

echo "=== Camera scale infra setup ==="
cd "$APP_DIR"
git -c safe.directory="$APP_DIR" fetch origin main
git -c safe.directory="$APP_DIR" reset --hard origin/main

echo "=== Merge production scale env ==="
touch "$ENV_FILE"
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

echo "=== Compose overrides ==="
cp deploy/docker-compose.override.yml camera-api/docker-compose.override.yml
cp deploy/docker-compose.mediamtx-shard.yml camera-api/docker-compose.mediamtx-shard.yml
cp deploy/docker-compose.gpu.yml camera-api/docker-compose.gpu.yml

USE_GPU=0
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  USE_GPU=1
  echo "=== NVIDIA GPU detected — using Dockerfile.gpu ==="
else
  echo "=== No GPU — CPU Docker image ==="
fi

if [ -d /etc/nginx/sites-available ] && sudo -n true 2>/dev/null; then
  sudo cp deploy/nginx/cam-fermi-stream.conf /etc/nginx/sites-available/stream.cam.fermi.uz.conf
  sudo ln -sf /etc/nginx/sites-available/stream.cam.fermi.uz.conf /etc/nginx/sites-enabled/stream.cam.fermi.uz.conf 2>/dev/null || true
  sudo nginx -t
  sudo systemctl reload nginx
  echo "=== Nginx reloaded ==="
else
  echo "WARN: skip nginx reload — copy deploy/nginx/cam-fermi-stream.conf manually if needed"
fi

echo "=== Stop legacy single mediamtx (if running) ==="
docker stop camera-api-mediamtx-1 2>/dev/null || true
docker rm camera-api-mediamtx-1 2>/dev/null || true

echo "=== Docker compose up ==="
cd camera-api
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.mediamtx-shard.yml)
if [ "$USE_GPU" -eq 1 ]; then
  COMPOSE+=(-f docker-compose.gpu.yml)
fi
"${COMPOSE[@]}" up -d --build

echo "=== Alembic + health ==="
sleep 15
"${COMPOSE[@]}" exec -T api alembic upgrade head 2>/dev/null || true
sleep 10
curl -sf http://127.0.0.1:18080/health
echo
"${COMPOSE[@]}" ps

echo "=== Backup timer ==="
if [ -f "${APP_DIR}/deploy/enable-backup-timer.sh" ]; then
  bash "${APP_DIR}/deploy/enable-backup-timer.sh" || echo "WARN: backup timer setup failed — run deploy/enable-backup-timer.sh manually"
fi

echo "=== Done ==="
