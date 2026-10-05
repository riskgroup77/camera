#!/usr/bin/env bash
# Enable daily Postgres + MinIO backup timer on the production host.
# Optional: SUDO_PASSWORD env for non-interactive deploy (never commit passwords).
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/camera}"
UNIT_DIR="/etc/systemd/system"

sudo_cmd() {
  if [ -n "${SUDO_PASSWORD:-}" ]; then
    echo "$SUDO_PASSWORD" | sudo -S "$@"
  else
    sudo "$@"
  fi
}

echo "=== Camera backup timer ==="
sudo_cmd cp "${APP_DIR}/deploy/camera-backup.service" "${UNIT_DIR}/camera-backup.service"
sudo_cmd cp "${APP_DIR}/deploy/camera-backup.timer" "${UNIT_DIR}/camera-backup.timer"
sudo_cmd mkdir -p /var/backups/camera-api
sudo_cmd systemctl daemon-reload
sudo_cmd systemctl enable camera-backup.timer
sudo_cmd systemctl start camera-backup.timer
systemctl status camera-backup.timer --no-pager || true
echo "=== Backup timer enabled (daily 02:00) ==="
