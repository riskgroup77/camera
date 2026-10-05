#!/usr/bin/env bash
# Runs Postgres + MinIO backups in sequence. Intended for cron/systemd timer.
#
# Usage (bare metal):
#   cd /opt/camera/camera-api
#   export DATABASE_URL=postgresql+asyncpg://...
#   export S3_BUCKET=camera-uploads
#   bash scripts/run_all_backups.sh
#
# Usage (Docker Compose on host):
#   bash scripts/backup_docker.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG_PREFIX="[camera-backup $(date -u +%Y-%m-%dT%H:%M:%SZ)]"
echo "$LOG_PREFIX starting Postgres backup ..."
bash scripts/backup_postgres.sh

echo "$LOG_PREFIX starting MinIO backup ..."
if [[ -x ./.venv/bin/python ]]; then
  ./.venv/bin/python scripts/backup_minio.py
elif command -v python3 >/dev/null 2>&1; then
  python3 scripts/backup_minio.py
else
  python scripts/backup_minio.py
fi

echo "$LOG_PREFIX all backups complete"
