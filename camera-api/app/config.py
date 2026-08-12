from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    port: int = 8080
    database_url: str
    jwt_secret: str
    jwt_ttl_hours: int = 12
    cors_origin: str = "http://localhost:5173"
    encryption_key: str

    s3_endpoint_url: str = "http://127.0.0.1:9000"
    # Used only to generate presigned GET URLs (app/storage.py presigned_url()).
    # In Docker Compose, s3_endpoint_url is the internal service name
    # ("http://minio:9000") that the api container uses to reach MinIO for
    # actual uploads — but that hostname means nothing to the browser the
    # presigned URL gets handed to, so presigning needs the host-reachable
    # address instead. Defaults to s3_endpoint_url for local (non-container)
    # dev, where the two are the same address.
    s3_public_endpoint_url: str | None = None
    s3_access_key: str = "camera_minio_admin"
    s3_secret_key: str = "camera_minio_dev_pw"
    s3_bucket: str = "camera-uploads"
    s3_region: str = "us-east-1"

    mediamtx_api_url: str = "http://127.0.0.1:9997"
    mediamtx_hls_base_url: str = "http://127.0.0.1:8888"

    # Parolni tiklash havolasi shu manzil ostida quriladi (frontend'ning
    # ResetPasswordPage marshruti). SMTP sozlanmagan bo'lsa (dev holati),
    # email yuborilmaydi — havola shunchaki strukturaviy logga yoziladi.
    # Background cleanup job (app/jobs/cleanup.py) — how far back AuditLog
    # rows are kept, and how often the sweep runs. No Celery/cron here: a
    # plain asyncio loop started from main.py's lifespan is enough for a
    # single periodic sweep.
    audit_log_retention_days: int = 90
    cleanup_interval_hours: int = 24

    # Camera reachability sweep (app/jobs/camera_health.py) — how often every
    # camera marked "faol" gets a lightweight TCP reachability check, and how
    # long a successful check stays "fresh" before a camera reads as offline
    # again. Freshness should be a few multiples of the interval so one
    # missed/slow sweep tick doesn't immediately flip a healthy camera to
    # "offline".
    camera_health_interval_seconds: int = 30
    camera_health_freshness_seconds: int = 90

    # Automatic attendance via face recognition (app/jobs/attendance_ai.py,
    # app/services/frame_grabber.py) — TT kriteriya 6/7/8, no external AI
    # API: everything runs locally through the same InsightFace model
    # app/services/face_recognition.py already uses for enrollment/compare.
    attendance_ai_interval_seconds: int = 30
    # 1:N identification against the whole enrolled population is a
    # higher false-accept risk than the 1:1 verification used at enrollment
    # time (face_recognition.MATCH_THRESHOLD=0.45) — deliberately stricter.
    attendance_ai_match_threshold: float = 0.55
    # "HH:MM" — a check-in recognized at or after this time is marked
    # kech_keldi instead of keldi.
    attendance_ai_late_cutoff: str = "09:00"
    # TT kriteriya 9 ("Darsdan/ishdan erta ketish") — pure rule-based, no
    # extra model needed: a day's check_out (already tracked as "last seen"
    # by upsert_attendance_from_recognition above) earlier than this is
    # flagged early_leave in GET /api/attendance/{id} — see
    # app/routers/attendance.py's _to_out().
    attendance_early_leave_cutoff: str = "16:00"
    # TT kriteriya 3 ("Notekis/kechki vaqtda kirish") — also pure rule-based:
    # a face-recognized check-in outside [start, end) raises a real Event
    # (module_code=3), same as any other AI-detected incident.
    attendance_off_hours_start: str = "07:00"
    attendance_off_hours_end: str = "20:00"

    # TT kriteriya 20 ("Talabaning uxlab qolishi") — app/jobs/vision_ai.py.
    # Same camera pool as attendance_ai (faol + reachable), separate sweep
    # since it checks EVERY face in frame (attendance only matches the
    # single largest face). sleep_dedup_minutes avoids re-raising an Event
    # every tick for a person who stays asleep across many sweeps.
    vision_ai_interval_seconds: int = 30
    sleep_dedup_minutes: int = 15

    # TT kriteriya 23 ("Yong'in / tutun aniqlash") — app/jobs/fire_ai.py.
    # Its own interval (not shared with vision_ai_interval_seconds) since
    # each fire sweep tick costs two ffmpeg frame grabs per camera
    # (app/services/frame_grabber.py's grab_frame_pair, ~1s apart) instead
    # of one. fire_dedup_minutes is deliberately shorter than
    # sleep_dedup_minutes — a sustained fire is worth re-confirming sooner
    # than a sustained nap.
    fire_ai_interval_seconds: int = 30
    fire_dedup_minutes: int = 5

    # How many cameras each AI sweep loop (attendance_ai/vision_ai/fire_ai)
    # processes concurrently, instead of one at a time. A dev machine with
    # a handful of cameras is fine at the default; a production server
    # with hundreds of cameras should raise this substantially (the real
    # ceiling is the server's CPU/GPU and network capacity for concurrent
    # ffmpeg reads + inference, not this number itself — see
    # face_recognition_inference_concurrency for the inference-specific
    # cap that composes with this one).
    ai_sweep_camera_concurrency: int = 8

    # InsightFace/ONNX inference. face_recognition_gpu_enabled requests
    # CUDAExecutionProvider first (falls back to CPU automatically if the
    # onnxruntime-gpu package/CUDA drivers aren't present — see
    # app/services/face_recognition.py's _get_app()). Only takes effect if
    # onnxruntime-gpu is installed instead of the CPU-only onnxruntime
    # package (see requirements.txt) — installing the package alone does
    # nothing without also flipping this on.
    face_recognition_gpu_enabled: bool = False
    # How many InsightFace calls run concurrently. 2 is a sane CPU default
    # (matches _embed()'s real single-image cost on a dev machine); a GPU
    # deployment should raise this a lot (GPUs are built for exactly this
    # kind of batched/concurrent throughput) — tune against the actual
    # production GPU's memory and measured latency, not blindly maxed out.
    face_recognition_inference_concurrency: int = 2

    # Persistent per-camera frame cache (app/services/stream_cache.py) —
    # replaces spawning a fresh ffmpeg process on every single frame grab
    # with one long-lived ffmpeg reader per camera that continuously
    # decodes frames and keeps only the latest one in memory.
    # stream_cache_max_age_seconds: how stale a cached frame is allowed to
    # be before it's treated as "stream stalled" (same as a failed grab).
    # stream_cache_idle_timeout_seconds: a camera's reader is stopped (and
    # its ffmpeg process killed) after this long with no sweep loop asking
    # for its frames — avoids leaking a live decode pipeline per camera
    # that was deactivated or removed.
    stream_cache_max_age_seconds: float = 15.0
    stream_cache_idle_timeout_seconds: float = 300.0
    stream_cache_capture_fps: float = 2.0

    frontend_base_url: str = "http://localhost:5173"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@fjsti.local"
    smtp_use_tls: bool = True


settings = Settings()
