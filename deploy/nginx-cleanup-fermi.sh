#!/usr/bin/env bash
# Remove duplicate cam-fermi-* nginx sites; keep canonical *.fermi.uz.conf files.
set -euo pipefail

APP_DIR=/opt/camera
ENABLED=/etc/nginx/sites-enabled
AVAILABLE=/etc/nginx/sites-available

echo "[nginx-cleanup] Removing duplicate cam-fermi-* symlinks..."
for dup in cam-fermi-frontend cam-fermi-api cam-fermi-storage cam-fermi-stream; do
  rm -f "${ENABLED}/${dup}.conf"
done

echo "[nginx-cleanup] Ensuring canonical fermi configs are installed..."
install -m 644 "${APP_DIR}/deploy/nginx/cam-fermi-frontend.conf" "${AVAILABLE}/cam.fermi.uz.conf"
install -m 644 "${APP_DIR}/deploy/nginx/cam-fermi-api.conf" "${AVAILABLE}/camapi.fermi.uz.conf"
install -m 644 "${APP_DIR}/deploy/nginx/cam-fermi-storage.conf" "${AVAILABLE}/storage.camapi.fermi.uz.conf"
install -m 644 "${APP_DIR}/deploy/nginx/cam-fermi-stream.conf" "${AVAILABLE}/stream.cam.fermi.uz.conf"

for site in cam.fermi.uz.conf camapi.fermi.uz.conf storage.camapi.fermi.uz.conf stream.cam.fermi.uz.conf; do
  ln -sf "${AVAILABLE}/${site}" "${ENABLED}/${site}"
done

# Preserve Let's Encrypt paths if certbot already configured main domains.
if [[ -f /etc/letsencrypt/live/cam.fermi.uz/fullchain.pem ]]; then
  for site in cam.fermi.uz.conf camapi.fermi.uz.conf; do
    sed -i 's|/etc/ssl/camera-devflix/fullchain.pem|/etc/letsencrypt/live/cam.fermi.uz/fullchain.pem|g' "${AVAILABLE}/${site}"
    sed -i 's|/etc/ssl/camera-devflix/privkey.pem|/etc/letsencrypt/live/cam.fermi.uz/privkey.pem|g' "${AVAILABLE}/${site}"
  done
fi

nginx -t
systemctl reload nginx
echo "[nginx-cleanup] Done — no duplicate server_name blocks."
