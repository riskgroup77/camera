#!/bin/bash
# Production (cam.fermi.uz) ni GitHub'dagi main holatiga keltirish.
# Serverda, root huquqi bilan:
#
#   sudo bash /opt/camera/deploy/server-pull.sh
#
# GitHub Actions (.github/workflows/deploy.yml) ham aynan shu skriptni SSH
# orqali ishga tushiradi. Kod qaysi repodan klon qilingan bo'lsa, o'shaning
# `origin` idan olinadi — repo manzili bu yerda yozilmagan.
#
# 1) kod  2) production .env sozlamalari  3) frontend  4) MediaMTX sozlamasi
# 5) nginx (zaxira bilan; `nginx -t` o'tmasa avvalgi holat qaytadi)
# 6) Docker: MediaMTX shardlari + API (migratsiyalar API ishga tushganda)
# 7) tekshiruv — API sog'lom bo'lmasa skript nol bo'lmagan kod bilan chiqadi.
#
# Sozlanadigan muhit o'zgaruvchilari:
#   APP_DIR        — repo papkasi (standart: shu skript turgan repo, odatda /opt/camera)
#   DEPLOY_BRANCH  — qaysi branch (standart: main)
#   DEPLOY_REF     — aniq commit (ixtiyoriy; GitHub Actions CI o'tgan commitni beradi)
# Xuddi shular argument sifatida ham: server-pull.sh [--ref SHA] [--branch NOM]
# (sudo muhit o'zgaruvchisini o'tkazmasligi mumkin — argument ishonchliroq).
#   CAMERA_AI_WORKER=0 — AI'ni alohida konteynersiz (favqulodda) ishga tushirish
#
# Joylangan commit $APP_DIR/deploy/.deployed (va .deployed.history) ga yoziladi.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
DEPLOY_REF="${DEPLOY_REF:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref) DEPLOY_REF="${2:?--ref commit talab qiladi}"; shift 2 ;;
    --branch) DEPLOY_BRANCH="${2:?--branch nom talab qiladi}"; shift 2 ;;
    *) echo "Noma'lum argument: $1" >&2; exit 2 ;;
  esac
done
if [[ -n "$DEPLOY_REF" && ! "$DEPLOY_REF" =~ ^[0-9a-fA-F]{7,40}$ ]]; then
  echo "XATO: --ref faqat commit SHA bo'lishi mumkin" >&2
  exit 2
fi
if [[ ! "$DEPLOY_BRANCH" =~ ^[A-Za-z0-9._/-]+$ ]]; then
  echo "XATO: branch nomi noto'g'ri: $DEPLOY_BRANCH" >&2
  exit 2
fi
GIT="git -c safe.directory=${APP_DIR}"
LOCK_FILE="${DEPLOY_LOCK_FILE:-/var/lock/camera-deploy.lock}"
STATE_FILE="$APP_DIR/deploy/.deployed"
API_HEALTH_URL="${API_HEALTH_URL:-http://127.0.0.1:18080/health}"

on_error() {
  local code=$? line=$1
  echo "XATO: server-pull.sh ${line}-qatorda to'xtadi (kod ${code})." >&2
  exit "$code"
}
trap 'on_error $LINENO' ERR

acquire_lock() {
  # Ikki deploy bir vaqtda ishlamasin (qo'lda + GitHub Actions).
  # fd 9 qayta exec'da meros qoladi — qulf ikkinchi marta olinmaydi.
  exec 9>"$LOCK_FILE"
  if ! flock -w 600 9; then
    echo "XATO: boshqa deploy 10 daqiqadan beri ishlayapti ($LOCK_FILE)" >&2
    exit 1
  fi
}

update_code() {
  echo "=== 1. Git ==="
  local previous target
  previous=$($GIT rev-parse HEAD 2>/dev/null || echo "")
  $GIT fetch --prune origin "$DEPLOY_BRANCH"
  if [[ -n "$DEPLOY_REF" ]]; then
    # CI tekshirgan commit branch'da bo'lishi shart — boshqa narsani joylamaymiz.
    target=$($GIT rev-parse --verify "${DEPLOY_REF}^{commit}")
    if ! $GIT merge-base --is-ancestor "$target" "origin/${DEPLOY_BRANCH}"; then
      echo "XATO: ${DEPLOY_REF} origin/${DEPLOY_BRANCH} tarixida yo'q" >&2
      exit 1
    fi
  else
    target="origin/${DEPLOY_BRANCH}"
  fi
  $GIT reset --hard "$target"
  echo "$previous" >"$APP_DIR/deploy/.deployed.previous"
}

record_deploy() {
  local sha short when
  sha=$($GIT rev-parse HEAD)
  short=$($GIT rev-parse --short HEAD)
  when=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  printf 'commit=%s\nshort=%s\nbranch=%s\ndeployed_at=%s\n' "$sha" "$short" "$DEPLOY_BRANCH" "$when" >"$STATE_FILE"
  printf '%s %s %s\n' "$when" "$sha" "$($GIT log -1 --format=%s | tr '\n' ' ')" >>"$STATE_FILE.history"
  tail -n 200 "$STATE_FILE.history" >"$STATE_FILE.history.tmp" && mv "$STATE_FILE.history.tmp" "$STATE_FILE.history"
  # GitHub Actions shu qatorni o'qiydi.
  echo "DEPLOYED_COMMIT=${sha}"
}

