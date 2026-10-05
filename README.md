# camera — Situatsion Markaz

[![CI](https://github.com/aiziyrak-coder/camera/actions/workflows/ci.yml/badge.svg)](https://github.com/aiziyrak-coder/camera/actions/workflows/ci.yml)
[![Deploy](https://github.com/aiziyrak-coder/camera/actions/workflows/deploy.yml/badge.svg)](https://github.com/aiziyrak-coder/camera/actions/workflows/deploy.yml)

Kamera monitoring tizimi — React + TypeScript frontend va FastAPI backend (`camera-api`).

## Loyiha tuzilmasi

- `src/` — React frontend (Vite, Tailwind CSS); `public/` — statik fayllar, PWA (manifest, service worker, ikonlar)
- `camera-api/` — FastAPI backend (yuz tanish, davomat, yong'in aniqlash va boshqalar)
- `deploy/` — production server skriptlari, nginx, Docker override'lari
- `deploy/monitoring/` — Prometheus + Grafana + Alertmanager (Telegram)
- `.github/workflows/` — CI (tekshiruv) va CD (serverga deploy)
- `scripts/` — qo'lda ishlatiladigan yordamchi skriptlar

## Ishga tushirish

### Frontend

```bash
npm install
npm run dev
```

Tekshiruvlar: `npm run lint`, `npm test`, `npm run build`.

### Backend

```bash
cd camera-api
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env     # sozlamalarni to'ldiring
uvicorn app.main:app --reload
```

Testlar: `python -m pytest -q` (PostgreSQL kerak; `TEST_DATABASE_URL` alohida baza).

## CI/CD

- **CI** (`.github/workflows/ci.yml`) — har push va PR'da: frontend (oxlint,
  vitest, `tsc` + `vite build`) va backend (Python 3.14, PostgreSQL 17, Redis,
  MinIO, MediaMTX; toza bazada `alembic upgrade head`, pytest, API smoke-test
  `/health` va `/metrics`).
- **Deploy** (`.github/workflows/deploy.yml`) — `main` dagi CI muvaffaqiyatli
  tugagach serverga SSH orqali kirib `deploy/server-pull.sh --ref <commit>` ni
  ishga tushiradi va `HEALTHCHECK_URL` ni tekshiradi. Qo'lda ham ishga tushiriladi
  (Actions → Deploy → Run workflow). Kerakli secrets va server sozlamasi:
  [`deploy/README.md`](deploy/README.md#github-actions-orqali-deploy-cicd).

## Monitoring

Prometheus `/metrics` (API), server va konteyner ko'rsatkichlarini yig'adi,
Grafana'da "Situatsion Markaz" dashboardi, muammolar Telegram'ga keladi:
[`deploy/monitoring/README.md`](deploy/monitoring/README.md).

## Mobil ilova (PWA)

Sayt telefon va kompyuterga ilova sifatida o'rnatiladi: Chrome/Edge — manzil
satridagi "O'rnatish" belgisi yoki menyu → *Ilovani o'rnatish*; iPhone (Safari) —
*Ulashish* → *Bosh ekranga qo'shish*. Service worker (`public/sw.js`) faqat
production build'da va HTTPS'da yoqiladi; ilova qobig'i va statik fayllarni
keshlaydi, API, WebSocket va jonli videoni hech qachon keshlamaydi. Ikonlarni
qayta yaratish: `camera-api/.venv/Scripts/python scripts/generate_pwa_icons.py public/icons`.
