#!/usr/bin/env bash
# Polls DNS on ahost authoritative NS; runs certbot when all cam fermi domains resolve.
set -euo pipefail

DOMAINS=(cam.fermi.uz camapi.fermi.uz)
NS=rdns1.ahost.uz
TARGET=87.192.230.208
EMAIL=admin@fermi.uz
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
  log "DNS ready — requesting Let's Encrypt certificate for cam + camapi"
  certbot --nginx \
    -d cam.fermi.uz \
    -d camapi.fermi.uz \
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
