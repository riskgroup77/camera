"""One-off maintenance: delete objects in MinIO that no DB row references.

Why this exists: app/storage.py's delete_file() had no callers, so every
event purged by the retention job, every event deleted through the API,
and every replaced biometric photo left its object behind. That is now
fixed going forward (see app/storage.py's delete_files_quietly), but the
objects already orphaned before the fix are still there and nothing will
ever reclaim them.

Run it from inside the api container:

    # what WOULD be deleted (default — deletes nothing):
    docker compose ... exec api python scripts/purge_orphaned_snapshots.py

    # actually delete:
    docker compose ... exec api python scripts/purge_orphaned_snapshots.py --delete

Dry-run by default on purpose: this removes data permanently, and an
"orphan" here is decided by comparing against the live DB, so running it
against the wrong database would delete everything. Read the summary
first, then re-run with --delete.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Event, StudentStaff  # noqa: E402
from app.storage import _s3, delete_file  # noqa: E402

# Prefixes app/storage.py's upload_file() writes under.
MANAGED_PREFIXES = ("events/", "biometrics/")


def _list_all_objects() -> list[tuple[str, int]]:
    keys: list[tuple[str, int]] = []
    paginator = _s3.get_paginator("list_objects_v2")
    for prefix in MANAGED_PREFIXES:
        for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append((obj["Key"], obj.get("Size", 0)))
    return keys


async def _referenced_keys() -> set[str]:
    async with SessionLocal() as db:
        event_keys = (
            await db.execute(select(Event.snapshot_key).where(Event.snapshot_key.is_not(None)))
        ).scalars().all()
        photo_keys = (
            await db.execute(
                select(StudentStaff.biometric_photo_key).where(
                    StudentStaff.biometric_photo_key.is_not(None)
                )
            )
        ).scalars().all()
    return {k for k in list(event_keys) + list(photo_keys) if k}


def _human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delete",
        action="store_true",
        help="actually delete the orphans (without this the script only reports)",
    )
    args = parser.parse_args()

    print(f"Bucket: {settings.s3_bucket} @ {settings.s3_endpoint_url}")
    stored = await asyncio.to_thread(_list_all_objects)
    referenced = await _referenced_keys()

    orphans = [(key, size) for key, size in stored if key not in referenced]
    orphan_bytes = sum(size for _, size in orphans)

    print(f"  saqlangan obyektlar : {len(stored)}")
    print(f"  DB'da havola bor    : {len(referenced)}")
    print(f"  egasiz (orphan)     : {len(orphans)}  ({_human(orphan_bytes)})")

    if not orphans:
        print("\nTozalash shart emas.")
        return 0

    for key, size in orphans[:10]:
        print(f"    - {key}  ({_human(size)})")
    if len(orphans) > 10:
        print(f"    ... va yana {len(orphans) - 10} ta")

    if not args.delete:
        print("\nBu — QURUQ ISHLASH (dry run). Hech narsa o'chirilmadi.")
        print("Haqiqatan o'chirish uchun: --delete bayrog'i bilan qayta ishga tushiring.")
        return 0

    deleted = 0
    for key, _size in orphans:
        try:
            await asyncio.to_thread(delete_file, key)
            deleted += 1
        except Exception as exc:  # noqa: BLE001 - best effort, report and continue
            print(f"  XATO {key}: {exc}")
    print(f"\n{deleted} ta obyekt o'chirildi ({_human(orphan_bytes)} bo'shatildi).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
