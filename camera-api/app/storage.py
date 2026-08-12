"""S3-compatible object storage (MinIO locally, real S3/MinIO cluster in
production — the boto3 client code is identical either way, only
S3_ENDPOINT_URL changes). Replaces the frontend's fileUpload.ts, which
only ever created a temporary browser object URL — nothing was actually
persisted anywhere."""

import uuid

import boto3

from app.config import settings

_s3 = boto3.client(
    "s3",
    endpoint_url=settings.s3_endpoint_url,
    aws_access_key_id=settings.s3_access_key,
    aws_secret_access_key=settings.s3_secret_key,
    region_name=settings.s3_region,
)

# Separate client used ONLY for signing presigned URLs. In Docker Compose
# s3_endpoint_url is the internal "http://minio:9000" the api container
# uses to actually talk to MinIO, but a presigned URL is handed to the
# BROWSER — which can't resolve that Docker-internal hostname. Signing
# against s3_public_endpoint_url instead (e.g. "http://localhost:9000")
# produces a URL the browser can actually reach. No network call happens
# at client-construction time, so this costs nothing when the two
# endpoints are the same (plain local dev, no containers).
_s3_public = (
    _s3
    if settings.s3_public_endpoint_url is None
    else boto3.client(
        "s3",
        endpoint_url=settings.s3_public_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )
)

PRESIGNED_URL_TTL_SECONDS = 3600


def upload_file(data: bytes, filename: str, content_type: str, prefix: str) -> tuple[str, str]:
    """Stores the file under `<prefix>/<id>-<filename>` and returns
    (id, key) — the id is the stable handle callers keep (e.g. to later
    delete the object); the key is the internal S3 path derived from it."""
    file_id = str(uuid.uuid4())
    key = f"{prefix}/{file_id}-{filename}"
    _s3.put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type)
    return file_id, key


def check_bucket() -> None:
    """Raises if MinIO/S3 is unreachable or the configured bucket doesn't
    exist — used by GET /health so a broken storage backend shows up as
    "degraded" instead of surfacing only when someone happens to hit
    /api/uploads or biometric enrollment."""
    _s3.head_bucket(Bucket=settings.s3_bucket)


def presigned_url(key: str) -> str:
    return _s3_public.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=PRESIGNED_URL_TTL_SECONDS,
    )


def delete_file(key: str) -> None:
    _s3.delete_object(Bucket=settings.s3_bucket, Key=key)
