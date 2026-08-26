#!/usr/bin/env bash
# Enable daily Postgres + MinIO backup timer on the production host.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/camera}"
UNIT_DIR="/etc/systemd/system"

echo "=== Camera backup timer ==="
sudo cp "${APP_DIR}/deploy/camera-backup.service" "${UNIT_DIR}/camera-backup.service"
sudo cp "${APP_DIR}/deploy/camera-backup.timer" "${UNIT_DIR}/camera-backup.timer"
sudo mkdir -p /var/backups/camera-api
sudo systemctl daemon-reload
sudo systemctl enable camera-backup.timer
sudo systemctl start camera-backup.timer
systemctl status camera-backup.timer --no-pager || true
echo "=== Backup timer enabled (daily 02:00) ==="
