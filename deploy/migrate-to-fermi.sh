#!/usr/bin/env bash
# Migrate camera project from devflix.uz to fermi.uz domains
set -euo pipefail

APP_DIR=/opt/camera
FRONTEND=cam.fermi.uz
API=camapi.fermi.uz
STORAGE=storage.camapi.fermi.uz
STREAM=stream.cam.fermi.uz

source "$APP_DIR/deploy/.secrets.env"

echo "[migrate] Updating backend .env..."
cat > "$APP_DIR/camera-api/.env" <<EOF
DB_PASSWORD=${DB_PASSWORD}
JWT_SECRET=${JWT_SECRET}
ENCRYPTION_KEY=${ENCRYPTION_KEY}
CORS_ORIGIN=https://${FRONTEND}
FRONTEND_BASE_URL=https://${FRONTEND}
WEB_CONCURRENCY=2
S3_ACCESS_KEY=${S3_ACCESS_KEY}
S3_SECRET_KEY=${S3_SECRET_KEY}
S3_BUCKET=camera-uploads
S3_PUBLIC_ENDPOINT_URL=https://${STORAGE}
MEDIAMTX_HLS_BASE_URL=https://${STREAM}
AI_SWEEP_CAMERA_CONCURRENCY=8
FACE_RECOGNITION_GPU_ENABLED=false
FACE_RECOGNITION_INFERENCE_CONCURRENCY=2
EOF
chmod 600 "$APP_DIR/camera-api/.env"

echo "[migrate] Updating frontend .env.production..."
cat > "$APP_DIR/.env.production" <<EOF
VITE_API_BASE_URL=https://${API}
VITE_REALTIME_URL=wss://${API}/ws/events
VITE_STREAM_GATEWAY_URL=https://${STREAM}
EOF

echo "[migrate] Rebuilding frontend..."
cd "$APP_DIR"
npm run build

echo "[migrate] Deploying frontend..."
mkdir -p "/var/www/${FRONTEND}"
rm -rf "/var/www/${FRONTEND:?}"/*
cp -r dist/* "/var/www/${FRONTEND}/"
chown -R www-data:www-data "/var/www/${FRONTEND}"

echo "[migrate] Regenerating self-signed cert for fermi domains..."
openssl req -x509 -nodes -days 90 -newkey rsa:2048 \
  -keyout /etc/ssl/camera-devflix/privkey.pem \
  -out /etc/ssl/camera-devflix/fullchain.pem \
  -subj "/CN=${FRONTEND}" \
  -addext "subjectAltName=DNS:${FRONTEND},DNS:${API},DNS:${STORAGE},DNS:${STREAM}"

echo "[migrate] Configuring nginx (canonical *.fermi.uz.conf, no duplicates)..."
bash "$APP_DIR/deploy/nginx-cleanup-fermi.sh"

echo "[migrate] Enabling SSL wait timers..."
cp "$APP_DIR/deploy/camera-ssl-storage-stream.service" /etc/systemd/system/
cp "$APP_DIR/deploy/camera-ssl-storage-stream.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now camera-ssl-storage-stream.timer

echo "[migrate] Restarting API container..."
cd "$APP_DIR/camera-api"
docker compose -f docker-compose.yml -f docker-compose.mediamtx.yml restart api

echo "[migrate] Waiting for API..."
for i in $(seq 1 30); do
  curl -sf http://127.0.0.1:18080/health >/dev/null && break
  sleep 2
done

echo "[migrate] Requesting Let's Encrypt certificates..."
certbot --nginx \
  -d "$FRONTEND" -d "$API" -d "$STORAGE" -d "$STREAM" \
  --non-interactive --agree-tos -m "admin@${API}" --redirect \
  || echo "[migrate] Certbot: some domains may need DNS (storage/stream)"

curl -sf "https://${API}/health" -k || curl -sf http://127.0.0.1:18080/health
echo
echo "[migrate] DONE — https://${FRONTEND} https://${API}"
