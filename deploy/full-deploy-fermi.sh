#!/usr/bin/env bash
# Full production deploy for cam.fermi.uz — run on server as root.
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/riskgroup77/camera/main/deploy/full-deploy-fermi.sh | sudo bash
# Or after clone:
#   sudo bash /opt/camera/deploy/full-deploy-fermi.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/camera}"
REPO_URL="${REPO_URL:-https://github.com/riskgroup77/camera.git}"
FRONTEND=cam.fermi.uz
API=camapi.fermi.uz
STORAGE=storage.camapi.fermi.uz
STREAM=stream.cam.fermi.uz

log() { echo "[full-deploy] $*"; }
die() { echo "[full-deploy] ERROR: $*" >&2; exit 1; }

[[ $(id -u) -eq 0 ]] || die "Run as root: sudo bash $0"

if [[ ! -d "$APP_DIR/.git" ]]; then
  log "Cloning repository to $APP_DIR..."
  apt-get update -qq && apt-get install -y -qq git curl docker.io docker-compose-plugin nginx certbot python3-certbot-nginx nodejs npm 2>/dev/null || true
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
git -c safe.directory="$APP_DIR" fetch origin main
git -c safe.directory="$APP_DIR" reset --hard origin/main

log "Running slim setup (env, secrets, docker, frontend)..."
bash deploy/server-setup-slim.sh

log "Docker compose overrides + MediaMTX..."
cp deploy/docker-compose.override.yml camera-api/docker-compose.override.yml
cp deploy/docker-compose.mediamtx.yml camera-api/docker-compose.mediamtx.yml
cp deploy/mediamtx.yml camera-api/mediamtx.yml 2>/dev/null || true
cd camera-api
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.mediamtx.yml up -d --build
cd "$APP_DIR"

log "Nginx (fermi, no duplicates)..."
bash deploy/nginx-cleanup-fermi.sh

log "Systemd services..."
cp deploy/camera-api.service /etc/systemd/system/
cp deploy/camera-ssl-wait.service /etc/systemd/system/
cp deploy/camera-ssl-wait.timer /etc/systemd/system/
cp deploy/camera-ssl-storage-stream.service /etc/systemd/system/
cp deploy/camera-ssl-storage-stream.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable camera-api.service
systemctl enable camera-ssl-storage-stream.timer
systemctl start camera-api.service 2>/dev/null || true
systemctl start camera-ssl-storage-stream.timer

log "SSL (if DNS ready)..."
bash deploy/wait-dns-storage-stream.sh 2>/dev/null || log "storage/stream DNS not ready — timer will retry"

log "Health checks..."
sleep 5
curl -sf "http://127.0.0.1:18080/health" || die "API health check failed"
curl -sfI -X OPTIONS "http://127.0.0.1:18080/api/auth/login" \
  -H "Origin: https://${FRONTEND}" \
  -H "Access-Control-Request-Method: POST" | grep -qi access-control-allow-origin || log "WARN: CORS header missing"

log "=== DEPLOY COMPLETE ==="
log "Frontend: https://${FRONTEND}"
log "API:      https://${API}/health"
log "Login:    admin / admin123  (see deploy/.secrets.env for camadmin)"
[[ -f deploy/.secrets.env ]] && log "Secrets:  ${APP_DIR}/deploy/.secrets.env"
