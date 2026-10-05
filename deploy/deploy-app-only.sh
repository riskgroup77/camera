#!/usr/bin/env bash
# Faqat ilova konteynerlarini (api, ai-worker) yangilaydi.
#
# Baza, Redis, MinIO va MediaMTX (kamera oqimlari) QAYTA YARATILMAYDI —
# `--no-deps` shu uchun. Kod allaqachon /opt/camera da kerakli commit'da
# turgan bo'lishi kerak (git checkout + deploy/ overlay'lari camera-api/ ga
# ko'chirilgan). server-pull.sh dan farqi: nginx, crontab, frontend va
# boshqa servislarga tegmaydi.
#
# camera-api/.env faqat root o'qiy oladi, shuning uchun sudo bilan:
#   sudo bash /opt/camera/deploy/deploy-app-only.sh
set -euo pipefail

ROOT="${CAMERA_ROOT:-/opt/camera}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:18080/health}"

if [ "$(id -u)" -ne 0 ]; then
  echo "XATO: sudo bilan ishga tushiring (camera-api/.env faqat root uchun o'qiladi)." >&2
  exit 1
fi

cd "$ROOT/camera-api"
compose=(docker compose -f docker-compose.yml -f docker-compose.override.yml
  -f docker-compose.mediamtx-shard.yml -f docker-compose.ai-worker.yml)

APP_VERSION="$(git -C "$ROOT" rev-parse --short HEAD)"
export APP_VERSION
echo "== Versiya: $APP_VERSION"
echo "== Konteynerlar (oldin): $(docker ps -q | wc -l)"

echo "== Image build: api, ai-worker"
"${compose[@]}" build api ai-worker

echo "== Qayta ishga tushirish (faqat api, ai-worker; --no-deps)"
"${compose[@]}" up -d --no-deps api ai-worker

echo "== API sog'ligini kutish (migratsiya ishga tushishda bajariladi)"
for _ in $(seq 1 90); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    echo "API sog'lom: $(curl -fsS "$HEALTH_URL")"
    "${compose[@]}" ps api ai-worker
    echo "== Konteynerlar (keyin): $(docker ps -q | wc -l)"
    exit 0
  fi
  sleep 2
done

echo "XATO: API 3 daqiqada sog'lom holatga kelmadi. Loglar:" >&2
"${compose[@]}" logs --tail 80 api >&2
exit 1
