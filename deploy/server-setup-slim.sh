#!/usr/bin/env bash
# Slim production deploy — skips apt (docker/nginx/node/certbot already on server)
set -euo pipefail

APP_DIR=/opt/camera
FRONTEND_DOMAIN=cam.fermi.uz
API_DOMAIN=camapi.fermi.uz
STORAGE_DOMAIN=storage.camapi.fermi.uz
STREAM_DOMAIN=stream.cam.fermi.uz
CERT_EMAIL=admin@fermi.uz

log() { echo "[deploy] $*"; }
rand_hex() { openssl rand -hex 32; }
rand_b64() { openssl rand -base64 32 | tr -d '/+=' | head -c 43; }

cd "$APP_DIR"

SECRETS_FILE="${APP_DIR}/deploy/.secrets.env"
if [[ ! -f "$SECRETS_FILE" ]]; then
  log "Generating secrets..."
  DB_PASSWORD="$(rand_hex)"
  JWT_SECRET="$(rand_hex)"
  ENCRYPTION_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' 2>/dev/null || openssl rand -base64 32)"
  S3_ACCESS_KEY="cam_minio_$(rand_b64 | tr '[:upper:]' '[:lower:]')"
  S3_SECRET_KEY="$(rand_hex)$(rand_hex)"
  PROD_ADMIN_LOGIN="camadmin"
  PROD_ADMIN_PASSWORD="$(rand_b64)Aa1!"
  cat > "$SECRETS_FILE" <<EOF
DB_PASSWORD=${DB_PASSWORD}
JWT_SECRET=${JWT_SECRET}
ENCRYPTION_KEY=${ENCRYPTION_KEY}
S3_ACCESS_KEY=${S3_ACCESS_KEY}
S3_SECRET_KEY=${S3_SECRET_KEY}
PROD_ADMIN_LOGIN=${PROD_ADMIN_LOGIN}
PROD_ADMIN_PASSWORD=${PROD_ADMIN_PASSWORD}
EOF
  chmod 600 "$SECRETS_FILE"
fi
# shellcheck disable=SC1090
source "$SECRETS_FILE"

log "Writing camera-api/.env..."
cat > "${APP_DIR}/camera-api/.env" <<EOF
DB_PASSWORD=${DB_PASSWORD}
JWT_SECRET=${JWT_SECRET}
ENCRYPTION_KEY=${ENCRYPTION_KEY}
CORS_ORIGIN=https://${FRONTEND_DOMAIN}
FRONTEND_BASE_URL=https://${FRONTEND_DOMAIN}
WEB_CONCURRENCY=2
S3_ACCESS_KEY=${S3_ACCESS_KEY}
S3_SECRET_KEY=${S3_SECRET_KEY}
S3_BUCKET=camera-uploads
S3_PUBLIC_ENDPOINT_URL=https://${STORAGE_DOMAIN}
MEDIAMTX_HLS_BASE_URL=https://${STREAM_DOMAIN}
AI_SWEEP_CAMERA_CONCURRENCY=8
FACE_RECOGNITION_GPU_ENABLED=false
FACE_RECOGNITION_INFERENCE_CONCURRENCY=2
EOF
chmod 600 "${APP_DIR}/camera-api/.env"

log "Writing frontend .env.production..."
cat > "${APP_DIR}/.env.production" <<EOF
VITE_API_BASE_URL=https://${API_DOMAIN}
VITE_REALTIME_URL=wss://${API_DOMAIN}/ws/events
VITE_STREAM_GATEWAY_URL=https://${STREAM_DOMAIN}
EOF

log "Starting Docker Compose..."
cd "${APP_DIR}/camera-api"
cp "${APP_DIR}/deploy/docker-compose.override.yml" docker-compose.override.yml
cp "${APP_DIR}/deploy/docker-compose.mediamtx.yml" docker-compose.mediamtx.yml
cp "${APP_DIR}/deploy/mediamtx.yml" mediamtx.yml 2>/dev/null || true
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.mediamtx.yml down 2>/dev/null || true
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.mediamtx.yml up -d --build

log "Waiting for API..."
for i in $(seq 1 90); do
  if curl -sf http://127.0.0.1:18080/health >/dev/null 2>&1; then
    log "API healthy"
    break
  fi
  sleep 5
done

log "Building frontend..."
cd "${APP_DIR}"
npm ci
npm run build
mkdir -p "/var/www/${FRONTEND_DOMAIN}"
rm -rf "/var/www/${FRONTEND_DOMAIN:?}"/*
cp -r dist/* "/var/www/${FRONTEND_DOMAIN}/"
chown -R www-data:www-data "/var/www/${FRONTEND_DOMAIN}"

log "Configuring nginx..."
bash "${APP_DIR}/deploy/nginx-cleanup-fermi.sh"

log "SSL certificates..."
certbot --nginx -d "${FRONTEND_DOMAIN}" -d "${API_DOMAIN}" -d "${STORAGE_DOMAIN}" -d "${STREAM_DOMAIN}" \
  --non-interactive --agree-tos -m "${CERT_EMAIL}" --redirect 2>/dev/null || log "Certbot skipped (check DNS)"

log "Creating production admin..."
TOKEN=$(curl -sf -X POST http://127.0.0.1:18080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"login":"admin","password":"admin123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])") || true
if [[ -n "${TOKEN:-}" ]]; then
  curl -sf -X POST http://127.0.0.1:18080/api/users \
    -H "Authorization: Bearer ${TOKEN}" \
    -H 'Content-Type: application/json' \
    -d "{\"login\":\"${PROD_ADMIN_LOGIN}\",\"password\":\"${PROD_ADMIN_PASSWORD}\",\"name\":\"Production Admin\",\"role\":\"Super Admin\"}" \
    >/dev/null 2>&1 || true
fi

log "DONE"
cat "$SECRETS_FILE"
curl -sf http://127.0.0.1:18080/health || true
