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
