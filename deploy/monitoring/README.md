# Monitoring — Prometheus, Grafana, Telegram ogohlantirishlari

Situatsion Markaz serverining holatini kuzatish: kameralar, hodisalar, davomat,
AI modullari, server va konteyner resurslari. Muammo bo'lsa Telegram guruhiga
xabar keladi.

```
 API (/metrics) ─┐
 node-exporter ──┼──> Prometheus ──> Alertmanager ──> Telegram
 cAdvisor ───────┘         │
                           └──> Grafana ──> nginx (HTTPS + login) ──> brauzer
```

| Xizmat | Manzil (faqat serverning o'zida) | Vazifasi |
|--------|----------------------------------|----------|
| Prometheus | `127.0.0.1:19090` | ko'rsatkichlarni yig'adi va saqlaydi (30 kun / 20 GB) |
| Alertmanager | `127.0.0.1:19093` | ogohlantirishlarni Telegram'ga yuboradi |
| Grafana | `127.0.0.1:13000` | "Situatsion Markaz" dashboardi |
| node-exporter | `127.0.0.1:19100` | server: CPU, xotira, disk, tarmoq |
| cAdvisor | `127.0.0.1:18081` | har bir Docker konteynerining CPU/xotirasi |

Hech biri internetga to'g'ridan-to'g'ri ochilmaydi. Grafana nginx orqali
(parol bilan), qolganlari faqat SSH tunnel orqali ko'riladi.

## 1. O'rnatish (bir marta, serverda root)

```bash
cd /opt/camera
cp deploy/monitoring/.env.example deploy/monitoring/.env
chmod 600 deploy/monitoring/.env
nano deploy/monitoring/.env        # GRAFANA_ADMIN_PASSWORD, TELEGRAM_* ni to'ldiring
sudo bash deploy/monitoring/up.sh
```

`up.sh`:
1. `.env` dan Alertmanager sozlamasini yaratadi (`alertmanager.generated.yml`, gitignore'da);
2. `camera-api/.env` dagi `METRICS_TOKEN` ni Prometheus'ga beradi (bo'lsa);
3. sozlamalarni `promtool` va `amtool` bilan tekshiradi — xato bo'lsa hech narsa o'zgarmaydi;
4. konteynerlarni ko'taradi, Prometheus/Alertmanager'ni qayta yuklaydi va
   nishonlar holatini chiqaradi (`camera-api up`, `node up`, `cadvisor up`).

`deploy/monitoring/.env` mavjud bo'lsa, har `server-pull.sh` (GitHub Actions
deploy ham) oxirida `up.sh` avtomatik ishga tushadi — qoida va dashboard
o'zgarishlari o'zi qo'llanadi.

### Telegram

1. Telegram'da **@BotFather** → `/newbot` → token (`123456:ABC...`) → `TELEGRAM_BOT_TOKEN`.
   Bildirishnomalar uchun ishlatilayotgan bot (camera-api `TELEGRAM_BOT_TOKEN`)
   ham bo'ladi, lekin alohida bot tavsiya etiladi.
2. Botni navbatchilar guruhiga qo'shing va guruhga istalgan xabar yozing.
3. Chat ID: `curl -s https://api.telegram.org/bot<TOKEN>/getUpdates` —
   javobdagi `"chat":{"id":-100...}` → `TELEGRAM_CHAT_ID`.
4. `sudo bash deploy/monitoring/up.sh`.
5. Sinov xabari:

   ```bash
   docker compose -f deploy/monitoring/docker-compose.monitoring.yml exec alertmanager \
     amtool alert add SinovOgohlantirish severity=warning \
       --annotation=summary="Sinov xabari" --annotation=description="Monitoring ishlayapti" \
       --alertmanager.url=http://127.0.0.1:19093
   ```

Token va chat ID faqat serverdagi `.env` da turadi — repoga hech qachon yozilmaydi.

## 2. Grafana'ni ochish

**Subdomen (tavsiya):** `deploy/monitoring/nginx/grafana-subdomain.conf` ning
boshidagi 5 qadam (DNS `monitor.cam`, nginx, certbot, ixtiyoriy basic auth).
`.env`: `GRAFANA_ROOT_URL=https://monitor.cam.fermi.uz/`, `GRAFANA_COOKIE_SECURE=true`.

