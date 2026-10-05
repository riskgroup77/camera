#!/usr/bin/env bash
# Install SSL for storage/stream once DNS resolves on ahost.
set -euo pipefail

DOMAINS=(storage.camapi.fermi.uz stream.cam.fermi.uz)
NS=rdns1.ahost.uz
TARGET=87.192.230.208
EMAIL=admin@fermi.uz
LOG=/var/log/camera-ssl-storage-stream.log

log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }

all_ready() {
  for d in "${DOMAINS[@]}"; do
    ip=$(dig +short "$d" @"$NS" | tail -1)
    [[ "$ip" == "$TARGET" ]] || return 1
  done
}

if ! all_ready; then
  log "DNS not ready:"
  for d in "${DOMAINS[@]}"; do
    log "  $d => $(dig +short "$d" @"$NS" | tail -1 || echo NXDOMAIN)"
  done
  exit 1
fi

log "DNS ready — requesting Let's Encrypt for storage/stream"
certbot --nginx \
  -d storage.camapi.fermi.uz \
  -d stream.cam.fermi.uz \
  --non-interactive --agree-tos -m "$EMAIL" --redirect

log "SSL installed for storage/stream"
systemctl disable camera-ssl-storage-stream.timer 2>/dev/null || true
