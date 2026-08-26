#!/usr/bin/env bash
# Docker Compose backup runner — uses pg_dump inside the db container and
# runs MinIO backup from the api container (boto3 + env already configured).
#
# Usage:
#   cd /opt/camera/camera-api
#   export BACKUP_DIR=/var/backups/camera-api
#   bash scripts/backup_docker.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PG_DIR="$BACKUP_DIR/postgres"
OUT_FILE="$PG_DIR/camera_api_${TIMESTAMP}.dump"

mkdir -p "$PG_DIR"

echo "[camera-backup] Postgres via docker compose exec db ..."
docker compose exec -T db pg_dump \
  --format=custom --no-owner --no-privileges --exclude-extension=pgcrypto \
  -U camera_api camera_api > "$OUT_FILE"
echo "[camera-backup] Postgres saved: $(du -h "$OUT_FILE" | cut -f1)"

find "$PG_DIR" -name 'camera_api_*.dump' -mtime "+$RETENTION_DAYS" -print -delete

echo "[camera-backup] MinIO via docker compose exec api ..."
docker compose exec -T -e "BACKUP_DIR=$BACKUP_DIR/minio" api python scripts/backup_minio.py
echo "[camera-backup] done"
