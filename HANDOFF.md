# Loyihani topshirish

## Tuzilma
- `camera-api/` — FastAPI + PostgreSQL + Redis + MinIO, AI (InsightFace) `ai-worker` jarayonida.
- `src/` — React + TypeScript + Tailwind frontend.
- `deploy/` — docker-compose qatlamlari va nginx nusxalari.

## Lokal ishga tushirish
1. PostgreSQL'da bo'sh baza yarating, `camera-api/.env` ga `DATABASE_URL`, `JWT_SECRET`, `ENCRYPTION_KEY`, `AI_ROLE=api` yozing.
2. `cd camera-api && alembic upgrade head`
3. Sintetik ma'lumot (haqiqiy shaxs yo'q): `PYTHONPATH=. python scripts/demo_data.py`
4. `uvicorn app.main:app --port 8010`; frontend: `VITE_API_BASE_URL=http://localhost:8010 npx vite`

## Testlar
- Frontend: `npx tsc -b && npx vitest run`
- Backend: `cd camera-api && TEST_DATABASE_URL=... pytest -q --ignore=tests/test_health.py --ignore=tests/test_pose_detection.py`
- Bir vaqtda faqat BITTA pytest ishlating (umumiy test bazasi).

## Deploy (server kirish huquqini loyiha egasidan oling)
- Backend: serverda `git pull`, `docker compose <qatlamlar> build api ai-worker` va `up -d --no-deps api ai-worker` (migratsiya avtomatik).
- Frontend: `npx vite build --assetsDir app`, `dist/` ni web ildizga rsync (`fonts/` ni chiqarib), `index.html` oxirida almashtiriladi.
- Boshqa loyihalarning konteynerlari va nginx'ga tegmang.

## Keyingi ishlar
- Sahifalarni boyitish davomi: Shaxs sahifasi, Tuzilma, Hodisalar, Xarita, Kameralar, Tizim holati.
- Nazorat konsolidagi "Kameralar" paneli ba'zan "Kamera yo'q" deydi — tekshirish.
- Yumshoq yuz mosligi o'zgarishining (ikkinchi tasdiq: boshqa kamera yoki 10 s) ta'sirini ish kunida o'lchash.
- Admin 2FA ixtiyoriy (`ADMIN_2FA_REQUIRED`), hisobot paroli alohida.
