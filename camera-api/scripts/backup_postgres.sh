#!/usr/bin/env bash
# Dumps the Postgres database to a timestamped, compressed custom-format
# file and prunes backups older than BACKUP_RETENTION_DAYS.
#
# Requires pg_dump on PATH, matching (or newer than) the server's major
# version. In the docker-compose deployment (docker-compose.yml), run this
# via `docker compose exec db pg_dump ...` instead — the db container
# already ships a matching pg_dump — or install postgresql-client on
# whatever host/cron runner executes this script directly.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups/postgres}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="$BACKUP_DIR/camera_api_${TIMESTAMP}.dump"

: "${DATABASE_URL:?DATABASE_URL must be set (e.g. postgresql+asyncpg://user:pass@host:5432/camera_api)}"
# pg_dump doesn't understand the +asyncpg driver suffix SQLAlchemy uses.
PG_URL="${DATABASE_URL/postgresql+asyncpg:/postgresql:}"

mkdir -p "$BACKUP_DIR"

echo "Backing up to $OUT_FILE ..."
# --exclude-extension=pgcrypto: extensions are schema/infra, not data —
# they're expected to already exist on the restore target (created once,
# outside Alembic's migrations, by whoever provisions the database).
# Including it made pg_restore --clean emit `DROP EXTENSION pgcrypto`,
# which fails unless the restoring role happens to own the extension
# (discovered by actually running restore_postgres.sh against a real dump).
pg_dump --format=custom --no-owner --no-privileges --exclude-extension=pgcrypto \
  --dbname="$PG_URL" --file="$OUT_FILE"
echo "Backup complete: $(du -h "$OUT_FILE" | cut -f1)"

echo "Pruning backups older than $RETENTION_DAYS days ..."
find "$BACKUP_DIR" -name 'camera_api_*.dump' -mtime "+$RETENTION_DAYS" -print -delete
