#!/usr/bin/env bash
# Camera monitoring system — production deploy on Ubuntu/Debian
# Domains: cam.devflix.uz (frontend), camapi.devflix.uz (API)
# Also uses: storage.camapi.devflix.uz (MinIO), stream.cam.devflix.uz (HLS)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/camera}"
REPO_URL="${REPO_URL:-https://github.com/riskgroup77/camera.git}"
FRONTEND_DOMAIN="${FRONTEND_DOMAIN:-cam.devflix.uz}"
API_DOMAIN="${API_DOMAIN:-camapi.devflix.uz}"
STORAGE_DOMAIN="${STORAGE_DOMAIN:-storage.camapi.devflix.uz}"
STREAM_DOMAIN="${STREAM_DOMAIN:-stream.cam.devflix.uz}"
CERT_EMAIL="${CERT_EMAIL:-admin@${API_DOMAIN}}"

log() { echo "[deploy] $*"; }
die() { echo "[deploy] ERROR: $*" >&2; exit 1; }

require_root() {
  [[ "$(id -u)" -eq 0 ]] || die "Run as root: sudo bash deploy/server-setup.sh"
}

rand_hex() { openssl rand -hex 32; }
rand_b64() { openssl rand -base64 32 | tr -d '/+=' | head -c 43; }

install_packages() {
  log "Installing system packages..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq git curl ca-certificates nginx certbot python3-certbot-nginx \
    docker.io docker-compose-v2 2>/dev/null \
    || apt-get install -y -qq git curl ca-certificates nginx certbot python3-certbot-nginx docker.io docker-compose-plugin

  systemctl enable --now docker
  systemctl enable nginx
}

clone_or_update() {
  log "Cloning/updating repository in ${APP_DIR}..."
  if [[ -d "${APP_DIR}/.git" ]]; then
    git -C "${APP_DIR}" pull --ff-only
  else
    git clone "${REPO_URL}" "${APP_DIR}"
  fi
}

install_node() {
  if command -v node >/dev/null 2>&1 && [[ "$(node -p 'process.version.slice(1).split(".")[0]')" -ge 20 ]]; then
    log "Node.js already installed: $(node --version)"
    return
  fi
  log "Installing Node.js 22..."
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y -qq nodejs
}

generate_secrets() {
  SECRETS_FILE="${APP_DIR}/deploy/.secrets.env"
  if [[ -f "${SECRETS_FILE}" ]]; then
    log "Reusing existing secrets from ${SECRETS_FILE}"
    # shellcheck disable=SC1090
    source "${SECRETS_FILE}"
    return
  fi

  log "Generating production secrets..."
  DB_PASSWORD="$(rand_hex)"
  JWT_SECRET="$(rand_hex)"
  ENCRYPTION_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  S3_ACCESS_KEY="cam_minio_$(rand_b64 | tr '[:upper:]' '[:lower:]')"
  S3_SECRET_KEY="$(rand_hex)$(rand_hex)"

  # Production admin (in addition to seed users admin/operator)
  PROD_ADMIN_LOGIN="camadmin"
  PROD_ADMIN_PASSWORD="$(rand_b64)Aa1!"

  cat > "${SECRETS_FILE}" <<EOF
DB_PASSWORD=${DB_PASSWORD}
JWT_SECRET=${JWT_SECRET}
ENCRYPTION_KEY=${ENCRYPTION_KEY}
S3_ACCESS_KEY=${S3_ACCESS_KEY}
S3_SECRET_KEY=${S3_SECRET_KEY}
PROD_ADMIN_LOGIN=${PROD_ADMIN_LOGIN}
PROD_ADMIN_PASSWORD=${PROD_ADMIN_PASSWORD}
EOF
  chmod 600 "${SECRETS_FILE}"
  # shellcheck disable=SC1090
  source "${SECRETS_FILE}"
}

write_backend_env() {
  log "Writing camera-api/.env for Docker Compose..."
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

# Production tuning (adjust for GPU server)
AI_SWEEP_CAMERA_CONCURRENCY=8
FACE_RECOGNITION_GPU_ENABLED=false
FACE_RECOGNITION_INFERENCE_CONCURRENCY=2
EOF
  chmod 600 "${APP_DIR}/camera-api/.env"
}

write_frontend_env() {
  log "Writing frontend .env.production..."
  cat > "${APP_DIR}/.env.production" <<EOF
VITE_API_BASE_URL=https://${API_DOMAIN}
VITE_REALTIME_URL=wss://${API_DOMAIN}/ws/events
VITE_STREAM_GATEWAY_URL=https://${STREAM_DOMAIN}
EOF
}

start_backend() {
  log "Building and starting Docker Compose stack..."
  cd "${APP_DIR}/camera-api"
  docker compose down 2>/dev/null || true
  docker compose up -d --build
  log "Waiting for API health..."
  for i in $(seq 1 60); do
    if curl -sf "http://127.0.0.1:8080/health" >/dev/null 2>&1; then
      log "API is healthy"
      return
    fi
    sleep 5
  done
  log "API not healthy yet — check: docker compose -f ${APP_DIR}/camera-api logs api"
}

