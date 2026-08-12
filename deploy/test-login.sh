#!/bin/bash
set -e
echo '=== admin123 (no space) ==='
curl -s -X POST http://127.0.0.1:18080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"login":"admin","password":"admin123"}'
echo
echo '=== admin123 (with trailing space) ==='
curl -s -X POST http://127.0.0.1:18080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"login":"admin","password":"admin123 "}'
echo
echo '=== operator123 ==='
curl -s -X POST http://127.0.0.1:18080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"login":"operator","password":"operator123"}'
echo
