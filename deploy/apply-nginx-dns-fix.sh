#!/usr/bin/env bash
set -euo pipefail
cd /opt/camera
git -c safe.directory=/opt/camera pull origin main
bash deploy/nginx-cleanup-fermi.sh
cp deploy/camera-ssl-storage-stream.service /etc/systemd/system/
cp deploy/camera-ssl-storage-stream.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now camera-ssl-storage-stream.timer
echo "=== DNS status (ahost) ==="
for d in storage.camapi.fermi.uz stream.cam.fermi.uz; do
  echo -n "$d => "
  dig +short "$d" @rdns1.ahost.uz || true
done
echo "=== nginx duplicate check ==="
nginx -t 2>&1 | grep -i conflicting || echo "No conflicting server_name warnings for cam domains"
bash deploy/wait-dns-storage-stream.sh || true
