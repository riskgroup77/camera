# NOTE: this Dockerfile has NOT been build-tested — Docker is not installed
# on the machine this was written on. It follows standard, well-established
# patterns (slim base, non-root user, healthcheck, migrations-then-serve
# entrypoint), but treat the first `docker build` as the real first test.

FROM python:3.14-slim

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
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

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
