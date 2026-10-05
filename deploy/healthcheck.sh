#!/usr/bin/env bash
# Situatsion Markaz — serverdagi barcha qismlarning sog'liq tekshiruvi.
#
# Ishga tushirish — FONDA (terminal band bo'lmaydi):
#     cd /opt/camera && nohup bash deploy/healthcheck.sh </dev/null >/tmp/hc.txt 2>&1 &
# Natijani ko'rish (1-2 daqiqadan keyin; tugamagan bo'lsa qayerdaligi ko'rinadi):
#     cat /tmp/hc.txt
#
# Hech narsani o'zgartirmaydi — faqat o'qiydi.
#
# NIMA UCHUN LOG O'QISH CHEGARALANGAN. Birinchi versiya API logini
# boshidan oxirigacha o'qirdi va serverda jim qotib qoldi: 107 kamera
# tinimsiz JSON log yozadi, fayl ulkan, docker esa uni ketma-ket
# skanerlaydi. Hozir log faqat ikki joydan o'qiladi:
#   * OXIRIDAN cheklangan qator (--tail) — docker buni fayl oxiridan
#     tez o'qiydi; xatolar va AI o'tishlari shu yerdan sanaladi;
#   * BOSHIDAN birinchi qatorlar (| head) — ishga tushish yozuvi fayl
#     boshida turadi, head yetgach o'qish darhol to'xtaydi.
# --since ishlatilmaydi: u vaqtni topish uchun faylni baribir boshidan
# skanerlaydi.
#
# Baholashdagi ikki nozik joy — ular ataylab "xato" deb hisoblanmaydi:
#   * AI o'tishi natija bermasa logga YOZMAYDI (ai_scheduler.py). Ishonchli
#     signal — faqat "scheduler sweep failed".
#   * Video shlyuz yo'llari talab bo'yicha ochiladi: hech kim ko'rmayotgan
#     kamera "ready" bo'lmaydi. Tasvir cameras.last_frame_at orqali
#     tekshiriladi.

set -u
# Hech bir ichki buyruq terminaldan o'qishga urinmasin: fonda ishlaganda
# terminal o'qishga uringan jarayon to'xtatib qo'yiladi (SIGTTIN) va
# skript cheksiz kutib qoladi.
exec </dev/null

cd "$(dirname "$0")/../camera-api" || { echo "camera-api papkasi topilmadi"; exit 1; }

DC="docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.mediamtx-shard.yml"
REPORT="/tmp/healthcheck-$(date +%Y%m%d-%H%M%S).txt"
RETIRED_MODULES="4,5,11,16,18,24,25"
EXPECTED_STAFF=688
LOG_TAIL=20000

OK=0; WARN=0; FAIL=0
ok()      { echo "  [ OK ]  $*"; OK=$((OK + 1)); }
warn()    { echo "  [ !! ]  $*"; WARN=$((WARN + 1)); }
fail()    { echo "  [XATO]  $*"; FAIL=$((FAIL + 1)); }
info()    { echo "          $*"; }
section() { echo; echo "━━ $* ━━  ($(date +%H:%M:%S))"; }

sql() {
  timeout 20 $DC exec -T db psql -U camera_api -d camera_api -At -F '|' -c "$1" 2>/dev/null
}

http_code() {
  curl -sk -o /dev/null --max-time 15 -w '%{http_code}' "$@" 2>/dev/null || echo "000"
}