main() {
  cd "$APP_DIR"

  if [[ -z "${CAMERA_PULL_REEXEC:-}" ]]; then
    acquire_lock
    update_code
    # Bu skriptning o'zi ham yangilangan bo'lishi mumkin — yangisini ishga tushiramiz.
    CAMERA_PULL_REEXEC=1 DEPLOY_BRANCH="$DEPLOY_BRANCH" DEPLOY_REF="$DEPLOY_REF" APP_DIR="$APP_DIR" \
      exec bash "$APP_DIR/deploy/server-pull.sh"
  fi
  $GIT log -1 --format='    %h %s'
  # Konteynerlar /metrics da versiyani ko'rsatadi (camera-api/docker-compose.yml).
  APP_VERSION=$($GIT rev-parse --short HEAD)
  export APP_VERSION

  echo "=== 2. Production .env ==="
  python3 "$APP_DIR/deploy/merge_env.py" "$APP_DIR/deploy/env.production.scale" "$APP_DIR/camera-api/.env"

  echo "=== 3. Frontend ==="
  npm ci --no-audit --no-fund
  npm run build
  rsync -a --delete dist/ /var/www/cam.fermi.uz/

  echo "=== 4. MediaMTX sozlamasi ==="
  # cp faylni joyida yozadi (inode o'zgarmaydi) — konteyner o'zgarishni ko'radi.
  cmp -s deploy/mediamtx.yml camera-api/mediamtx.yml || cp deploy/mediamtx.yml camera-api/mediamtx.yml

  echo "=== 5. Nginx ==="
  python3 "$APP_DIR/deploy/nginx_sync.py"

  echo "=== 6. Docker ==="
  cp deploy/docker-compose.override.yml deploy/docker-compose.mediamtx-shard.yml deploy/docker-compose.ai-worker.yml \
    deploy/docker-compose.gpu.yml camera-api/
  cd "$APP_DIR/camera-api"
  local compose=(docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.mediamtx-shard.yml)
  # AI alohida konteynerda (docker-compose.ai-worker.yml izohiga qarang).
  # O'chirish (favqulodda, eski bitta-konteyner rejimi): CAMERA_AI_WORKER=0
  if [[ "${CAMERA_AI_WORKER:-1}" != "0" ]]; then
    compose+=(-f docker-compose.ai-worker.yml)
  else
    docker rm -f camera-api-ai-worker-1 2>/dev/null || true
  fi
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    compose+=(-f docker-compose.gpu.yml)
  fi
  # Eski bitta-MediaMTX konteyneri (docker-compose.mediamtx.yml, eski
  # server-pull.sh ishga tushirardi) shardlar bilan bir portni talab qiladi.
  local names
  names=$(docker ps -a --format '{{.Names}}')
  if grep -qx camera-api-mediamtx-1 <<<"$names"; then
    echo "    eski bitta-MediaMTX konteyneri olib tashlanadi"
    docker rm -f camera-api-mediamtx-1
  fi
  "${compose[@]}" up -d --build

  echo "=== 7. Tekshiruv ==="
  local healthy=""
  for _ in $(seq 1 36); do
    if curl -sf "$API_HEALTH_URL" >/dev/null; then healthy=1; break; fi
    sleep 5
  done
  curl -s "$API_HEALTH_URL" || true
  echo
  "${compose[@]}" ps
  if [[ "${CAMERA_AI_WORKER:-1}" != "0" ]]; then
    # ai-worker AI qulfini olganini loglardan ko'rsatamiz (eski api
    # konteyneri to'xtaguncha bir necha soniya kutishi mumkin).
    local elected=""
    for _ in $(seq 1 24); do
      if "${compose[@]}" logs --since 10m ai-worker 2>/dev/null | grep -q leader_elected; then elected=1; break; fi
      sleep 5
    done
    if [[ -n "$elected" ]]; then
      echo "    ai-worker: AI sweeplari ishga tushdi"
    else
      echo "DIQQAT: ai-worker 2 daqiqada AI'ni boshlamadi — '${compose[*]} logs ai-worker'"
    fi
  fi
  if [[ -z "$healthy" ]]; then
    echo "XATO: API 3 daqiqada sog'lom holatga kelmadi — '${compose[*]} logs api'" >&2
    exit 1
  fi
  bash "$APP_DIR/deploy/test-login.sh" \
    || echo "DIQQAT: demo parol hali ishlaydi — Foydalanuvchilar va Rollar sahifasida almashtiring"

  if ! grep -q '^STREAM_URL_SECRET=.' "$APP_DIR/camera-api/.env"; then
    echo "ESLATMA: jonli video hali imzosiz. Yoqish: sudo bash $APP_DIR/deploy/enable-stream-auth.sh"
  fi

  # Monitoring steki o'rnatilgan bo'lsa — uning sozlamalarini ham yangilaymiz.
  if [[ -f "$APP_DIR/deploy/monitoring/.env" ]]; then
    echo "=== 8. Monitoring ==="
    bash "$APP_DIR/deploy/monitoring/up.sh" \
      || echo "DIQQAT: monitoring steki yangilanmadi — deploy/monitoring/README.md"
  fi

  cd "$APP_DIR"
  record_deploy
  echo "=== Tayyor ==="
}

main
