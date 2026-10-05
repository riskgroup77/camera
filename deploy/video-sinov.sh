#!/bin/bash
# Kunlik video tahlilni yozib olingan videolarda SINASH — production'ga tegmasdan.
#
#   bash /opt/camera-sinov/deploy/video-sinov.sh tayyorla      # kod, nusxa baza, bucket
#   bash /opt/camera-sinov/deploy/video-sinov.sh cli <buyruq>   # scripts/video_tahlil.py
#   bash /opt/camera-sinov/deploy/video-sinov.sh tozala         # hammasini o'chirish
#
# Nima o'zgarmaydi: /opt/camera (production kodi), camera_api bazasi (faqat
# o'qiladi — nusxa olish uchun), ishlab turgan konteynerlar, Redis, asosiy
# MinIO bucket, yozuvlar (/opt/camera/recordings — faqat o'qiladi).
#
# Nima yaratiladi:
#   * /opt/camera-sinov          — kunlik-video-tahlil branchi (git clone);
#   * camera_api_sinov bazasi    — production bazasining nusxasi (o'sha
#                                  PostgreSQL konteynerida), migratsiyalar
#                                  faqat shunga qo'llanadi;
#   * camera-sinov bucket        — dalil rasmlari (xalat, chekish);
#   * vaqtinchalik konteyner     — jonli ai-worker rasmi + branch kodi ustidan.
#
# Himoya: sinov konteynerida Telegram, SMS, e-pochta kalitlari BO'SH (ota-
# onalarga "kelmadi" xabari ketmaydi), Redis yo'q (hodisalar jonli panelga
# chiqmaydi), protsessor SINOV_CPUS bilan cheklangan.
set -euo pipefail

