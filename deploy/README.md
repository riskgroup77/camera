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

## Updating production (on the server)

After changes are pushed to `main`, GitHub Actions deploys automatically (see
below). Manually, on the server:

```bash
sudo bash /opt/camera/deploy/server-pull.sh            # origin/main
sudo bash /opt/camera/deploy/server-pull.sh --ref <sha> # aniq commit (main tarixida bo'lishi shart)
```

The script pulls from the `origin` remote of whatever repository `/opt/camera`
was cloned from, exits non-zero if any step fails or the API is not healthy
within 3 minutes, holds a lock (`/var/lock/camera-deploy.lock`) so two deploys
never overlap, and records the deployed commit in `deploy/.deployed`
(history: `deploy/.deployed.history`, previous commit: `deploy/.deployed.previous`).
The commit is also exposed as `APP_VERSION` (`sm_app_info` in `/metrics`).

It pulls `main`, merges `deploy/env.production.scale` into `camera-api/.env`
(`deploy/merge_env.py` — other keys and secrets are left alone), builds the
frontend, copies `deploy/mediamtx.yml`, updates nginx with
`deploy/nginx_sync.py` (backups + automatic rollback when `nginx -t` fails;
`--dry-run` shows the diff only) and recreates the Docker stack with the
three MediaMTX shards. Database migrations run when the API starts.

### Live video access (one time)

MediaMTX has no user check of its own. HLS links handed out by the API are
signed (`/sN/<md5>,<expires>/cam-<uuid>/...`, see
`camera-api/app/services/stream_links.py`) and nginx rejects everything else.
Enable it once, after `server-pull.sh`:

```bash
sudo bash /opt/camera/deploy/enable-stream-auth.sh
```

The script shares one secret between `camera-api/.env` (`STREAM_URL_SECRET`)
and `/etc/nginx/snippets/cam-stream-secret.conf`, checks that a signed link
really plays and only then closes unsigned links. MediaMTX ports are bound to
`127.0.0.1`, so the LAN cannot bypass nginx either.

## GitHub Actions orqali deploy (CI/CD)

`.github/workflows/ci.yml` har push/PR'da frontend (lint, vitest, build) va
backend (toza bazada `alembic upgrade head`, pytest, API smoke-test) ni
tekshiradi. `main` dagi CI muvaffaqiyatli tugagach `.github/workflows/deploy.yml`
serverga SSH orqali kirib `server-pull.sh --ref <o'sha commit>` ni ishga tushiradi,
so'ng `HEALTHCHECK_URL` ni tekshiradi. Qo'lda: GitHub → Actions → Deploy →
*Run workflow* (ixtiyoriy commit SHA bilan).

**GitHub → Settings → Secrets and variables → Actions:**

| Nom | Turi | Qiymat |
|-----|------|--------|
| `DEPLOY_HOST` | secret | server IP yoki domeni |
| `DEPLOY_PORT` | secret | SSH porti (standart 22; bu serverda tashqaridan `2222`) |
| `DEPLOY_USER` | secret | deploy foydalanuvchisi (masalan `deploy`) |
| `DEPLOY_SSH_KEY` | secret | shu foydalanuvchining **maxsus** ed25519 yopiq kaliti |
| `DEPLOY_HOST_FINGERPRINT` | secret (ixtiyoriy, tavsiya) | `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` natijasidagi `SHA256:...` |
| `DEPLOY_PATH` | variable | repo papkasi, standart `/opt/camera` |
| `HEALTHCHECK_URL` | variable | `https://camapi.fermi.uz/health` |

**Serverda bir marta (root):**

```bash
adduser --disabled-password --gecos "" deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
# GitHub'ga qo'yiladigan kalit juftligi (yopig'i -> DEPLOY_SSH_KEY secret'iga):
ssh-keygen -t ed25519 -N "" -C github-deploy -f /root/github-deploy
cat /root/github-deploy.pub >> /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys && chmod 600 /home/deploy/.ssh/authorized_keys
# Faqat deploy skriptini parolsiz root sifatida ishga tushirishga ruxsat:
echo 'deploy ALL=(root) NOPASSWD: /usr/bin/bash /opt/camera/deploy/server-pull.sh, /usr/bin/bash /opt/camera/deploy/server-pull.sh *'   > /etc/sudoers.d/camera-deploy && chmod 440 /etc/sudoers.d/camera-deploy && visudo -c
cat /root/github-deploy   # -> GitHub secret DEPLOY_SSH_KEY, keyin: shred -u /root/github-deploy
```

Diqqat: `main` ga push qila oladigan har kim shu yo'l bilan serverda root
sifatida kod ishga tushiradi. `main` ni himoyalang (Settings → Branches:
PR majburiy, CI o'tishi shart) va `production` environment'ga reviewer qo'ying
(Settings → Environments → production → Required reviewers).

Muammo bo'lsa oldingi commitga qaytish: Actions → Deploy → Run workflow →
`ref` ga `deploy/.deployed.previous` dagi SHA ni yozing.

## Monitoring (Prometheus + Grafana + Telegram ogohlantirishlari)

`deploy/monitoring/README.md` ga qarang. `/metrics` tashqariga ochilmaydi
(`deploy/nginx/cam-fermi-api.conf` da `location ^~ /metrics { deny all; }`).

## One-command deploy (on the server)

```bash
sudo apt-get update && sudo apt-get install -y git
sudo git clone https://github.com/aiziyrak-coder/camera.git /opt/camera
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

## Login users

Production creates **no demo users**. On an empty database the API creates one
Super Admin from `INITIAL_ADMIN_LOGIN` / `INITIAL_ADMIN_PASSWORD` in
`camera-api/.env`; the setup scripts generate these (`camadmin` + a random
password) and save them in `/opt/camera/deploy/.secrets.env` (never committed).

The demo users `admin` / `admin123` and `operator` / `operator123` exist only
when `SEED_DEMO_USERS=true` (local development and tests). Their passwords are
public — if an older install still has them, change both passwords. While any
of them still works, the admin dashboard and *Tizim jurnali* show a critical
alert. `bash deploy/test-login.sh` checks that the demo passwords are rejected.

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
| MediaMTX HLS | `127.0.0.1:8888-8890` | stream subdomain (nginx, signed links) |
| Prometheus | `127.0.0.1:19090` | monitoring (SSH tunnel) |
| Alertmanager | `127.0.0.1:19093` | monitoring (SSH tunnel) |
| Grafana | `127.0.0.1:13000` | nginx: `deploy/monitoring/nginx/` |
| node-exporter / cAdvisor | `127.0.0.1:19100` / `127.0.0.1:18081` | Prometheus only |

After changing `.env`, recreate the API container so CORS and other env vars reload:

```bash
cd /opt/camera/camera-api
sudo docker compose up -d --force-recreate api
```