build_frontend() {
  log "Building frontend..."
  cd "${APP_DIR}"
  npm ci
  npm run build
  mkdir -p "/var/www/${FRONTEND_DOMAIN}"
  rm -rf "/var/www/${FRONTEND_DOMAIN:?}"/*
  cp -r dist/* "/var/www/${FRONTEND_DOMAIN}/"
  chown -R www-data:www-data "/var/www/${FRONTEND_DOMAIN}"
}

write_nginx() {
  log "Configuring nginx..."
  cp "${APP_DIR}/deploy/nginx/cam-frontend.conf" "/etc/nginx/sites-available/${FRONTEND_DOMAIN}.conf"
  cp "${APP_DIR}/deploy/nginx/cam-api.conf" "/etc/nginx/sites-available/${API_DOMAIN}.conf"
  cp "${APP_DIR}/deploy/nginx/cam-storage.conf" "/etc/nginx/sites-available/${STORAGE_DOMAIN}.conf"
  cp "${APP_DIR}/deploy/nginx/cam-stream.conf" "/etc/nginx/sites-available/${STREAM_DOMAIN}.conf"

  sed -i "s/__FRONTEND_DOMAIN__/${FRONTEND_DOMAIN}/g" "/etc/nginx/sites-available/${FRONTEND_DOMAIN}.conf"
  sed -i "s/__API_DOMAIN__/${API_DOMAIN}/g" "/etc/nginx/sites-available/${API_DOMAIN}.conf"
  sed -i "s/__STORAGE_DOMAIN__/${STORAGE_DOMAIN}/g" "/etc/nginx/sites-available/${STORAGE_DOMAIN}.conf"
  sed -i "s/__STREAM_DOMAIN__/${STREAM_DOMAIN}/g" "/etc/nginx/sites-available/${STREAM_DOMAIN}.conf"

  ln -sf "/etc/nginx/sites-available/${FRONTEND_DOMAIN}.conf" "/etc/nginx/sites-enabled/"
  ln -sf "/etc/nginx/sites-available/${API_DOMAIN}.conf" "/etc/nginx/sites-enabled/"
  ln -sf "/etc/nginx/sites-available/${STORAGE_DOMAIN}.conf" "/etc/nginx/sites-enabled/"
  ln -sf "/etc/nginx/sites-available/${STREAM_DOMAIN}.conf" "/etc/nginx/sites-enabled/"
  rm -f /etc/nginx/sites-enabled/default

  nginx -t
  systemctl reload nginx
}

issue_ssl() {
  log "Issuing Let's Encrypt certificates..."
  certbot --nginx -d "${FRONTEND_DOMAIN}" -d "${API_DOMAIN}" -d "${STORAGE_DOMAIN}" -d "${STREAM_DOMAIN}" \
    --non-interactive --agree-tos -m "${CERT_EMAIL}" --redirect || {
      log "Certbot failed — ensure DNS A records point to this server, then run:"
      log "  certbot --nginx -d ${FRONTEND_DOMAIN} -d ${API_DOMAIN} -d ${STORAGE_DOMAIN} -d ${STREAM_DOMAIN}"
    }
}

create_prod_admin() {
  log "Creating production admin user..."
  TOKEN=$(curl -sf -X POST "http://127.0.0.1:8080/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d '{"login":"admin","password":"admin123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])") || return 0

  curl -sf -X POST "http://127.0.0.1:8080/api/users" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H 'Content-Type: application/json' \
    -d "{\"login\":\"${PROD_ADMIN_LOGIN}\",\"password\":\"${PROD_ADMIN_PASSWORD}\",\"name\":\"Production Admin\",\"role\":\"Super Admin\"}" \
    >/dev/null 2>&1 || log "Production admin may already exist or seed not ready"
}

print_summary() {
  cat <<EOF

================================================================================
 DEPLOY COMPLETE
================================================================================
 Frontend:  https://${FRONTEND_DOMAIN}
 API:       https://${API_DOMAIN}
 Storage:   https://${STORAGE_DOMAIN}
 HLS:       https://${STREAM_DOMAIN}

 SEED USERS (from app/seed.py — created on first API boot):
   admin    / admin123      (super-admin — Jamshid Alimov)
   operator / operator123   (admin — Behzod Karimov)

 PRODUCTION ADMIN (strong password — saved in deploy/.secrets.env):
   ${PROD_ADMIN_LOGIN} / ${PROD_ADMIN_PASSWORD}

 Secrets file: ${APP_DIR}/deploy/.secrets.env  (chmod 600 — keep private)

 DNS required (A records -> this server IP):
   ${FRONTEND_DOMAIN}
   ${API_DOMAIN}
   ${STORAGE_DOMAIN}
   ${STREAM_DOMAIN}

 Useful commands:
   cd ${APP_DIR}/camera-api && docker compose logs -f api
   systemctl status nginx
   curl https://${API_DOMAIN}/health
================================================================================
EOF
}

main() {
  require_root
  install_packages
  clone_or_update
  install_node
  generate_secrets
  write_backend_env
  write_frontend_env
  start_backend
  build_frontend
  write_nginx
  issue_ssl
  create_prod_admin
  print_summary
}

main "$@"
