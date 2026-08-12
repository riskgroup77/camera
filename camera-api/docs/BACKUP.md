# Backup strategy

Two independent stores need backing up: Postgres (all structured data —
users, students/staff, events, attendance, reports, audit log, ...) and
MinIO/S3 (uploaded files — passport scans, biometric enrollment photos).
MediaMTX and the cleanup job (`app/jobs/cleanup.py`) hold no state of
their own and need no backup.

Both backup scripts and their restore counterparts live in `scripts/` and
have been run end-to-end against a real Postgres + MinIO instance while
writing this (a genuine dump → restore → verify cycle, not just written
and assumed to work) — see the fix below for a bug that surfaced doing
exactly that.

## Postgres

`scripts/backup_postgres.sh` — `pg_dump --format=custom` to a timestamped
file, then prunes anything older than `BACKUP_RETENTION_DAYS` (default 14
days).

```bash
export DATABASE_URL=postgresql+asyncpg://camera_api:...@host:5432/camera_api
export BACKUP_DIR=/var/backups/camera-api/postgres   # optional, defaults to ./backups/postgres
export BACKUP_RETENTION_DAYS=14                       # optional
bash scripts/backup_postgres.sh
```

Requires `pg_dump` on PATH, matching (or newer than) the server's major
version. In the docker-compose deployment, either install
`postgresql-client` wherever cron runs, or run it via the `db` container
itself, which already has a matching `pg_dump`:

```bash
docker compose exec -T db pg_dump --format=custom --no-owner --no-privileges \
  --exclude-extension=pgcrypto -U camera_api camera_api > backup.dump
```

**Restore** — `scripts/restore_postgres.sh <backup-file> [target-database-url]`.
Destructive (`pg_restore --clean --if-exists`): drops and recreates every
object in the target database before restoring. Prompts for confirmation.

```bash
bash scripts/restore_postgres.sh backups/postgres/camera_api_20260101T000000Z.dump
```

**Why `--exclude-extension=pgcrypto` on the dump side:** the schema uses
`gen_random_uuid()` from the `pgcrypto` extension, which by default lands
in the dump too. Restoring that dump with `--clean` then tries to `DROP
EXTENSION pgcrypto` — which fails unless the restoring role happens to
own the extension (it usually doesn't; extensions are typically created
once by a superuser during provisioning). Extensions are infrastructure,
not data — the restore target is expected to already have them, the same
way it's expected to already have `alembic upgrade head` applied before
data gets restored on top.

## MinIO / S3

`scripts/backup_minio.py` — downloads every object in `S3_BUCKET` to
`BACKUP_DIR/<bucket>/`, preserving object keys as the relative path.

```bash
export S3_ENDPOINT_URL=http://127.0.0.1:9000
export S3_ACCESS_KEY=...
export S3_SECRET_KEY=...
export S3_BUCKET=camera-uploads
export BACKUP_DIR=/var/backups/camera-api/minio   # optional
python scripts/backup_minio.py
```

**Restore** — `scripts/restore_minio.py` re-uploads everything from
`BACKUP_DIR/<bucket>/` back into `S3_BUCKET`, creating the bucket first if
it doesn't exist. Overwrites existing keys — safe to re-run.

```bash
python scripts/restore_minio.py
```

Both scripts use the same `S3_*` env vars as `app/storage.py` (loaded via
`.env` if present) — no separate credentials to manage.

## Scheduling

Neither script schedules itself — wire either into your platform's own
scheduler. A daily cron entry, run from wherever the scripts + `pg_dump` +
python venv are available:

```cron
# Daily at 02:00, keep 14 days of Postgres dumps, mirror MinIO in full each time
0 2 * * * cd /opt/camera-api && DATABASE_URL=... BACKUP_DIR=/var/backups/camera-api/postgres bash scripts/backup_postgres.sh >> /var/log/camera-api-backup.log 2>&1
5 2 * * * cd /opt/camera-api && S3_BUCKET=camera-uploads BACKUP_DIR=/var/backups/camera-api/minio ./.venv/bin/python scripts/backup_minio.py >> /var/log/camera-api-backup.log 2>&1
```

`BACKUP_DIR` should point somewhere that itself gets backed up off-host
(the whole point is surviving loss of the machine these run on) — a
mounted network volume, or synced to a separate object store/bucket.

## What's NOT covered

- **MediaMTX**: stateless — its only "state" is camera path registrations,
  which `app/routers/cameras.py` re-registers from the database on every
  camera update; nothing to back up.
- **App code / Docker images**: covered by git + your image registry, not
  this doc.
- **Encryption key / JWT secret** (`ENCRYPTION_KEY`, `JWT_SECRET` in
  `.env`): losing `ENCRYPTION_KEY` makes stored camera RTSP credentials
  (`app/crypto.py`) permanently undecryptable even with a perfect Postgres
  restore — back up `.env`'s secrets separately, through whatever secret
  manager you use, not alongside the application data dumps above.
