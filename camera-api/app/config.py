from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    port: int = 8080
    database_url: str
    # SQLAlchemy's own defaults (pool_size=5, max_overflow=10 -> 15 total)
    # were sized for a handful of concurrent requests, not 14 background AI
    # sweep loops each opening their own per-camera sessions on top of
    # normal admin-panel traffic. Raise these in .env for a production
    # server with many cameras; the defaults here are already well above
    # SQLAlchemy's own for a dev/small deployment.
    db_pool_size: int = 20
    db_max_overflow: int = 40
    db_pool_timeout_seconds: int = 30
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
    # Browser-facing HLS base (mediamtx_hls_base_url) often differs from what
    # the API container can reach (e.g. https://stream.cam.fermi.uz vs
    # http://mediamtx:8888 inside Docker). AI/frame_grabber uses this internal
    # base to rewrite public stream URLs before ffmpeg opens them.
    mediamtx_hls_internal_base_url: str | None = None

    # Parolni tiklash havolasi shu manzil ostida quriladi (frontend'ning
    # ResetPasswordPage marshruti). SMTP sozlanmagan bo'lsa (dev holati),
    # email yuborilmaydi — havola shunchaki strukturaviy logga yoziladi.
    # Background cleanup job (app/jobs/cleanup.py) — how far back AuditLog
    # rows are kept, and how often the sweep runs. No Celery/cron here: a
    # plain asyncio loop started from main.py's lifespan is enough for a
    # single periodic sweep.
    audit_log_retention_days: int = 90
    # AI-detected incidents (app/models/event.py) — older rows are purged
    # by app/jobs/cleanup.py on the same schedule as audit logs.
    event_retention_days: int = 180
    cleanup_interval_hours: int = 24

    # Camera reachability sweep (app/jobs/camera_health.py) — how often every
    # camera marked "faol" gets a lightweight TCP reachability check, and how
    # long a successful check stays "fresh" before a camera reads as offline
    # again. Freshness should be a few multiples of the interval so one
    # missed/slow sweep tick doesn't immediately flip a healthy camera to
    # "offline".
    camera_health_interval_seconds: int = 30
    camera_health_freshness_seconds: int = 90
    # Parallel TCP checks during camera_health sweep (300 cameras @ 48 ≈ 19 waves × 3s)
    camera_health_concurrency: int = 32
    # How long a faol camera must stay unreachable before raising an admin
    # alert (AuditLog entry + structured WARNING log). Zero disables alerts.
    camera_offline_alert_minutes: int = 5

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
    # Camera.is_entrance cameras get a multi-frame burst instead of one
    # sampled frame — see app/models/camera.py's is_entrance docstring and
    # app/jobs/attendance_ai.py's run_attendance_ai_sweep_once. Mirrors
    # app/services/frame_grabber.py's grab_frame_burst signature/defaults
    # used by vision_ai.py's sleep confirmation, though attendance doesn't
    # need majority voting — ANY frame matching a person is enough to
    # credit them (upsert_attendance_from_recognition is idempotent per
    # person per day), since the goal is maximizing recall for someone
    # only briefly in frame, not filtering a noisy classification.
    attendance_entrance_burst_frame_count: int = 3
    attendance_entrance_burst_gap_seconds: float = 1.0

    # TT kriteriya 20 ("Talabaning uxlab qolishi") — app/jobs/vision_ai.py.
    # Same camera pool as attendance_ai (faol + reachable), separate sweep
    # since it checks EVERY face in frame (attendance only matches the
    # single largest face). sleep_dedup_minutes avoids re-raising an Event
    # every tick for a person who stays asleep across many sweeps.
    vision_ai_interval_seconds: int = 30
    sleep_dedup_minutes: int = 15
    # PERCLOS-style multi-frame confirmation (app/jobs/vision_ai.py) —
    # replaces the earlier fixed 2-frame "asleep in both" check with a
    # majority vote across a short burst, on the same premise (a blink
    # doesn't last multiple seconds) but statistically sturdier: one noisy
    # frame out of 4 no longer flips the result either way. Frame count is
    # a real cost (each is an InsightFace inference call — see
    # face_recognition_inference_concurrency), so raising it trades
    # accuracy for load; 4 frames over ~3s was picked as a reasonable
    # balance, not measured against labeled footage.
    sleep_confirmation_frame_count: int = 4
    sleep_confirmation_gap_seconds: float = 1.0
    sleep_confirmation_majority_ratio: float = 0.75

    # TT kriteriya 23 ("Yong'in / tutun aniqlash") — app/jobs/fire_ai.py.
    # Its own interval (not shared with vision_ai_interval_seconds) since
    # each fire sweep tick costs two ffmpeg frame grabs per camera
    # (app/services/frame_grabber.py's grab_frame_pair, ~1s apart) instead
    # of one. fire_dedup_minutes is deliberately shorter than
    # sleep_dedup_minutes — a sustained fire is worth re-confirming sooner
    # than a sustained nap.
    fire_ai_interval_seconds: int = 30
    fire_dedup_minutes: int = 5

    # TT kriteriya 22 ("O'qituvchining darsga aniq kelishi") —
    # app/jobs/teacher_punctuality_ai.py. Only affects LessonSession rows
    # that have teacher_id/camera_id/scheduled_start_time set (no
    # scheduling UI exists yet to populate these, so this is a no-op
    # until a schedule is actually entered). grace_minutes is how long
    # after scheduled_start_time a teacher has to be seen before the
    # check runs and (if not seen) raises an Event.
    teacher_punctuality_interval_seconds: int = 60
    teacher_punctuality_grace_minutes: int = 10

    # TT kriteriya 1 ("Notanish/begona shaxsni aniqlash") —
    # app/jobs/unauthorized_person_ai.py.
    unauthorized_person_ai_interval_seconds: int = 30
    unauthorized_person_dedup_minutes: int = 5

    # TT kriteriya 5 ("Olomon zichligi anomaliyasi") —
    # app/jobs/crowd_density_ai.py. baseline_window/min_samples control the
    # per-camera rolling face-count history; spike_multiplier/min_absolute
    # control what counts as an anomaly relative to that baseline.
    crowd_ai_interval_seconds: int = 30
    crowd_dedup_minutes: int = 10
    crowd_baseline_window: int = 20
    crowd_baseline_min_samples: int = 5
    crowd_spike_multiplier: float = 2.0
    crowd_min_absolute: int = 4

    # TT kriteriya 4 ("Egasiz qoldirilgan buyum") —
    # app/jobs/abandoned_object_ai.py. min_area/max_area_fraction filter
    # obviously-wrong blob sizes (noise vs. a lighting-change covering
    # most of the frame); match_distance_px is how close two ticks'
    # largest blob centroids must be to count as "the same" static
    # region; min_consecutive_ticks approximates how long it must stay
    # put (in sweep ticks, not exact wall-clock — see module docstring).
    abandoned_object_ai_interval_seconds: int = 30
    abandoned_object_dedup_minutes: int = 15
    abandoned_object_min_area: int = 800
    abandoned_object_max_area_fraction: float = 0.5
    abandoned_object_match_distance_px: float = 40.0
    abandoned_object_min_consecutive_ticks: int = 4
    # MOG2's default AUTOMATIC learning rate adapts fast enough (tuned for
    # real ~30fps video) that a genuinely static new object gets absorbed
    # into the background model after just 1-2 sweep ticks when ticks are
    # ~30s apart — found from real testing (see
    # tests/test_abandoned_object_ai.py), not assumed. An explicit, much
    # lower learning rate keeps a new static region classified as
    # foreground for several ticks, which is what min_consecutive_ticks
    # above actually needs to be able to observe.
    abandoned_object_learning_rate: float = 0.02

    # TT kriteriya 17 ("Tartib-intizom buzilishi") —
    # app/jobs/disorder_ai.py. min_absolute_magnitude/spike_multiplier are
    # calibrated against real Farneback optical-flow numbers (see the
    # module docstring): identical frames read ~0.0003-0.0006, a 5-10px
    # shift reads 5-10.
    disorder_ai_interval_seconds: int = 30
    disorder_dedup_minutes: int = 10
    disorder_baseline_window: int = 20
    disorder_baseline_min_samples: int = 5
    disorder_spike_multiplier: float = 3.0
    disorder_min_absolute_magnitude: float = 1.5

    # YOLOv8 object detection (app/services/object_detection.py) — shared
    # by TT kriteriya 16 (telefon) and 25 (transport). See
    # face_recognition_gpu_enabled/inference_concurrency for the same
    # pattern applied to InsightFace; this is the object-detection
    # equivalent, a separate knob since the two models have independent
    # resource costs.
    object_detection_model_path: str = "yolov8n.pt"
    object_detection_gpu_enabled: bool = False
    object_detection_inference_concurrency: int = 2

    # TT kriteriya 16 ("Imtihonda telefondan foydalanish") —
    # app/jobs/phone_ai.py.
    phone_ai_interval_seconds: int = 30
    phone_dedup_minutes: int = 10
    phone_detection_confidence: float = 0.5

    # TT kriteriya 25 ("Hovlida transport harakati") —
    # app/jobs/vehicle_ai.py.
    vehicle_ai_interval_seconds: int = 30
    vehicle_dedup_minutes: int = 10
    vehicle_detection_confidence: float = 0.5

    # mediapipe Pose Landmarker (app/services/pose_detection.py) — shared
    # by TT kriteriya 24 (yiqilish), 2 (taqiqlangan zona), 21 (o'qituvchi
    # faolligi). Same pattern as object_detection_*/face_recognition_*
    # above, a separate knob since each model has independent resource
    # costs.
    pose_detection_model_path: str = "pose_landmarker_lite.task"
    pose_detection_inference_concurrency: int = 2
    pose_detection_max_poses: int = 5

    # TT kriteriya 24 ("Yiqilib tushish") — app/jobs/fall_ai.py /
    # app/services/fall_detection.py. dedup_minutes is deliberately
    # shorter than other criteria's — a real fall is safety-critical and
    # worth re-confirming sooner than, say, a sustained sleep Event.
    fall_ai_interval_seconds: int = 30
    fall_dedup_minutes: int = 5
    fall_min_landmark_visibility: float = 0.5
    fall_torso_angle_threshold: float = 60.0
    fall_aspect_ratio_threshold: float = 1.4

    # TT kriteriya 10 ("Oq xalat kiyilganligi") — app/jobs/dress_code_ai.py
    # / app/services/coat_detection.py. Classical HSV heuristic, not a
    # trained classifier — see that module's docstring for the honest
    # scope limits. S/V thresholds are OpenCV's 0-255 HSV ranges.
    coat_ai_interval_seconds: int = 45
    dress_code_ai_interval_seconds: int = 45
    coat_dedup_minutes: int = 30
    coat_min_landmark_visibility: float = 0.5
    coat_torso_extension_factor: float = 0.6
    coat_white_saturation_max: int = 60
    coat_white_value_min: int = 170
    coat_white_fraction_threshold: float = 0.60

    # TT kriteriya 11 ("Bosh kiyim (kalpakcha) borligi") —
    # app/jobs/dress_code_ai.py / app/services/head_covering_detection.py.
    # Classical color-uniformity heuristic — see that module's docstring.
    head_covering_min_landmark_visibility: float = 0.5
    head_covering_width_factor: float = 0.9
    head_covering_height_factor: float = 1.1
    head_covering_top_margin_factor: float = 0.25
    head_covering_uniformity_threshold: float = 0.55

    # TT kriteriya 2 ("Taqiqlangan zonaga kirish") —
    # app/jobs/zone_entry_ai.py / app/services/zone_detection.py.
    zone_ai_interval_seconds: int = 30
    zone_dedup_minutes: int = 5
    zone_min_landmark_visibility: float = 0.5

    # TT kriteriya 19 ("Talabaning darsga diqqati") va 21 ("O'qituvchi
    # faolligi") — app/jobs/lesson_quality_ai.py. lesson_duration_minutes
    # defines the "active window" after scheduled_start_time during which
    # both scores are sampled — no LessonSession end-time field exists,
    # so this is a configured assumption (typical class length), not
    # read from real schedule data.
    lesson_quality_ai_interval_seconds: int = 30
    lesson_duration_minutes: int = 90
    attention_score_frontal: float = 100.0
    attention_score_not_frontal: float = 40.0
    attention_score_phone_visible: float = 20.0
    teacher_activity_min_visibility: float = 0.5
    # Scales average per-landmark displacement (normalized 0-1 frame
    # coordinates, ~1s apart) into a 0-100 score. Not calibrated against
    # real classroom footage — chosen so a small (~0.1 average landmark
    # movement) reads as a mid-range score, an untuned starting point.
    teacher_activity_scale: float = 500.0

    # TT kriteriya 14 ("Jang/nizolashish holati") — app/jobs/fight_ai.py.
    # THE LEAST RELIABLE criterion in this system — see that module's
    # docstring. Reuses app/jobs/disorder_ai.py's motion-spike baseline
    # logic under a namespaced key, plus its own proximity check.
    fight_ai_interval_seconds: int = 30
    fight_dedup_minutes: int = 5
    fight_min_landmark_visibility: float = 0.5
    fight_proximity_threshold: float = 0.12
    fight_spike_multiplier: float = 4.0
    fight_min_absolute_magnitude: float = 2.0

    # Max cameras processed concurrently ACROSS ALL AI sweep modules.
    # app/jobs/sweep_concurrency.py — every module shares this one cap so
    # parallel scheduler ticks can't spawn (module_count × N) pipelines.
    ai_global_sweep_concurrency: int = 48

    # Deprecated alias kept for older .env files — prefer
    # AI_GLOBAL_SWEEP_CONCURRENCY on production servers.
    ai_sweep_camera_concurrency: int = 8

    # Seconds between each AI sweep loop's FIRST tick at startup (see
    # app/main.py's lifespan) — all 16 loops used to fire their first
    # sweep in the same instant, all contending for the same camera/
    # inference semaphores and DB connections at once, then falling back
    # into sync every ~30s after. Staggering only the START time smooths
    # that initial burst; each loop's own steady-state interval (still set
    # independently per job, e.g. attendance_ai_interval_seconds) is
    # unchanged.
    ai_loop_stagger_seconds: float = 2.0

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

    # Unified face sweep (app/jobs/unified_face_sweep.py) — one frame grab +
    # one face-detect pass per camera tick, feeding attendance/crowd/unauthorized/
    # sleep modules instead of four independent loops each re-grabbing/re-detecting.
    # When true, the four individual face-based loops are NOT started.
    unified_face_sweep_enabled: bool = True
    unified_face_sweep_interval_seconds: int = 30

    # Optional Redis — shared rate limits (slowapi) + WebSocket pub/sub fan-out
    # across multiple API workers/instances. Unset = in-memory (single instance).
    redis_url: str = ""

    # Central AI scheduler (app/jobs/ai_scheduler.py) — when true, individual
    # per-module asyncio loops are NOT started; one coordinator dispatches sweeps.
    ai_scheduler_enabled: bool = False
    ai_scheduler_poll_seconds: int = 5

    # GPU batch inference caps — detect_faces_batch / detect_objects_batch chunk size.
    face_recognition_batch_size: int = 4
    object_detection_batch_size: int = 4

    # FAISS exact IP search when enrolled count >= this threshold (requires faiss-cpu).
    face_match_faiss_min_size: int = 10_000
    # Live detection (public.py) reloads embeddings from DB after this TTL.
    candidate_matrix_cache_ttl_seconds: int = 30
    # AI sweep loops share one matrix per TTL — avoids 10k+ row reads every tick.
    candidate_matrix_sweep_cache_ttl_seconds: int = 300

    # Admin dashboard resource alerts (app/routers/system.py).
    resource_alert_cpu_percent: int = 85
    resource_alert_ram_percent: int = 85
    resource_alert_disk_percent: int = 90
    resource_alert_ffmpeg_count: int = 280

    # MediaMTX horizontal sharding — comma-separated URLs, equal length pairs.
    # Empty = single MEDIAMTX_API_URL / MEDIAMTX_HLS_BASE_URL.
    mediamtx_shard_api_urls: str = ""
    mediamtx_shard_hls_base_urls: str = ""
    # Parallel to mediamtx_shard_hls_base_urls — docker-internal HLS bases for ffmpeg
    # (e.g. http://mediamtx-0:8888,http://mediamtx-1:8888,http://mediamtx-2:8888).
    mediamtx_shard_hls_internal_base_urls: str = ""

    # TT kriteriya 12 — ID-badge evristikasi
    badge_ai_interval_seconds: int = 45
    badge_dedup_minutes: int = 30
    badge_min_landmark_visibility: float = 0.5
    badge_chest_width_factor: float = 0.35
    badge_chest_height_factor: float = 0.45
    badge_min_rect_fraction: float = 0.02
    badge_max_rect_fraction: float = 0.25
    badge_min_aspect: float = 0.5
    badge_max_aspect: float = 2.5

    # TT kriteriya 13 — SIZ
    ppe_ai_interval_seconds: int = 45
    ppe_dedup_minutes: int = 20
    ppe_detection_model_path: str = ""
    ppe_detection_confidence: float = 0.5
    ppe_mask_saturation_min: int = 40
    ppe_mask_value_min: int = 40
    ppe_mask_fraction_threshold: float = 0.15

    # TT kriteriya 15 — chekish postura
    smoking_ai_interval_seconds: int = 45
    smoking_dedup_minutes: int = 15
    smoking_min_landmark_visibility: float = 0.5
    smoking_wrist_mouth_distance: float = 0.12

    # TT kriteriya 18 — talaba dress code
    student_uniform_ai_interval_seconds: int = 45
    student_uniform_dedup_minutes: int = 30
    student_uniform_min_landmark_visibility: float = 0.5
    student_uniform_contrast_min: float = 15.0

    frontend_base_url: str = "http://localhost:5173"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@fjsti.local"
    smtp_use_tls: bool = True


settings = Settings()
