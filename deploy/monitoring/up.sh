#!/bin/bash
# Monitoring stekini ishga tushirish / yangilash (serverda, root):
#
#   sudo bash /opt/camera/deploy/monitoring/up.sh
#
# 1) .env dan Alertmanager sozlamasini yaratadi (Telegram)
# 2) camera-api/.env dagi METRICS_TOKEN ni Prometheus'ga beradi
# 3) sozlamalarni promtool/amtool bilan tekshiradi — xato bo'lsa hech narsa
#    o'zgarmaydi
# 4) konteynerlarni ko'taradi va Prometheus/Alertmanager'ni qayta yuklaydi
#
# server-pull.sh deploy/monitoring/.env bor bo'lsa buni o'zi chaqiradi.
set -Eeuo pipefail

MON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$MON_DIR/../.." && pwd)"
ENV_FILE="$MON_DIR/.env"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$MON_DIR/docker-compose.monitoring.yml")
# Konteynerlar ichidagi foydalanuvchi (prom/*, alertmanager: nobody).
NOBODY=65534

if [[ ! -f "$ENV_FILE" ]]; then
  echo "XATO: $ENV_FILE yo'q. Avval: cp $MON_DIR/.env.example $ENV_FILE va to'ldiring." >&2
  exit 1
fi
chmod 600 "$ENV_FILE"
if ! grep -q '^GRAFANA_ADMIN_PASSWORD=.' "$ENV_FILE"; then
  echo "XATO: GRAFANA_ADMIN_PASSWORD bo'sh ($ENV_FILE)" >&2
  exit 1
fi

echo "=== Monitoring: sozlamalar ==="
python3 "$MON_DIR/render_alertmanager.py" "$ENV_FILE" "$MON_DIR/alertmanager/alertmanager.generated.yml"
chown "$NOBODY:$NOBODY" "$MON_DIR/alertmanager/alertmanager.generated.yml"

# API METRICS_TOKEN bo'sh bo'lsa ham fayl kerak (Prometheus uni o'qiydi);
# token o'rnatilmagan API Authorization sarlavhasiga qaramaydi.
secrets="$MON_DIR/prometheus/secrets"
install -d -m 700 -o "$NOBODY" -g "$NOBODY" "$secrets"
token=""
if [[ -f "$APP_DIR/camera-api/.env" ]]; then
  token=$(grep -E '^METRICS_TOKEN=' "$APP_DIR/camera-api/.env" | tail -n 1 | cut -d= -f2- | tr -d "\"' \r") || true
fi
umask 077
printf '%s' "${token:-none}" >"$secrets/metrics_token"
chown "$NOBODY:$NOBODY" "$secrets/metrics_token"

echo "=== Monitoring: tekshiruv (promtool / amtool) ==="
"${COMPOSE[@]}" run --rm --no-deps --entrypoint promtool prometheus \
  check config /etc/prometheus/prometheus.yml
"${COMPOSE[@]}" run --rm --no-deps --entrypoint amtool alertmanager \
  check-config /etc/alertmanager/alertmanager.generated.yml

echo "=== Monitoring: konteynerlar ==="
"${COMPOSE[@]}" up -d --remove-orphans

# Bind-mount qilingan fayllar o'zgargan bo'lsa konteyner o'zi bilmaydi.
reloaded=""
for _ in $(seq 1 30); do
  if curl -sf -X POST http://127.0.0.1:19090/-/reload >/dev/null; then reloaded=1; break; fi
  sleep 2
done
[[ -n "$reloaded" ]] || { echo "XATO: Prometheus 60 soniyada javob bermadi" >&2; exit 1; }
curl -sf -X POST http://127.0.0.1:19093/-/reload >/dev/null \
  || echo "DIQQAT: Alertmanager qayta yuklanmadi — '${COMPOSE[*]} logs alertmanager'"

echo "=== Monitoring: nishonlar ==="
sleep 5
curl -sf http://127.0.0.1:19090/api/v1/targets?state=active \
  | python3 -c '
import json, sys
for t in json.load(sys.stdin)["data"]["activeTargets"]:
    err = t.get("lastError") or ""
    print("    %-14s %-8s %s" % (t["labels"]["job"], t["health"], err))
' || echo "DIQQAT: nishonlar ro'yxati olinmadi"
"${COMPOSE[@]}" ps
echo "=== Monitoring tayyor: Grafana http://127.0.0.1:13000 (nginx orqali — README) ==="
