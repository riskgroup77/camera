#!/usr/bin/env bash
set -euo pipefail
DOMAINS=(storage.camapi.fermi.uz stream.cam.fermi.uz)
NS=rdns1.ahost.uz
TARGET=87.192.230.208
EMAIL=admin@fermi.uz

all_ready() {
  for d in "${DOMAINS[@]}"; do
    ip=$(dig +short "$d" @"$NS" | tail -1)
    [[ "$ip" == "$TARGET" ]] || return 1
  done
}

if all_ready; then
  certbot --nginx -d storage.camapi.fermi.uz -d stream.cam.fermi.uz \
    --non-interactive --agree-tos -m "$EMAIL" --redirect
  systemctl disable camera-ssl-wait.timer 2>/dev/null || true
fi
