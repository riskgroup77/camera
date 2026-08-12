#!/bin/bash
set -euo pipefail
cp /opt/camera/deploy/docker-compose.override.yml /opt/camera/camera-api/docker-compose.override.yml
cp /opt/camera/deploy/docker-compose.mediamtx.yml /opt/camera/camera-api/docker-compose.mediamtx.yml
cd /opt/camera/camera-api
docker compose -f docker-compose.yml -f docker-compose.mediamtx.yml up -d
sleep 8
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep camera || true
curl -sf http://127.0.0.1:18080/health
echo
