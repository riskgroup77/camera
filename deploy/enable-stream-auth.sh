#!/bin/bash
# Jonli videoni (HLS) faqat tizimga kirganlar ko'ra oladigan qilish.
# Bir marta, server-pull.sh dan KEYIN, root huquqi bilan:
#
#   sudo bash /opt/camera/deploy/enable-stream-auth.sh
#
# Tartib uzilishsiz o'tish uchun tanlangan:
#   1) nginx imzoli havolani ham, eskisini ham qabul qiladi;
#   2) API imzoli havola bera boshlaydi (qayta ishga tushadi);
#   3) imzoli havola haqiqatan ochilishi tekshiriladi;
#   4) shundan keyingina imzosiz havolalar yopiladi.
# 3-qadam o'tmasa 4-qadam bajarilmaydi — video ishlashda davom etadi.
set -euo pipefail

APP_DIR=/opt/camera
ENV_FILE="$APP_DIR/camera-api/.env"
SNIPPET=/etc/nginx/snippets/cam-stream-secret.conf
HOST=cam.fermi.uz

cd "$APP_DIR/camera-api"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.mediamtx-shard.yml)
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  COMPOSE+=(-f docker-compose.gpu.yml)
fi

nginx_build=$(nginx -V 2>&1)
[[ "$nginx_build" == *--with-http_secure_link_module* ]] \
  || { echo "XATO: nginx secure_link modulisiz yig'ilgan"; exit 1; }
grep -qs "cam-fermi-stream-locations.conf" "/etc/nginx/sites-enabled/${HOST}.conf" \
  || { echo "XATO: nginx hali yangilanmagan — avval: sudo bash $APP_DIR/deploy/server-pull.sh"; exit 1; }

secret=$(grep -E '^STREAM_URL_SECRET=.' "$ENV_FILE" | tail -n1 | cut -d= -f2- || true)
if [[ -z "$secret" ]]; then
  secret=$(openssl rand -hex 32)
fi

# $1: 1 — imzosiz havolalar ham ochiq (o'tish davri), 0 — faqat imzolilari.
write_snippet() {
  local previous=""
  [[ -f "$SNIPPET" ]] && previous=$(cat "$SNIPPET")
  install -d -m 755 /etc/nginx/snippets
  (umask 077 && printf 'set $cam_stream_secret "%s";\nset $cam_stream_allow_unsigned %s;\n' "$secret" "$1" > "$SNIPPET")
  if ! nginx -t 2>/dev/null; then
    if [[ -n "$previous" ]]; then printf '%s\n' "$previous" > "$SNIPPET"; else rm -f "$SNIPPET"; fi
    nginx -t
    echo "XATO: nginx sozlamasi o'tmadi — avvalgi holat qaytarildi"
    exit 1
  fi
  systemctl reload nginx
  sleep 1
}

http_code() {
  local url="$1"
  [[ "$url" == /* ]] && url="https://${HOST}${url}"
  local host="${url#https://}"
  host="${host%%/*}"
  curl -sk -o /dev/null -w '%{http_code}' --max-time 30 --resolve "${host}:443:127.0.0.1" "$url" || true
}

echo "=== 1. nginx: o'tish davri ==="
write_snippet 1

echo "=== 2. API: imzoli havolalar ==="
# Sir buyruq qatorida emas (ps'da ko'rinmasin), muhit o'zgaruvchisida.
STREAM_SECRET="$secret" python3 - "$ENV_FILE" <<'PY'
import os, sys, tempfile
path, secret = sys.argv[1], os.environ["STREAM_SECRET"]
lines = [l for l in open(path).read().splitlines(keepends=True) if not l.startswith("STREAM_URL_SECRET=")]
if lines and not lines[-1].endswith("\n"):
    lines[-1] += "\n"
lines.append(f"STREAM_URL_SECRET={secret}\n")
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".env.")
with os.fdopen(fd, "w") as handle:
    handle.writelines(lines)
os.chmod(tmp, 0o600)
os.replace(tmp, path)
PY
"${COMPOSE[@]}" up -d --force-recreate api
for _ in $(seq 1 36); do
  curl -sf http://127.0.0.1:18080/health >/dev/null && break
  sleep 5
done

echo "=== 3. Imzoli havola tekshiruvi ==="
mapfile -t urls < <("${COMPOSE[@]}" exec -T api python - <<'PY'
import asyncio

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Camera
from app.services.stream_links import signed_stream_url


async def main() -> None:
    async with SessionLocal() as db:
        rows = await db.execute(
            select(Camera.stream_url)
            .where(Camera.status == "faol", Camera.stream_url.isnot(None), Camera.last_seen_at.isnot(None))
            .order_by(Camera.last_seen_at.desc())
            .limit(6)
        )
    for url in rows.scalars():
        print(signed_stream_url(url))


asyncio.run(main())
PY
)
working=""
for url in "${urls[@]}"; do
  [[ "$url" == *,* ]] || { echo "XATO: API havolani imzolamadi: $url"; break; }
  code=$(http_code "$url")
  echo "  $code  ${url%%,*},…"
  if [[ "$code" == "200" ]]; then working="$url"; break; fi
done
if [[ -z "$working" ]]; then
  echo "DIQQAT: imzoli havola bilan video ochilmadi — imzosiz havolalar OCHIQ qoldirildi."
  echo "        API loglari: ${COMPOSE[*]} logs api --tail 100"
  exit 1
fi

echo "=== 4. Imzosiz havolalar yopiladi ==="
write_snippet 0
unsigned=$(printf '%s' "$working" | sed -E 's#/(s[0-9]+)/[A-Za-z0-9_-]+,[0-9]+/#/\1/#')
echo "  imzoli:   $(http_code "$working")  (200 kutiladi)"
echo "  imzosiz:  $(http_code "$unsigned")  (403 kutiladi)"
echo "  soxta:    $(http_code "${working/,/x,}")  (403 kutiladi)"
echo "=== Tayyor. Ochiq turgan monitoring sahifalarini bir marta yangilang (F5). ==="
