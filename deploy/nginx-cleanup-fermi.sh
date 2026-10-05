#!/usr/bin/env bash
# fermi.uz nginx sozlamalarini repodagi holatga keltirish. Endi hamma ish
# deploy/nginx_sync.py da: takroriy cam-fermi-* havolalarni olib tashlaydi,
# serverdagi SSL yo'llarini saqlaydi, zaxira oladi va `nginx -t` o'tmasa
# avvalgi holatni qaytaradi (eski skript fayllarni qaytarmasdan qoldirardi).
set -euo pipefail
exec python3 /opt/camera/deploy/nginx_sync.py "$@"
