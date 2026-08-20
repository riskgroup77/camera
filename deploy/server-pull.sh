#!/bin/bash
# Pull latest from GitHub and apply to production (fermi.uz)
set -euo pipefail

APP_DIR=/opt/camera
GIT="git -c safe.directory=${APP_DIR}"

cd "$APP_DIR"

echo "=== Git pull ==="
$GIT fetch origin main
$GIT reset --hard origin/main

echo "=== Frontend build ==="
npm run build
rsync -a --delete dist/ /var/www/cam.fermi.uz/

echo "=== Nginx configs (fermi, no duplicates) ==="
bash deploy/nginx-cleanup-fermi.sh

echo "=== Docker compose overrides ==="
cp deploy/docker-compose.override.yml camera-api/docker-compose.override.yml
cp deploy/docker-compose.mediamtx.yml camera-api/docker-compose.mediamtx.yml

echo "=== Docker stack (full recreate) ==="
cd camera-api
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.mediamtx.yml up -d --build

echo "=== Health check ==="
sleep 5
curl -sf http://127.0.0.1:18080/health | head -c 200
echo
curl -sfI -X OPTIONS http://127.0.0.1:18080/api/auth/login \
  -H 'Origin: https://cam.fermi.uz' \
  -H 'Access-Control-Request-Method: POST' | grep -i access-control-allow-origin || true

echo "=== Done ==="
