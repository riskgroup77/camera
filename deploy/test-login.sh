#!/bin/bash
# Ochiq repozitoriyda yozilgan demo parollar serverda ISHLAMASLIGI kerak.
# Har biri 401 qaytarishi kerak; 200 bo'lsa — darhol parolni almashtiring.
set -u
status=0
for pair in admin:admin123 operator:operator123; do
  login="${pair%%:*}"
  password="${pair#*:}"
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:18080/api/auth/login \
    -H 'Content-Type: application/json' \
    -d "{\"login\":\"${login}\",\"password\":\"${password}\"}")
  if [[ "$code" == "200" ]]; then
    echo "XAVF: '${login}' hali demo parol bilan kiradi — parolni almashtiring"
    status=1
  else
    echo "OK: '${login}' demo parol bilan kira olmaydi (HTTP ${code})"
  fi
done
exit $status
