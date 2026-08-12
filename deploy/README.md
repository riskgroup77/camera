# Production deploy — cam.fermi.uz

## DNS (A records → server IP `87.192.230.208`)

| Name (in fermi.uz zone) | Full domain | Purpose |
|-------------------------|-------------|---------|
| `cam` | `cam.fermi.uz` | React frontend |
| `camapi` | `camapi.fermi.uz` | FastAPI backend + WebSocket |
| `storage.camapi` | `storage.camapi.fermi.uz` | MinIO (presigned upload URLs) |
| `stream.cam` | `stream.cam.fermi.uz` | MediaMTX HLS video streams |

Add records in **ahost.uz → Mening domenlar → fermi.uz → DNS hosting → Zone Editor**:

1. **Type:** A, **Name:** `storage.camapi`, **Value:** `87.192.230.208`
2. **Type:** A, **Name:** `stream.cam`, **Value:** `87.192.230.208`

After DNS propagates (5–30 min), the server auto-installs SSL:

```bash
# Timer checks every 5 minutes — or run manually:
sudo bash /opt/camera/deploy/wait-dns-storage-stream.sh
```

Remove duplicate nginx configs (if `cam-fermi-*` warnings appear):

```bash
sudo bash /opt/camera/deploy/nginx-cleanup-fermi.sh
```

## One-command deploy (on the server)

```bash
sudo apt-get update && sudo apt-get install -y git
sudo git clone https://github.com/riskgroup77/camera.git /opt/camera
cd /opt/camera
sudo bash deploy/server-setup.sh
```

For servers that already have Docker/nginx/node installed:

```bash
sudo bash deploy/server-setup-slim.sh
```

## Migrate devflix → fermi domains

If the stack was deployed with old `*.devflix.uz` domains:

```bash
sudo bash deploy/migrate-to-fermi.sh
```

## SSH note

If port 22 is blocked externally, use the port that responds (often `2222`):

```bash
ssh admin_root@87.192.230.208 -p 2222
```

## Default login users (seed)

| Login | Password | Role |
|-------|----------|------|
| `admin` | `admin123` | super-admin |
| `operator` | `operator123` | admin |

A stronger production admin (`camadmin`) is created automatically; credentials are saved in `/opt/camera/deploy/.secrets.env` (never committed).

## Manual checks

```bash
curl https://camapi.fermi.uz/health
docker compose -f /opt/camera/camera-api logs -f api
```

## Port mapping (host)

| Service | Host port | Notes |
|---------|-----------|-------|
| API | `127.0.0.1:18080` | nginx proxies HTTPS |
| MinIO | `127.0.0.1:9100` | storage subdomain |
| MediaMTX HLS | `8888` | stream subdomain |

After changing `.env`, recreate the API container so CORS and other env vars reload:

```bash
cd /opt/camera/camera-api
sudo docker compose up -d --force-recreate api
```
