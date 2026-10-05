#!/usr/bin/env bash
# Temporary self-signed HTTPS until Let's Encrypt (wait-dns-and-ssl.sh replaces certs).
set -euo pipefail

CERT_DIR=/etc/ssl/camera-devflix
DOMAINS=cam.devflix.uz,camapi.devflix.uz,storage.camapi.devflix.uz,stream.cam.devflix.uz

mkdir -p "$CERT_DIR"
if [[ ! -f "$CERT_DIR/fullchain.pem ]]; then
  openssl req -x509 -nodes -days 90 -newkey rsa:2048 \
    -keyout "$CERT_DIR/privkey.pem" \
    -out "$CERT_DIR/fullchain.pem" \
    -subj "/CN=cam.devflix.uz/O=Camera/O=Devflix" \
    -addext "subjectAltName=DNS:cam.devflix.uz,DNS:camapi.devflix.uz,DNS:storage.camapi.devflix.uz,DNS:stream.cam.devflix.uz"
fi

patch_ssl() {
  local file=$1
  grep -q 'listen 443' "$file" && return 0
  local tmp
  tmp=$(mktemp)
  awk -v cert="$CERT_DIR/fullchain.pem" -v key="$CERT_DIR/privkey.pem" '
    /^server \{/ && !done {
      print
      print "    listen 443 ssl;"
      print "    listen [::]:443 ssl;"
      print "    ssl_certificate " cert ";"
      print "    ssl_certificate_key " key ";"
      print "    ssl_protocols TLSv1.2 TLSv1.3;"
      done=1
      next
    }
    { print }
  ' "$file" > "$tmp"
  mv "$tmp" "$file"
}

for f in /etc/nginx/sites-available/cam.devflix.uz.conf \
         /etc/nginx/sites-available/camapi.devflix.uz.conf \
         /etc/nginx/sites-available/storage.camapi.devflix.uz.conf \
         /etc/nginx/sites-available/stream.cam.devflix.uz.conf; do
  [[ -f $f ]] && patch_ssl "$f"
done

# ACME webroot for future certbot
mkdir -p /var/www/certbot
for f in /etc/nginx/sites-available/cam*.conf /etc/nginx/sites-available/storage.camapi*.conf /etc/nginx/sites-available/stream.cam*.conf; do
  [[ -f $f ]] || continue
  grep -q acme-challenge "$f" && continue
  sed -i '/listen 80;/a\    location /.well-known/acme-challenge/ { root /var/www/certbot; }' "$f"
done

nginx -t
systemctl reload nginx
echo "Interim self-signed HTTPS enabled (browser will warn until Let's Encrypt)"