**Subpath:** `https://cam.fermi.uz/grafana/` — `deploy/monitoring/nginx/grafana-subpath.conf`
ni cam.fermi.uz server blokiga `include` qiling; `.env`:
`GRAFANA_ROOT_URL=https://cam.fermi.uz/grafana/`, `GRAFANA_SERVE_FROM_SUB_PATH=true`.

**Himoya:** Grafana o'z logini (`GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD`),
ro'yxatdan o'tish va anonim kirish o'chirilgan. Qo'shimcha: nginx `auth_basic`
va/yoki `allow 192.168.0.0/16; deny all;` (snippetdagi izohlarni yoqing).
Operatorlar uchun Grafana'da *Viewer* roli bilan alohida foydalanuvchi oching
(Administration → Users) — admin parolini bermang.

**Prometheus / Alertmanager UI** (faqat administrator):

```bash
ssh -p 2222 -L 19090:127.0.0.1:19090 -L 19093:127.0.0.1:19093 admin_root@87.192.230.208
# brauzerda: http://127.0.0.1:19090/alerts , http://127.0.0.1:19093
```

## 3. Dashboard: "Situatsion Markaz"

`grafana/dashboards/situatsion-markaz.json` — Grafana ochilganda bosh sahifa.

- **Umumiy holat** — API ishlayaptimi, faol kameralar, tarmoqda/tasvir bor ulushi,
  ko'rib chiqilmagan va muddati o'tgan hodisalar, bugun kelganlar, eng so'nggi kelish.
- **Kameralar** — faol / tarmoqda / tasvir bor dinamikasi, oflayn ulushi.
- **Hodisalar** — oxirgi soatdagi signallar modul va og'irlik bo'yicha, ochiq navbat.
- **Davomat** — bugungi yozuvlar holat va manba (kamera, turniket, qo'lda) bo'yicha.
- **Turniket va bildirishnomalar** — ruxsat berilgan/rad etilgan, yuborilgan/xato xabarlar.
- **AI** — har modulning ishlash davomiyligi, kechikish, xatolar, slotlar, video oqimlar.
- **Server resurslari** — CPU, RAM, disk, tarmoq, disk I/O, har konteyner xotirasi va CPU.

Dashboard fayldan yuklanadi va Grafana ichida saqlanmaydi. O'zgartirish:
Grafana'da tahrirlang → *Export → JSON* → faylga yozing → commit → deploy.

## 4. Ogohlantirishlar

`prometheus/rules/camera.rules.yml`:

| Ogohlantirish | Shart | Daraja |
|---------------|-------|--------|
| ApiIshlamayapti | `/metrics` 2 daqiqa o'qilmaydi | critical |
| MetrikaBazadanOlinmayapti | API bazadan ko'rsatkich ololmaydi (5 daq.) | warning |
| KameralarOflayn20Foizdan | faol kameralarning >20% i oflayn (10 daq.) | warning |
| KameralarOflaynYarmidan | >50% oflayn (5 daq.) | critical |
| KameralarTasvirsiz | tarmoqdagi kameralarning >30% i kadr bermaydi (20 daq.) | warning |
| MuddatiOtganHodisalarKopaydi | SLA muddati o'tgan ochiq hodisa >10 (15 daq.) | warning |
| KoribChiqilmaganHodisalarKop | 'yangi' hodisa >200 (30 daq.) | warning |
| IshVaqtidaDavomatYozilmayapti | dush–shanba 10:00–17:00 (Toshkent) oralig'ida bugun birorta ham kelish yo'q, 30 daq. ("dam_olish" kuni emas) | critical |
| AiSweepKechikmoqda | AI moduli intervalidan ancha kechikmoqda (15 daq.) | warning |
| XabarlarYuborilmayapti | oxirgi soatda >10 xabar xato bilan | warning |
| DiskToldi85Foiz / DiskToldi95Foiz | disk to'lishi | warning / critical |
| XotiraYuqori | RAM >90% (10 daq.) | warning |
| ProtsessorYuqori | CPU >90% (15 daq.) | warning |
| KonteynerXotiraChegarasida | konteyner `mem_limit` ning >90% i | warning |
| NodeExporterIshlamayapti / CadvisorIshlamayapti | eksporter to'xtagan | warning |

Critical — har soatda, warning — har 4 soatda (`ALERT_REPEAT_INTERVAL`) takrorlanadi,
hal bo'lganda "HAL BO'LDI" xabari keladi. API o'chganda uning oqibatlari
(davomat, AI) alohida yuborilmaydi (Alertmanager inhibit qoidalari).

Chegarani o'zgartirish: faylni tahrirlang, commit/deploy (yoki serverda
`curl -X POST http://127.0.0.1:19090/-/reload`). CI (`tests/test_ops_monitoring_config.py`)
qoidalar faqat mavjud ko'rsatkichlardan foydalanishini tekshiradi.

