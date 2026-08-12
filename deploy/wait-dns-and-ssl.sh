#!/usr/bin/env bash
# Polls DNS on ahost authoritative NS; runs certbot when all cam domains resolve.
set -euo pipefail

DOMAINS=(cam.devflix.uz camapi.devflix.uz storage.camapi.devflix.uz stream.cam.devflix.uz)
NS=rdns1.ahost.uz
TARGET=87.192.230.208
EMAIL=admin@camapi.devflix.uz
LOG=/var/log/camera-ssl-wait.log

log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }

all_ready() {
  for d in "${DOMAINS[@]}"; do
    ip=$(dig +short "$d" @"$NS" | tail -1)
    if [[ "$ip" != "$TARGET" ]]; then
      return 1
    fi
  done
  return 0
}

if all_ready; then
  log "DNS ready — requesting Let's Encrypt certificate"
  certbot --nginx \
    -d cam.devflix.uz \
    -d camapi.devflix.uz \
    -d storage.camapi.devflix.uz \
    -d stream.cam.devflix.uz \
    --non-interactive --agree-tos -m "$EMAIL" --redirect
  log "SSL installed successfully"
  systemctl disable camera-ssl-wait.timer 2>/dev/null || true
  exit 0
fi

log "DNS not ready yet:"
for d in "${DOMAINS[@]}"; do
  log "  $d => $(dig +short "$d" @"$NS" | tail -1 || echo NXDOMAIN)"
done
exit 1
