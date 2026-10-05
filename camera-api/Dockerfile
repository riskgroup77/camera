# syntax=docker/dockerfile:1
# CPU obrazi (GPU'li xost — Dockerfile.gpu, deploy/docker-compose.gpu.yml).
#
# Deploy tezligi uchun:
#   * asos obraz digest bilan qotirilgan — ":3.14-slim" yangilansa, butun
#     kesh (pip qatlami ham) bekor bo'lib, har deployda ~25 daqiqa qayta
#     yig'ilardi (2026-10-05 deployi shunday bo'ldi). Yangilash: digest'ni
#     `docker buildx imagetools inspect python:3.14-slim` dan oling;
#   * torch CPU varianti — PyPI'dagi torch CUDA bilan keladi (nvidia-* va
#     triton ~4.5 GB), GPU'siz serverda ular hech qachon ishlatilmaydi;
#   * pip keshi BuildKit cache mount'da — qatlam qayta yig'ilsa ham
#     paketlar internetdan qayta yuklanmaydi.

FROM python:3.14-slim@sha256:c3e521df8b2b498a7a682e7e18676771cb80c6b75b8699af886b2d554ce40151

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ffmpeg (ffprobe) is required by app/services/connectivity.py to verify
# RTSP streams — without it the connectivity test silently degrades to a
# TCP-only check (see the shutil.which("ffprobe") fallback there).
#
# libgl1/libglib2.0-0 are opencv-python-headless's actual runtime deps
# despite the "headless" name (it still dlopen()s libGL/glib at import
# time); libgomp1 is onnxruntime's OpenMP runtime. Without these,
# `import cv2` / `import onnxruntime` raises ImportError: libGL.so.1 (or
# libgomp.so.1) not found the first time app/services/face_recognition.py
# is imported — python:slim's minimal Debian base doesn't ship them.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# ultralytics torch'ni talab qiladi; versiya CI bilan bir xil bo'lsin
# (.github/workflows/ci.yml). constraints — requirements o'rnatilayotganda
# pip PyPI'dagi CUDA torch'ga almashtirib yubormasin.
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
ARG TORCH_VERSION=2.14.1+cpu
ARG TORCHVISION_VERSION=0.29.1+cpu

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    printf 'torch==%s\ntorchvision==%s\n' "${TORCH_VERSION}" "${TORCHVISION_VERSION}" > /tmp/constraints.txt \
    && pip install --index-url "${TORCH_INDEX}" -c /tmp/constraints.txt torch torchvision \
    && pip install --extra-index-url "${TORCH_INDEX}" -c /tmp/constraints.txt -r requirements.txt \
    && python -c "import importlib.util as u, pathlib, torch; \
assert torch.version.cuda is None, torch.version.cuda; \
site = pathlib.Path(torch.__file__).parents[1]; \
assert not (site / 'nvidia').exists() and u.find_spec('triton') is None, 'CUDA kutubxonalari obrazga tushdi'; \
print('torch', torch.__version__, 'CPU')"

COPY . .

RUN useradd --create-home appuser \
    && mkdir -p /home/appuser/.insightface/models \
    && chown -R appuser:appuser /app /home/appuser/.insightface
USER appuser

# Persists InsightFace ONNX downloads across container rebuilds when mounted
# as a named volume (see docker-compose.yml insightface_models).
VOLUME /home/appuser/.insightface

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health').read()" || exit 1

# WEB_CONCURRENCY controls uvicorn's --workers (plain multi-process mode,
# built into uvicorn itself — no gunicorn needed). Migrations run once,
# before any worker starts, regardless of worker count. Each worker is a
# fully separate process with its own DB connection pool and its own copy
# of app/jobs/cleanup.py's background loop — harmless since cleanup is
# idempotent DELETE queries, and app/seed.py's startup seed is safe under
# concurrent multi-worker execution (see its docstring). Default of 1
# keeps `docker compose up` behavior unchanged unless explicitly scaled up.
ENV WEB_CONCURRENCY=1
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers ${WEB_CONCURRENCY}"]
