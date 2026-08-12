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

echo "=== Nginx configs (fermi) ==="
for f in cam-fermi-frontend cam-fermi-api cam-fermi-storage cam-fermi-stream; do
  if [[ -f "deploy/nginx/${f}.conf" ]]; then
    cp "deploy/nginx/${f}.conf" "/etc/nginx/sites-available/${f}.conf"
    ln -sf "/etc/nginx/sites-available/${f}.conf" "/etc/nginx/sites-enabled/${f}.conf"
  fi
done
nginx -t && systemctl reload nginx

echo "=== Docker API (reload env if .env changed) ==="
cd camera-api
docker compose up -d --force-recreate api

echo "=== Health check ==="
sleep 5
curl -sf http://127.0.0.1:18080/health | head -c 200
echo
curl -sfI -X OPTIONS http://127.0.0.1:18080/api/auth/login \
  -H 'Origin: https://cam.fermi.uz' \
  -H 'Access-Control-Request-Method: POST' | grep -i access-control-allow-origin || true

echo "=== Done ==="
