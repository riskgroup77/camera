# GPU + MediaMTX 3-shard — bosqichma-bosqich o‘rnatish

## Nima qo‘shiladi

| Bosqich | Natija |
|---------|--------|
| **1. GPU Docker** | InsightFace + YOLO CUDA orqali (2–5× tezroq AI) |
| **2. MediaMTX 3-shard** | 300 kamera ~100+100+100 ta node ga bo‘linadi |
| **3. Nginx /s0 /s1 /s2** | Bitta domen `stream.cam.fermi.uz`, path orqali shard |

## Talablar (server)

- Docker Compose v2.23+ (`!override` uchun)
- **GPU (ixtiyoriy lekin tavsiya):** NVIDIA driver + [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
- Nginx (allaqachon o‘rnatilgan — `cam-fermi-stream.conf` yangilanadi)

## Avtomatik deploy (tavsiya)

Lokal mashinadan:

```bash
python scripts/deploy_scale_infra.py
```

Serverda qo‘lda:

```bash
cd /opt/camera
git pull origin main
sudo bash deploy/setup-scale-infra.sh
```

## Qo‘lda bosqichlar

### 1) GPU tekshiruv

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

GPU yo‘q bo‘lsa — CPU image ishlatiladi (production scale env baribir yaxshiroq).

### 2) Compose fayllar

```bash
cd /opt/camera/camera-api
cp ../deploy/docker-compose.mediamtx-shard.yml .
cp ../deploy/docker-compose.gpu.yml .   # faqat GPU bo‘lsa
cp ../deploy/docker-compose.override.yml .
```

Ishga tushirish:

```bash
# GPU bilan:
docker compose -f docker-compose.yml -f docker-compose.override.yml \
  -f docker-compose.mediamtx-shard.yml -f docker-compose.gpu.yml up -d --build

# GPU siz:
docker compose -f docker-compose.yml -f docker-compose.override.yml \
  -f docker-compose.mediamtx-shard.yml up -d --build
```

### 3) `.env` shard kalitlari

`deploy/env.production.scale` dan merge (yoki qo‘lda):

```env
MEDIAMTX_SHARD_API_URLS=http://mediamtx-0:9997,http://mediamtx-1:9997,http://mediamtx-2:9997
MEDIAMTX_SHARD_HLS_BASE_URLS=https://stream.cam.fermi.uz/s0,https://stream.cam.fermi.uz/s1,https://stream.cam.fermi.uz/s2
MEDIAMTX_SHARD_HLS_INTERNAL_BASE_URLS=http://mediamtx-0:8888,http://mediamtx-1:8888,http://mediamtx-2:8888
```

### 4) Nginx

```bash
sudo cp /opt/camera/deploy/nginx/cam-fermi-stream.conf /etc/nginx/sites-available/stream.cam.fermi.uz.conf
sudo nginx -t && sudo systemctl reload nginx
```

### 5) Tekshiruv

```bash
curl -s http://127.0.0.1:18080/health
curl -s http://127.0.0.1:9997/v3/paths/list | head
curl -s http://127.0.0.1:9998/v3/paths/list | head
curl -s http://127.0.0.1:9999/v3/paths/list | head
docker logs camera-api-api-1 2>&1 | grep -i gpu
```

API qayta ishga tushganda barcha kameralar yangi shard URL bilan qayta ro‘yxatdan o‘tadi (`stream_sync`).

## Portlar (host)

| Shard | HLS | API | RTSP |
|-------|-----|-----|------|
| 0 | 8888 | 9997 | 8554 |
| 1 | 8889 | 9998 | 8555 |
| 2 | 8890 | 9999 | 8556 |

## Orqaga qaytish (bitta MediaMTX)

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml \
  -f docker-compose.mediamtx.yml up -d
# .env dan MEDIAMTX_SHARD_* qatorlarini olib tashlang
```
