from app.schemas.base import CamelModel


class ResourceAlertOut(CamelModel):
    metric: str
    level: str  # "warning" | "critical"
    message: str


class SystemResourcesOut(CamelModel):
    cpu: int
    ram: int
    disk: int
    ffmpeg_process_count: int
    stream_reader_count: int
    alerts: list[ResourceAlertOut]


class GpuStatusOut(CamelModel):
    cuda_available: bool
    onnx_providers: list[str]
    torch_cuda_available: bool
    face_gpu_enabled: bool
    face_gpu_active: bool
    object_gpu_enabled: bool
    object_gpu_active: bool
    recommendation: str


class SchedulerLastTickOut(CamelModel):
    finished_at: str | None
    duration_seconds: float
    modules_ran: int
    critical_ran: int
    standard_ran: int
    skipped_overlap: bool


class ConcurrencySlotOut(CamelModel):
    max: int
    in_use: int
    waiting: int = 0


class SystemAiStatusOut(CamelModel):
    scheduler_enabled: bool
    scheduler_poll_seconds: int
    unified_face_sweep_enabled: bool
    global_sweep_concurrency: int
    face_inference_concurrency: int
    object_inference_concurrency: int
    critical_modules: list[str]
    standard_modules: list[str]
    last_tick: SchedulerLastTickOut
    gpu: GpuStatusOut
    sweep_slots: ConcurrencySlotOut
    face_inference_gate: ConcurrencySlotOut
    stream_reader_count: int
    embedding_sweep_cache_ttl_seconds: int


class MediaMTXShardOut(CamelModel):
    index: int
    api_url: str
    hls_base_url: str
    reachable: bool
    path_count: int
    assigned_cameras: int = 0
    error: str | None = None


class SystemStreamStatusOut(CamelModel):
    sharding_enabled: bool
    shard_count: int
    faol_cameras: int
    registered_streams: int
    shards: list[MediaMTXShardOut]
    distribution: list[int]
    recommendation: str
    hls_public_base: str


class CameraHealthSweepOut(CamelModel):
    finished_at: str | None
    duration_seconds: float
    faol_checked: int
    reachable: int
    skipped_overlap: bool


class SystemCameraNetworkOut(CamelModel):
    faol_cameras: int
    reachable_cameras: int
    offline_cameras: int
    link_local_ip_count: int
    chronic_offline_count: int
    offline_alert_minutes: int
    health_interval_seconds: int
    health_freshness_seconds: int
    health_concurrency: int
    recent_offline_alerts_24h: int
    last_sweep: CameraHealthSweepOut
    recommendation: str


class StreamResyncOut(CamelModel):
    synced: int
    failed: int