REPO_URL=${REPO_URL:-https://github.com/riskgroup77/camera.git}
BRANCH=${BRANCH:-kunlik-video-tahlil}
SINOV_DIR=${SINOV_DIR:-/opt/camera-sinov}
SOURCE_CONTAINER=${SOURCE_CONTAINER:-camera-api-ai-worker-1}
RECORDINGS=${RECORDINGS:-/opt/camera/recordings}
DB_CONTAINER=${DB_CONTAINER:-camera-api-db-1}
NETWORK=${NETWORK:-camera-api_default}
IMAGE=${IMAGE:-camera-api-ai-worker:latest}
MODELS_VOLUME=${MODELS_VOLUME:-camera-api_insightface_models}
SINOV_DB=${SINOV_DB:-camera_api_sinov}
SINOV_BUCKET=${SINOV_BUCKET:-camera-sinov}
SINOV_CPUS=${SINOV_CPUS:-12}

# Sozlamalar ishlab turgan ai-worker'dan (aynan u ishlatayotgan qiymatlar;
# .env ni docker --env-file boshqacha o'qiydi — qo'shtirnoqlar). Vaqtinchalik
# fayl faqat egasi o'qiy oladi va chiqishda o'chiriladi; ekranga chiqmaydi.
ENV_TMP=$(mktemp)
chmod 600 "$ENV_TMP"
trap 'rm -f "$ENV_TMP"' EXIT
docker inspect "$SOURCE_CONTAINER" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -v '^$' > "$ENV_TMP"
PROD_DB_URL=$(grep '^DATABASE_URL=' "$ENV_TMP" | tail -1 | cut -d= -f2-)
[ -n "$PROD_DB_URL" ] || { echo "XATO: $SOURCE_CONTAINER da DATABASE_URL yo'q"; exit 1; }
SINOV_DB_URL="${PROD_DB_URL%/*}/$SINOV_DB"
# Eng muhim himoya: sinov hech qachon production bazasiga ulanmasin.
[ "$SINOV_DB_URL" != "$PROD_DB_URL" ] && [ "${SINOV_DB_URL##*/}" = "$SINOV_DB" ] \
  || { echo "XATO: sinov bazasi manzili production bilan bir xil chiqdi"; exit 1; }

db_psql() {
  docker exec "$DB_CONTAINER" sh -c "psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d postgres -tAc \"$1\""
}

run_sinov() {
  mkdir -p "$SINOV_DIR/nvr-eksport" "$SINOV_DIR/natijalar"
  # Konteyner appuser bilan ishlaydi — havolalar va hisobot shu yerga yoziladi.
  chmod 0777 "$SINOV_DIR/nvr-eksport" "$SINOV_DIR/natijalar"
  docker run --rm -i \
    --name "camera-sinov-$$" \
    --network "$NETWORK" \
    --cpus "$SINOV_CPUS" \
    --env-file "$ENV_TMP" \
    -e DATABASE_URL="$SINOV_DB_URL" \
    -e S3_BUCKET="$SINOV_BUCKET" \
    -e REDIS_URL= \
    -e TELEGRAM_BOT_TOKEN= -e TELEGRAM_POLLING_ENABLED=false \
    -e SMS_PROVIDER=none -e ESKIZ_EMAIL= -e ESKIZ_PASSWORD= \
    -e SMTP_HOST= -e SMTP_PASSWORD= \
    -e PARENT_NOTIFY_ARRIVAL_ENABLED=false -e PARENT_NOTIFY_ABSENCE_ENABLED=false \
    -e AI_ROLE=api \
    -e VIDEO_IMPORT_DIR=/data/nvr-eksport \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$SINOV_DIR/camera-api/app:/app/app:ro" \
    -v "$SINOV_DIR/camera-api/scripts:/app/scripts:ro" \
    -v "$SINOV_DIR/camera-api/alembic:/app/alembic:ro" \
    -v "$SINOV_DIR/camera-api/alembic.ini:/app/alembic.ini:ro" \
    -v "$RECORDINGS:/data/recordings:ro" \
    -v "$SINOV_DIR/nvr-eksport:/data/nvr-eksport" \
    -v "$SINOV_DIR/natijalar:/data/natijalar" \
    -v "$MODELS_VOLUME:/home/appuser/.insightface" \
    -w /app \
    "$IMAGE" "$@"
}

cmd_tayyorla() {
  echo "== 1. Kod: $REPO_URL ($BRANCH) -> $SINOV_DIR"
  if [ -d "$SINOV_DIR/.git" ]; then
    git -C "$SINOV_DIR" fetch -q origin "$BRANCH"
    git -C "$SINOV_DIR" checkout -q -B "$BRANCH" "origin/$BRANCH"
  else
    git clone -q --branch "$BRANCH" "$REPO_URL" "$SINOV_DIR"
  fi
  git -C "$SINOV_DIR" log --oneline -1

  echo "== 2. Baza nusxasi: camera_api -> $SINOV_DB"
  if [ "$(db_psql "SELECT 1 FROM pg_database WHERE datname='$SINOV_DB'")" = "1" ]; then
    echo "   $SINOV_DB allaqachon bor — qayta nusxalash uchun avval: $0 tozala"
  else
    db_psql "CREATE DATABASE $SINOV_DB"
    docker exec "$DB_CONTAINER" sh -c \
      "pg_dump -U \"\$POSTGRES_USER\" -Fc \"\$POSTGRES_DB\" | pg_restore -U \"\$POSTGRES_USER\" -d $SINOV_DB --no-owner --exit-on-error"
    echo "   nusxa tayyor: $(db_psql "SELECT pg_size_pretty(pg_database_size('$SINOV_DB'))")"
  fi

  echo "== 3. Migratsiyalar (faqat $SINOV_DB)"
  run_sinov alembic upgrade head

  echo "== 4. Dalil rasmlari uchun bucket: $SINOV_BUCKET"
  run_sinov python - <<'PY'
import boto3
from botocore.exceptions import ClientError
from app.config import settings

s3 = boto3.client("s3", endpoint_url=settings.s3_endpoint_url,
                  aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key)
try:
    s3.head_bucket(Bucket=settings.s3_bucket)
    print("   bucket bor")
except ClientError:
    s3.create_bucket(Bucket=settings.s3_bucket)
    print("   bucket yaratildi")
PY
  echo "Tayyor. Keyingi qadam: $0 cli papka /data/recordings/<papka>"
}

cmd_tozala() {
  echo "== Sinov bazasi, havolalar va bucket o'chiriladi (production'ga tegilmaydi)"
  if [ "$(db_psql "SELECT 1 FROM pg_database WHERE datname='$SINOV_DB'")" = "1" ]; then
    run_sinov python - <<'PY' || true
import boto3
from app.config import settings

s3 = boto3.resource("s3", endpoint_url=settings.s3_endpoint_url,
                    aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key)
bucket = s3.Bucket(settings.s3_bucket)
bucket.objects.all().delete()
bucket.delete()
print("   bucket o'chirildi")
PY
    db_psql "DROP DATABASE $SINOV_DB WITH (FORCE)"
    echo "   $SINOV_DB o'chirildi"
  fi
  rm -rf "$SINOV_DIR/nvr-eksport"
  echo "Kod ($SINOV_DIR) va natijalar ($SINOV_DIR/natijalar) qoldirildi — kerak bo'lmasa: rm -rf $SINOV_DIR"
}

case "${1:-}" in
  tayyorla) cmd_tayyorla ;;
  cli) shift; run_sinov python scripts/video_tahlil.py "$@" ;;
  shell) shift; run_sinov "${@:-bash}" ;;
  tozala) cmd_tozala ;;
  *)
    sed -n '2,8p' "$0"
    exit 1
    ;;
esac
