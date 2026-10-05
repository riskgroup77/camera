"""Backs up every object in the S3/MinIO bucket to a local directory,
preserving object keys as the relative path. Uses the same connection
settings as app/storage.py (S3_* env vars, loaded from .env if present).
The mirror-image operation is restore_minio.py.

Usage: python scripts/backup_minio.py
"""

import os
from pathlib import Path

import boto3
from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    bucket = os.environ["S3_BUCKET"]
    dest_root = Path(os.environ.get("BACKUP_DIR", "./backups/minio")) / bucket
    dest_root.mkdir(parents=True, exist_ok=True)

    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT_URL", "http://127.0.0.1:9000"),
        aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
        region_name=os.environ.get("S3_REGION", "us-east-1"),
    )

    paginator = s3.get_paginator("list_objects_v2")
    count = 0
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            dest = dest_root / key
            dest.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(dest))
            count += 1

    print(f"Backed up {count} object(s) from bucket '{bucket}' to {dest_root}")


if __name__ == "__main__":
    main()
