#!/usr/bin/env bash
# Quick fix when API returns 502 — run on server console as root.
set -euo pipefail
APP_DIR=/opt/camera
cd "$APP_DIR"
git -c safe.directory="$APP_DIR" pull origin main || true
cp deploy/docker-compose.override.yml camera-api/docker-compose.override.yml
cp deploy/docker-compose.mediamtx.yml camera-api/docker-compose.mediamtx.yml
cd camera-api
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.mediamtx.yml up -d --build
sleep 10
curl -sf http://127.0.0.1:18080/health && echo
cd "$APP_DIR"
bash deploy/nginx-cleanup-fermi.sh
echo "Done. Test: curl https://camapi.fermi.uz/health"
