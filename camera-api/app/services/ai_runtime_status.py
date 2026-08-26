"""Aggregated AI runtime snapshot for the admin dashboard."""

from app.config import settings
from app.jobs.scheduler_metrics import get_scheduler_tick_stats
from app.jobs.sweep_concurrency import sweep_concurrency_snapshot
from app.services.gpu_status import get_gpu_status
from app.services.inference_gate import face_inference_gate
from app.services.stream_cache import active_stream_reader_count


def _scheduler_module_lists() -> tuple[list[str], list[str]]:
    if settings.unified_face_sweep_enabled:
        critical = ["unified_face", "fire", "fall", "zone_entry", "fight"]
    else:
        critical = ["attendance", "vision_sleep", "unauthorized", "crowd", "fire", "fall", "zone_entry", "fight"]
    standard = [
        "teacher_punctuality",
        "abandoned_object",
        "disorder",
        "dress_code",
        "phone",
        "badge",
        "ppe",
        "smoking",
        "student_dress",
        "vehicle",
        "lesson_quality",
    ]
    return critical, standard


def build_ai_runtime_status() -> dict[str, object]:
    tick = get_scheduler_tick_stats()
    gpu = get_gpu_status()
    critical, standard = _scheduler_module_lists()
    sweep = sweep_concurrency_snapshot()

    return {
        "scheduler_enabled": settings.ai_scheduler_enabled,
        "scheduler_poll_seconds": settings.ai_scheduler_poll_seconds,
        "unified_face_sweep_enabled": settings.unified_face_sweep_enabled,
        "global_sweep_concurrency": settings.ai_global_sweep_concurrency,
        "face_inference_concurrency": settings.face_recognition_inference_concurrency,
        "object_inference_concurrency": settings.object_detection_inference_concurrency,
        "critical_modules": critical,
        "standard_modules": standard,
        "last_tick": {
            "finished_at": tick.finished_at.isoformat() if tick.finished_at else None,
            "duration_seconds": tick.duration_seconds,
            "modules_ran": tick.modules_ran,
            "critical_ran": tick.critical_ran,
            "standard_ran": tick.standard_ran,
            "skipped_overlap": tick.skipped_overlap,
        },
        "gpu": gpu,
        "sweep_slots": sweep,
        "face_inference_gate": face_inference_gate.snapshot(),
        "stream_reader_count": active_stream_reader_count(),
        "embedding_sweep_cache_ttl_seconds": settings.candidate_matrix_sweep_cache_ttl_seconds,
    }
