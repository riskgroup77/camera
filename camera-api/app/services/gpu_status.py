"""Runtime GPU / inference provider detection for admin observability."""

import logging

from app.config import settings

logger = logging.getLogger("app.gpu_status")


def _onnxruntime_providers() -> list[str]:
    try:
        import onnxruntime as ort

        return list(ort.get_available_providers())
    except ImportError:
        return []
    except Exception:
        logger.exception("onnxruntime provider probe failed")
        return []


def _torch_cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except ImportError:
        return False
    except Exception:
        logger.exception("torch CUDA probe failed")
        return False


def get_gpu_status() -> dict[str, object]:
    providers = _onnxruntime_providers()
    cuda_in_onnx = "CUDAExecutionProvider" in providers
    torch_cuda = _torch_cuda_available()
    cuda_available = cuda_in_onnx or torch_cuda

    # Model yuklangan bo'lsa — sessiyalar AMALDA nima ishlatayotgani
    # (CUDA "mavjud", lekin cuDNN topilmasa sessiya jimgina CPU'da ishlaydi).
    from app.services.face_recognition import face_session_providers

    session_providers = face_session_providers()
    face_fell_back = session_providers is not None and "CUDAExecutionProvider" not in session_providers
    face_active = settings.face_recognition_gpu_enabled and cuda_in_onnx and not face_fell_back
    object_active = settings.object_detection_gpu_enabled and torch_cuda

    if settings.face_recognition_gpu_enabled and cuda_in_onnx and face_fell_back:
        recommendation = (
            "CUDA mavjud, lekin yuz modellari CPU'da ishlayapti — onnxruntime CUDA/cuDNN "
            "kutubxonalarini yuklay olmadi (konteyner logida 'InsightFace sessions ready' qatori)."
        )
    elif settings.face_recognition_gpu_enabled and not cuda_in_onnx:
        recommendation = (
            "FACE_RECOGNITION_GPU_ENABLED=true, lekin CUDAExecutionProvider yo'q — "
            "Dockerfile.gpu + nvidia-container-toolkit o'rnatilganini tekshiring."
        )
    elif settings.object_detection_gpu_enabled and not torch_cuda:
        recommendation = (
            "OBJECT_DETECTION_GPU_ENABLED=true, lekin PyTorch CUDA yo'q — "
            "GPU Docker image va NVIDIA driver kerak."
        )
    elif not cuda_available:
        recommendation = (
            "GPU aniqlanmadi — CPU rejimida ishlayapti. "
            "Tezlashtirish uchun: NVIDIA driver + deploy/install-nvidia-toolkit.sh + setup-scale-infra.sh"
        )
    elif face_active and object_active:
        recommendation = "GPU faol — InsightFace (ONNX CUDA) va YOLO (PyTorch CUDA) ishlatilmoqda."
    elif face_active or object_active:
        recommendation = "GPU qisman faol — sozlamalarni deploy/env.production.scale dan tekshiring."
    else:
        recommendation = "GPU mavjud, lekin .env da GPU flaglari o'chirilgan."

    return {
        "cuda_available": cuda_available,
        "onnx_providers": providers,
        "torch_cuda_available": torch_cuda,
        "face_gpu_enabled": settings.face_recognition_gpu_enabled,
        "face_gpu_active": face_active,
        "face_session_providers": session_providers or [],
        "object_gpu_enabled": settings.object_detection_gpu_enabled,
        "object_gpu_active": object_active,
        "recommendation": recommendation,
    }
