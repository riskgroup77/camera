# Production deploy — cam.devflix.uz

## DNS (A records → server IP `87.192.230.208`)

| Domain | Purpose |
|--------|---------|
| `cam.devflix.uz` | React frontend |
| `camapi.devflix.uz` | FastAPI backend + WebSocket |
| `storage.camapi.devflix.uz` | MinIO (presigned upload URLs) |
| `stream.cam.devflix.uz` | MediaMTX HLS video streams |

## One-command deploy (on the server)

```bash
sudo apt-get update && sudo apt-get install -y git
sudo git clone https://github.com/riskgroup77/camera.git /opt/camera
cd /opt/camera
sudo bash deploy/server-setup.sh
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

A stronger production admin is created automatically; credentials are saved in `/opt/camera/deploy/.secrets.env`.

## Manual checks

```bash
curl https://camapi.devflix.uz/health
docker compose -f /opt/camera/camera-api logs -f api
```