## 5. API ko'rsatkichlari (`/metrics`)

`camera-api/app/routers/metrics.py`. Bazadan hisoblanadi va 15 soniya keshlanadi:

| Ko'rsatkich | Ma'nosi |
|-------------|---------|
| `sm_cameras_total`, `sm_cameras{status}` | kameralar soni (holat bo'yicha) |
| `sm_cameras_active` / `sm_cameras_reachable` / `sm_cameras_video_flowing` | faol / tarmoqda / tasvir bor |
| `sm_events_last_hour{module_code,module,severity}` | oxirgi soatdagi hodisalar (sinov rejimisiz) |
| `sm_events_open{status}`, `sm_events_unreviewed`, `sm_events_overdue` | ochiq navbat, SLA o'tganlar |
| `sm_attendance_records_today{status,source}` | bugungi davomat |
| `sm_attendance_last_check_in_timestamp_seconds` | bugungi eng kech kelish vaqti |
| `sm_access_events_last_hour{granted,direction}` | turniket |
| `sm_notifications_last_hour{channel,status}` | Telegram/SMS xabarlari |
| `sm_ai_sweep_*{name,tier}`, `sm_ai_slots`, `sm_ai_face_inference_gate`, `sm_ai_stream_readers`, `sm_ai_entrance_watchers`, `sm_camera_health_sweep` | AI ish holati (ai-worker'dan Redis orqali) |
| `sm_app_info{version,role,system}` | joylangan commit (`APP_VERSION`) |
| `sm_metrics_collect_success`, `sm_metrics_collect_duration_seconds` | ko'rsatkichlarni yig'ish holati |
| `process_*`, `python_gc_*` | uvicorn jarayoni (standart) |

**Himoya.** `METRICS_ENABLED=false` — endpoint 404. `METRICS_TOKEN` bo'sh bo'lsa
faqat ichki manzillar (127.0.0.0/8, 10/8, 172.16/12, 192.168/16) — nginx orqali
kelgan tashqi foydalanuvchi `X-Forwarded-For` bo'yicha rad etiladi; nginx esa
`/metrics` ni umuman o'tkazmaydi. Token qo'yish (tavsiya, agar serverda
begona konteynerlar bo'lsa):

```bash
echo "METRICS_TOKEN=$(openssl rand -hex 32)" | sudo tee -a /opt/camera/camera-api/.env
cd /opt/camera/camera-api && sudo docker compose up -d --force-recreate api ai-worker
sudo bash /opt/camera/deploy/monitoring/up.sh   # tokenni Prometheus'ga beradi
```

Qo'lda tekshirish: `curl -s http://127.0.0.1:18080/metrics | grep ^sm_`.

## 6. Xizmat ko'rsatish

```bash
C="docker compose -f /opt/camera/deploy/monitoring/docker-compose.monitoring.yml"
$C ps                       # holat
$C logs -f alertmanager     # Telegram xatolari shu yerda
$C restart grafana
$C down                     # to'xtatish (ma'lumotlar volume'larda qoladi)
```

**Versiyalarni yangilash.** Obrazlar qotirilgan (`prom/prometheus:v3.14.0`,
`prom/alertmanager:v0.34.1`, `grafana/grafana:13.2.2`, `prom/node-exporter:v1.12.1`,
`ghcr.io/google/cadvisor:v0.60.6`). Yangi versiyani release notes bo'yicha
tekshiring, `docker-compose.monitoring.yml` dagi tegni o'zgartiring va `up.sh`
ni ishga tushiring. Asosiy stekdagi (`camera-api/docker-compose.yml`) MinIO
(`quay.io/minio/minio`, MinIO Docker Hub'da yangi obraz chiqarmaydi), `mc` va
MediaMTX ham qotirilgan; MediaMTX versiyasi `deploy/Dockerfile.mediamtx` bilan
bir xil bo'lishi shart (CI tekshiradi).

**Disk.** Prometheus 30 kun yoki 20 GB (`PROMETHEUS_RETENTION_*`) saqlaydi.
Volume'lar: `camera-monitoring_prometheus_data`, `..._grafana_data`, `..._alertmanager_data`.