main() {
  echo "Situatsion Markaz — sog'liq tekshiruvi — $(date '+%d.%m.%Y %H:%M:%S')"

  # ─────────────────────────────────────────── 1
  section "1. Konteynerlar"
  API_CID=""
  for svc in db redis minio api mediamtx-0 mediamtx-1 mediamtx-2; do
    cid=$(timeout 20 $DC ps -q "$svc" 2>/dev/null | head -1)
    if [ -z "$cid" ]; then
      fail "$svc: konteyner topilmadi"
      continue
    fi
    [ "$svc" = "api" ] && API_CID="$cid"
    state=$(docker inspect -f '{{.State.Status}}' "$cid")
    health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}}' "$cid")
    restarts=$(docker inspect -f '{{.RestartCount}}' "$cid")
    started=$(docker inspect -f '{{.State.StartedAt}}' "$cid" | cut -c1-16 | tr 'T' ' ')
    if [ "$state" != "running" ]; then
      fail "$svc: holati '$state'"
    elif [ "$health" = "unhealthy" ]; then
      fail "$svc: ishlamoqda, lekin sog'liq tekshiruvidan o'tmayapti"
    elif [ "$restarts" -gt 0 ]; then
      warn "$svc: ishlamoqda, lekin $restarts marta qayta ishga tushgan (oxirgisi $started UTC)"
    else
      ok "$svc: ishlamoqda (ishga tushgan $started UTC)"
    fi
  done

  # ─────────────────────────────────────────── 2
  section "2. API va unga bog'liq xizmatlar"
  h=$(curl -s --max-time 15 http://127.0.0.1:18080/health 2>/dev/null)
  if [ -z "$h" ]; then
    fail "API javob bermayapti (127.0.0.1:18080/health)"
  else
    for dep in database storage video_gateway; do
      if echo "$h" | grep -q "\"$dep\":\"ok\""; then
        ok "$dep"
      else
        fail "$dep: $(echo "$h" | grep -o "\"$dep\":\"[^\"]*\"")"
      fi
    done
  fi

  cur=$(sql "SELECT version_num FROM alembic_version")
  head=$(timeout 45 $DC exec -T api alembic heads 2>/dev/null | awk '{print $1}' | head -1)
  if [ -z "$cur" ]; then
    fail "Migratsiya versiyasini o'qib bo'lmadi"
  elif [ -n "$head" ] && [ "$cur" = "$head" ]; then
    ok "Ma'lumotlar bazasi sxemasi eng so'nggi versiyada ($cur)"
  else
    fail "Migratsiya orqada qolgan: bazada $cur, kodda ${head:-aniqlanmadi}"
  fi

  # ─────────────────────────────────────────── 3
  section "3. AI kriteriyalari"
  r=$(sql "SELECT count(*), count(*) FILTER (WHERE active) FROM ai_modules")
  total=${r%%|*}; active=${r##*|}
  if [ "${total:-0}" = "19" ] && [ "${active:-0}" = "19" ]; then
    ok "19 ta kriteriyaning hammasi yoqilgan"
  else
    warn "Kriteriyalar: jami ${total:-?}, yoqilgan ${active:-?}"
    sql "SELECT '#'||code||' '||name FROM ai_modules WHERE NOT active ORDER BY code" | while read -r line; do
      info "o'chiq: $line"
    done
  fi

  retired=$(sql "SELECT count(*) FROM events WHERE module_code IN ($RETIRED_MODULES) AND occurred_at > now() - interval '24 hours'")
  if [ "${retired:-0}" = "0" ]; then
    ok "Olib tashlangan 7 ta kriteriyadan yangi hodisa yo'q (kodi haqiqatan o'chgan)"
  else
    fail "Olib tashlangan kriteriyalardan so'nggi 24 soatda $retired ta hodisa — eski kod ishlab turibdi"
  fi

  # ─────────────────────────────────────────── 4
  section "4. Rejalashtirgich va AI o'tishlari"
  RECENT_LOGS=""
  if [ -z "$API_CID" ]; then
    fail "API konteyneri yo'q — rejalashtirgichni tekshirib bo'lmaydi"
  else
    # Fayl BOSHI: ishga tushish yozuvi shu yerda; head yetgach o'qish to'xtaydi
    # Logda nol baytlar bor: grep ularni ko'rib faylni "binary" deb qatorni
    # chop etmasdi — shuning uchun avval tozalanadi va -a qo'yiladi.
    started_line=$(timeout 30 docker logs "$API_CID" 2>&1 | head -5000 | tr -d '\000' | grep -aF "AI scheduler started" | tail -1)
    if [ -z "$started_line" ]; then
      warn "Rejalashtirgichning ishga tushish yozuvi logning boshida topilmadi (log aylantirilgan bo'lishi mumkin)"
    else
      ok "Rejalashtirgich ishga tushgan"
      registered=$(echo "$started_line" | grep -o '"[a-z_]*"' | tr -d '"' | tr '\n' ' ')
      missing=""
      for sweep in fire zone_entry fight teacher_punctuality disorder dress_code badge ppe smoking \
                   lesson_quality lesson_attendance absence_marking; do
        echo " $registered " | grep -q " $sweep " || missing="$missing $sweep"
      done
      if echo " $registered " | grep -q " unified_face "; then :; else
        for sweep in attendance vision_sleep unauthorized; do
          echo " $registered " | grep -q " $sweep " || missing="$missing $sweep"
        done
      fi
      if [ -z "$missing" ]; then
        ok "Barcha AI o'tishlari ro'yxatdan o'tgan"
      else
        fail "Ro'yxatda yo'q o'tishlar:$missing"
      fi
    fi

    # Fayl OXIRI: bir marta o'qiladi va 4- hamda 9-bo'limda qayta ishlatiladi
    RECENT_LOGS=$(timeout 60 docker logs --tail "$LOG_TAIL" "$API_CID" 2>&1 | tr -d '\000')
    span=$(echo "$RECENT_LOGS" | grep -o '"timestamp": *"[^"]*"' | sed -n '1p;$p' | sed 's/.*"\([^"]*\)"$/\1/' | cut -c12-16 | tr '\n' ' ')
    info "Tahlil qilingan log: oxirgi $LOG_TAIL qator (${span:-vaqt oraligi aniqlanmadi})"

    failed=$(echo "$RECENT_LOGS" | grep -F "scheduler sweep failed" | grep -o '"sweep": *"[a-z_]*"' \
             | sed 's/.*"\([a-z_]*\)"$/\1/' | sort | uniq -c | sort -rn)
    tick_failed=$(echo "$RECENT_LOGS" | grep -cF "AI scheduler tick failed")
    if [ -z "$failed" ] && [ "$tick_failed" = "0" ]; then
      ok "Birorta AI o'tishi xato bermagan"
    else
      [ "$tick_failed" != "0" ] && fail "Rejalashtirgich tsikli $tick_failed marta yiqilgan"
      if [ -n "$failed" ]; then
        fail "Xato bergan o'tishlar:"
        echo "$failed" | while read -r n name; do info "$name — $n marta"; done
      fi
    fi

    active_sweeps=$(echo "$RECENT_LOGS" | grep -F "scheduler sweep completed" | grep -o '"sweep": *"[a-z_]*"' \
                    | sed 's/.*"\([a-z_]*\)"$/\1/' | sort | uniq -c | sort -rn | awk '{printf "%s(%s) ", $2, $1}')
    # ${var:-...} standart qiymati ichida apostrof ishlatilmaydi: bash uni
    # qo'shtirnoq ichida ham tirnoq deb o'qiydi va skript buziladi.
    if [ -n "$active_sweeps" ]; then
      info "Natija bergan o'tishlar: $active_sweeps"
    else
      info "Natija bergan o'tishlar: hozircha yo'q — bu xato emas, natija bo'lmasa log yozilmaydi"
    fi
  fi

  # ─────────────────────────────────────────── 5
  section "5. Kameralar va video"
  r=$(sql "SELECT count(*), count(*) FILTER (WHERE status = 'faol'), count(*) FILTER (WHERE last_seen_at > now() - interval '10 minutes'), count(*) FILTER (WHERE last_frame_at > now() - interval '10 minutes') FROM cameras")
  IFS='|' read -r cam_total cam_active cam_online cam_video <<< "$r"
  if [ "${cam_total:-0}" = "0" ]; then
    fail "Bazada kamera yo'q (yoki bazaga ulanib bo'lmadi)"
  else
    info "Jami: $cam_total | faol: $cam_active | tarmoqda: $cam_online | tasvir berayotgan: $cam_video"
    if [ "$cam_online" -ge "$cam_active" ]; then
      ok "Faol kameralarning hammasi tarmoqda ($cam_online/$cam_active)"
    else
      warn "Tarmoqda yo'q faol kameralar: $((cam_active - cam_online)) ta"
    fi
    if [ "$cam_video" -ge "$cam_online" ]; then
      ok "Tarmoqdagi kameralarning hammasi tasvir bermoqda ($cam_video/$cam_online)"
    else
      warn "\"Ko'r\" kameralar (tarmoqda bor, tasvir yo'q): $((cam_online - cam_video)) ta"
      sql "SELECT name FROM cameras WHERE last_seen_at > now() - interval '10 minutes' AND (last_frame_at IS NULL OR last_frame_at <= now() - interval '10 minutes') ORDER BY name LIMIT 10" \
        | while read -r name; do info "ko'r: $name"; done
    fi
  fi

  for port in 9997 9998 9999; do
    body=$(curl -s --max-time 10 "http://127.0.0.1:$port/v3/paths/list" 2>/dev/null)
    if [ -z "$body" ]; then
      fail "Video shlyuz tuguni :$port javob bermayapti"
    else
      paths=$(echo "$body" | grep -o '"name":"' | wc -l)
      ready=$(echo "$body" | grep -o '"ready":true' | wc -l)
      ok "Video shlyuz tuguni :$port — $paths yo'l, hozir ko'rilayotgani $ready"
    fi
  done

  # ─────────────────────────────────────────── 6
  section "6. Hodisalar (so'nggi 1 soat / 24 soat)"
  rows=$(sql "SELECT module_code, module_name, count(*) FILTER (WHERE occurred_at > now() - interval '1 hour'), count(*) FROM events WHERE occurred_at > now() - interval '24 hours' GROUP BY module_code, module_name ORDER BY module_code")
  if [ -z "$rows" ]; then
    info "So'nggi 24 soatda hodisa yo'q"
  else
    echo "$rows" | while IFS='|' read -r code name h1 h24; do
      printf "          #%-3s %-40.40s %5s / %s\n" "$code" "$name" "$h1" "$h24"
    done
    storm=$(sql "SELECT '#'||module_code||' '||module_name||' — '||count(*)||' ta' FROM events WHERE occurred_at > now() - interval '1 hour' GROUP BY module_code, module_name HAVING count(*) > 60")
    if [ -z "$storm" ]; then
      ok "Hech bir modul signal yog'dirmayapti (soatiga 60 dan kam)"
    else
      echo "$storm" | while read -r line; do warn "Juda ko'p signal (yolg'on bo'lishi mumkin): $line"; done
    fi
  fi
  pending=$(sql "SELECT count(*) FROM events WHERE status = 'yangi'")
  info "Ko'rib chiqilmagan hodisalar: ${pending:-?}"

  # ─────────────────────────────────────────── 7
  section "7. Xodimlar, biometrika va davomat"
  r=$(sql "SELECT count(*) FILTER (WHERE pinfl IS NOT NULL), count(*) FILTER (WHERE biometrics_status = 'tasdiqlangan'), count(*) FILTER (WHERE pinfl = '00000000000000') FROM students_staff")
  IFS='|' read -r staff enrolled testuser <<< "$r"
  if [ "${staff:-0}" -ge "$EXPECTED_STAFF" ]; then
    ok "JSHSHIRli xodimlar: $staff ta (kutilgan $EXPECTED_STAFF)"
  else
    fail "JSHSHIRli xodimlar ${staff:-?} ta — kutilgan $EXPECTED_STAFF (import to'liq emas)"
  fi
  if [ "${enrolled:-0}" -ge 10 ]; then
    ok "Yuzi tasdiqlanganlar: $enrolled ta"
  else
    warn "Yuzi tasdiqlanganlar: ${enrolled:-?} ta — 10 tagacha #1 (begona shaxs) o'zini o'chirib turadi"
  fi
  [ "${testuser:-0}" != "0" ] && warn "Sinov hisobi (JSHSHIR 00000000000000) hali o'chirilmagan"
  today=$(sql "SELECT count(*) FROM attendance_records WHERE date = (now() AT TIME ZONE 'Asia/Tashkent')::date")
  info "Bugungi davomat yozuvlari: ${today:-?}"

  # ─────────────────────────────────────────── 8
  section "8. Sahifalar va ochiq manzillar"
  check() {  # $1 nomi, $2 kutilgan kodlar (a|b), qolgani curl argumentlari
    local label="$1" expect="$2"; shift 2
    local code; code=$(http_code "$@")
    if echo "|$expect|" | grep -q "|$code|"; then ok "$label ($code)"; else fail "$label: kutilgan $expect, keldi $code"; fi
  }
  check "Monitoring sahifasi (cam.fermi.uz)"      "200"     -H "Host: cam.fermi.uz" https://127.0.0.1/
  check "Ro'yxatdan o'tish sahifasi"               "200"     -H "Host: cam.fermi.uz" https://127.0.0.1/royxatdan-otish
  check "API tashqi manzili (camapi.fermi.uz)"     "200"     -H "Host: camapi.fermi.uz" https://127.0.0.1/health
  check "Ro'yxatdan o'tish: jonli yo'naltirish"    "200"     -X POST http://127.0.0.1:18080/api/public/enrollment/pose-check \
                                                            -F "expected=front" -F "photo=@/dev/null;filename=x.jpg;type=image/jpeg"
  check "Ro'yxatdan o'tish: qidiruv tekshiruvi"    "422"     -X POST http://127.0.0.1:18080/api/public/enrollment/lookup \
                                                            -H "Content-Type: application/json" -d '{}'
  check "Excel eksport kirishsiz yopiq"            "401|403" http://127.0.0.1:18080/api/students-staff/export
  check "Shaxslar ro'yxati kirishsiz yopiq"        "401|403" http://127.0.0.1:18080/api/students-staff

  if timeout 30 $DC exec -T api python -c "import openpyxl" >/dev/null 2>&1; then
    ok "Excel kutubxonasi (openpyxl) o'rnatilgan"
  else
    fail "openpyxl yo'q — API obrazi --build bilan qayta qurilmagan"
  fi

  # ─────────────────────────────────────────── 9
  section "9. Xatolar (4-bo'limdagi o'sha log qismi)"
  if [ -n "$RECENT_LOGS" ]; then
    errs=$(echo "$RECENT_LOGS" | grep -E '"level": *"(ERROR|CRITICAL)"')
    n=$(printf '%s' "$errs" | grep -c . || true)
    if [ "$n" = "0" ]; then
      ok "API logida xato yo'q"
    else
      warn "API logida $n ta xato. Eng ko'p uchraganlari:"
      echo "$errs" | grep -o '"message": *"[^"]*"' | sed 's/"message": *//' | sort | uniq -c | sort -rn | head -5 \
        | while read -r line; do info "$line"; done
    fi
  else
    info "Log o'qilmadi — tekshiruv o'tkazib yuborildi"
  fi

  # ─────────────────────────────────────────── 10
  section "10. Server resurslari"
  disk=$(df -P / | awk 'NR==2 {gsub("%", "", $5); print $5}')
  mem=$(free -m | awk '/^Mem:/ {printf "%d", $3 * 100 / $2}')
  load=$(cut -d' ' -f1 /proc/loadavg); cores=$(nproc)
  [ "$disk" -lt 85 ] && ok "Disk: ${disk}% band" || warn "Disk: ${disk}% band — joy tugashiga yaqin"
  [ "$mem" -lt 90 ] && ok "Operativ xotira: ${mem}% band" || warn "Operativ xotira: ${mem}% band"
  info "Yuklama: $load ($cores yadro)"
  if [ -n "$API_CID" ]; then
    stats=$(timeout 15 docker stats --no-stream --format 'CPU {{.CPUPerc}}, xotira {{.MemUsage}}' "$API_CID" 2>/dev/null)
    info "API konteyneri: ${stats:-oqib bolmadi}"
  fi

  # ─────────────────────────────────────────── Xulosa
  echo
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  XULOSA:  $OK ta OK   |   $WARN ta ogohlantirish   |   $FAIL ta xato"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  TEKSHIRUV TUGADI"
}

main 2>&1 | tee "$REPORT"
