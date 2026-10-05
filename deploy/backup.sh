#!/usr/bin/env bash
# Kunlik zaxira: baza (pg_dump -Fc), MinIO fayllari (haftada bir) va .env.
# Cron: 0 2 * * * /opt/camera/deploy/backup.sh >> /home/admin_root/camera-backups/backup.log 2>&1
#
# Server umumiy (23 ta loyiha): faqat shu loyihaning konteynerlariga tegadi,
# hech narsa prune qilinmaydi. Eski nusxalar RETENTION_DAYS dan keyin o'chadi.
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/camera/camera-api}
OUT_DIR=${OUT_DIR:-$HOME/camera-backups}
RETENTION_DAYS=${RETENTION_DAYS:-14}
WEB_ROOT=${WEB_ROOT:-/var/www/cam.fermi.uz}
MINIO_VOLUME=${MINIO_VOLUME:-camera-api_minio_data}
STAMP=$(date +%F-%H%M)

mkdir -p "$OUT_DIR"
cd "$APP_DIR"

# 1. Baza. Vaqtinchalik faylga yoziladi va faqat muvaffaqiyatli tugagach
#    yakuniy nomga o'tkaziladi — yarim yozilgan dump zaxira bo'lib qolmasin.
tmp="$OUT_DIR/.db-$STAMP.part"
if docker compose exec -T db sh -c 'pg_dump -U $POSTGRES_USER -Fc $POSTGRES_DB' > "$tmp"; then
    mv "$tmp" "$OUT_DIR/db-$STAMP.dump"
    echo "$(date -Is) baza: $(du -h "$OUT_DIR/db-$STAMP.dump" | cut -f1)"
else
    rm -f "$tmp"
    echo "$(date -Is) XATO: baza zaxirasi olinmadi" >&2
    exit 1
fi

# 2. .env (kamera parollari shifrlash kaliti shu yerda — usiz baza tiklansa
#    ham kameralarga ulanib bo'lmaydi).
if [ -r "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env" "$OUT_DIR/env-$STAMP.bak"
    chmod 600 "$OUT_DIR/env-$STAMP.bak"
fi

# 3. Yuzlar va hodisa rasmlari (MinIO) — haftada bir (yakshanba), hajmi katta.
if [ "$(date +%u)" = "7" ]; then
    # MinIO obrazida tar yo'q — arxivni api obrazi bilan olamiz (volume read-only).
    img=$(docker compose images -q api | head -1)
    docker run --rm -v "$MINIO_VOLUME":/data:ro --entrypoint tar "$img" -cz -C /data camera-uploads \
        > "$OUT_DIR/minio-$STAMP.tgz" \
        && echo "$(date -Is) minio: $(du -h "$OUT_DIR/minio-$STAMP.tgz" | cut -f1)"
    tar -czf "$OUT_DIR/www-$STAMP.tgz" -C "$WEB_ROOT" . 2>/dev/null || true
fi

# 4. Eskilarini tozalash.
find "$OUT_DIR" -maxdepth 1 -name 'db-*.dump' -mtime +"$RETENTION_DAYS" -delete
find "$OUT_DIR" -maxdepth 1 -name 'env-*.bak' -mtime +"$RETENTION_DAYS" -delete
find "$OUT_DIR" -maxdepth 1 -name 'minio-*.tgz' -mtime +60 -delete
find "$OUT_DIR" -maxdepth 1 -name 'www-*.tgz' -mtime +60 -delete
echo "$(date -Is) tayyor; jami: $(du -sh "$OUT_DIR" | cut -f1)"
