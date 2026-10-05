"""Restores objects from a local backup directory (produced by
backup_minio.py) back into the S3/MinIO bucket named by S3_BUCKET,
creating it first if it doesn't exist. Existing objects with the same key
are overwritten — safe to re-run.

Usage: python scripts/restore_minio.py
"""

import mimetypes
import os
from pathlib import Path

import boto3
from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    bucket = os.environ["S3_BUCKET"]
    src_root = Path(os.environ.get("BACKUP_DIR", "./backups/minio")) / bucket
    if not src_root.is_dir():
        raise SystemExit(f"Backup directory not found: {src_root}")

    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT_URL", "http://127.0.0.1:9000"),
        aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
        region_name=os.environ.get("S3_REGION", "us-east-1"),
    )

    existing = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
    if bucket not in existing:
        s3.create_bucket(Bucket=bucket)

    count = 0
    for path in src_root.rglob("*"):
        if not path.is_file():
            continue
        key = str(path.relative_to(src_root)).replace(os.sep, "/")
        content_type, _ = mimetypes.guess_type(path.name)
        s3.upload_file(str(path), bucket, key, ExtraArgs={"ContentType": content_type or "application/octet-stream"})
        count += 1

    print(f"Restored {count} object(s) to bucket '{bucket}'")


if __name__ == "__main__":
    main()
