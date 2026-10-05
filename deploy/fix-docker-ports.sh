#!/bin/bash
set -euo pipefail
cd /opt/camera
git -c safe.directory=/opt/camera pull origin main
cp deploy/docker-compose.override.yml camera-api/docker-compose.override.yml
cp deploy/docker-compose.mediamtx.yml camera-api/docker-compose.mediamtx.yml
cd camera-api
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.mediamtx.yml up -d
sleep 12
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep camera || true
curl -sf http://127.0.0.1:18080/health
echo
docker exec camera-api-api-1 env | grep CORS
