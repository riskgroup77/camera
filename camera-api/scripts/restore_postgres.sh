#!/usr/bin/env bash
# Restores a Postgres database from a pg_dump custom-format backup file
# produced by backup_postgres.sh.
#
# DESTRUCTIVE: drops and recreates every object in the target database
# before restoring (--clean --if-exists). Confirm before running against
# anything but a throwaway/test database — this is exactly why it prompts
# instead of running silently.
set -euo pipefail

BACKUP_FILE="${1:?Usage: restore_postgres.sh <backup-file> [target-database-url]}"
TARGET_URL="${2:-${DATABASE_URL:?DATABASE_URL must be set or passed as the 2nd argument}}"
PG_URL="${TARGET_URL/postgresql+asyncpg:/postgresql:}"

if [ ! -f "$BACKUP_FILE" ]; then
  echo "Backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

echo "This will DROP and recreate every object in the target database:"
echo "  $PG_URL"
read -r -p "Type 'yes' to continue: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "Aborted."
  exit 1
fi

pg_restore --clean --if-exists --no-owner --no-privileges --dbname="$PG_URL" "$BACKUP_FILE"
echo "Restore complete."
