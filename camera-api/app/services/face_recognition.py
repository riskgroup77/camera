"""Real biometric face comparison via InsightFace (ArcFace embeddings) —
replaces the frontend's average-hash (aHash) placeholder in
camera/src/lib/imageSimilarity.ts, which explicitly documented itself as
"not true face recognition, but a real, deterministic comparison of pixel
data". This is the real thing: a RetinaFace-family detector finds faces,
a ResNet-50 recognition model (trained with ArcFace loss) embeds each
into a 512-d vector, and cosine similarity between embeddings is the
match score — the same category of model real biometric systems use.
"""

import asyncio
import logging
from dataclasses import dataclass

import cv2
import numpy as np
from insightface.app import FaceAnalysis

from app.config import settings
from app.services.inference_gate import PRIORITY_BACKGROUND, PRIORITY_LIVE, face_inference_gate

logger = logging.getLogger("app.face_recognition")

_app: FaceAnalysis | None = None

# Cosine similarity threshold for buffalo_l embeddings. This is a
# reasonable starting point, not a validated production number — real
# deployments should tune this against their own enrollment photos and
# accept a false-accept/false-reject tradeoff explicitly (see TT bo'lim on
# biometrics if it specifies a target FAR/FRR).
MATCH_THRESHOLD = 0.45


class NoFaceDetectedError(Exception):
    pass


# InsightFace/ONNX inference is CPU/GPU-bound. Found from real testing
# (not hypothetical): with the live-detection overlay endpoint polling
# every few seconds AND the background attendance/sleep sweep loops each
# doing their own inference every ~30s, several calls landing around the
# same moment made every one of them slower — which cascaded into sweeps
# that should complete in seconds instead stretching to minutes apart,
# since each sweep's grab-then-infer step was queued behind the others'
# work. Capping how many inference calls run at once keeps each one's
# latency bounded, regardless of how many callers show up together.
#
# The cap itself is configurable (settings.face_recognition_inference_
# concurrency) because the right number depends entirely on the hardware
# actually running this: 2 is sane for a CPU-only dev machine, but a
# production GPU server should raise this a lot — GPUs get their
# throughput specifically from many concurrent/batched operations, so a
# CPU-tuned cap of 2 would leave most of a real GPU deployment's capacity
# unused. Read once at import time (like the rest of this module's
# settings-derived state) — changing it requires a restart, same as
# MATCH_THRESHOLD.
# Slot allocation is via app/services/inference_gate.py — live-detection
# and enrollment jump ahead of background AI sweeps.


def _get_app() -> FaceAnalysis:
    global _app
    if _app is None:
        # CUDAExecutionProvider first when GPU is enabled: onnxruntime
        # tries providers in list order and falls back to the next one it
        # actually has support for, so requesting CUDA first is safe even
        # if the CPU-only `onnxruntime` package (not `onnxruntime-gpu`) is
        # what's installed — it just silently falls through to CPU. This
        # config flag exists so the production GPU server (onnxruntime-gpu
        # installed) gets real GPU inference without a code change, while
        # dev machines stay CPU-only by default.
        providers = ["CPUExecutionProvider"]
        if settings.face_recognition_gpu_enabled:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        logger.info(
            "loading InsightFace buffalo_l model (first use)",
            extra={"gpu_enabled": settings.face_recognition_gpu_enabled},
        )
        _app = FaceAnalysis(name="buffalo_l", providers=providers)
        # ctx_id=0 selects GPU device 0 when CUDAExecutionProvider is
        # active, and is harmless/ignored when it isn't (the CPU-only path
        # this codebase already ran and tested with before GPU support
        # existed also used ctx_id=0).
        _app.prepare(ctx_id=0, det_size=(640, 640))
    return _app


@dataclass
class FaceCompareResult:
    matched: bool
    confidence: float  # 0-100, rescaled cosine similarity — for display only
    similarity: float  # raw cosine similarity — what MATCH_THRESHOLD is actually compared against
    faces_detected_a: int
    faces_detected_b: int


def _embed(image_bytes: bytes) -> tuple[np.ndarray | None, int]:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise NoFaceDetectedError("Rasm formatini o'qib bo'lmadi")

    faces = _get_app().get(img)
    if not faces:
        return None, 0

    # Largest face by bounding-box area is treated as the photo's subject —
    # relevant for passport scans that might catch a second face in the background.
    best = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return best.normed_embedding, len(faces)


def _compare_sync(image_a: bytes, image_b: bytes) -> FaceCompareResult:
    emb_a, count_a = _embed(image_a)
    emb_b, count_b = _embed(image_b)
    if emb_a is None or emb_b is None:
        raise NoFaceDetectedError(f"Yuz aniqlanmadi (1-rasmda {count_a} ta, 2-rasmda {count_b} ta yuz topildi)")

    similarity = float(np.dot(emb_a, emb_b))  # both are L2-normalized -> dot product IS cosine similarity
    confidence = max(0.0, min(100.0, (similarity + 1) / 2 * 100))
    return FaceCompareResult(
        matched=similarity >= MATCH_THRESHOLD,
        confidence=round(confidence, 1),
        similarity=round(similarity, 4),
        faces_detected_a=count_a,
        faces_detected_b=count_b,
    )


async def compare_faces(image_a: bytes, image_b: bytes) -> FaceCompareResult:
    """Runs on a worker thread — InsightFace/ONNX inference is CPU-bound
    and synchronous; running it directly on the event loop would stall
    every other request for the ~100-300ms a comparison takes. Gated by
    face_inference_gate — see inference_gate.py."""
    async with face_inference_gate.slot(priority=PRIORITY_LIVE):
        return await asyncio.to_thread(_compare_sync, image_a, image_b)


def _extract_embedding_sync(image_bytes: bytes) -> list[float]:
    emb, count = _embed(image_bytes)
    if emb is None:
        raise NoFaceDetectedError(f"Yuz aniqlanmadi ({count} ta yuz topildi)")
    return emb.tolist()


async def extract_embedding(image_bytes: bytes) -> list[float]:
    """Used at enrollment time (app/routers/students_staff.py) to persist
    the enrollment photo's embedding — separate from compare_faces() since
    enrollment only ever has one photo to embed, not two to compare. Gated
    by face_inference_gate with live priority."""
    async with face_inference_gate.slot(priority=PRIORITY_LIVE):
        return await asyncio.to_thread(_extract_embedding_sync, image_bytes)


@dataclass
class DetectedFace:
    embedding: np.ndarray
    landmarks_68: np.ndarray  # (68, 3) — the standard iBUG scheme; see app/services/sleep_detection.py
    bbox: np.ndarray  # (4,) — [x1, y1, x2, y2] in the source image's pixel coordinates


def _detect_faces_sync(image_bytes: bytes) -> list[DetectedFace]:
    """Every face in the frame (not just the largest) with its embedding,
    68-point landmarks, and bounding box — reuses the same loaded
    buffalo_l model as everything else in this module (it already computes
    all three as part of every detection; nothing extra to load). Used by
    app/services/sleep_detection.py, which needs to check every face a
    classroom camera sees, not just the most prominent one, and by
    app/routers/cameras.py's live-detection endpoint, which needs the
    bbox to draw an overlay on the video."""
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise NoFaceDetectedError("Rasm formatini o'qib bo'lmadi")

    faces = _get_app().get(img)
    return [
        DetectedFace(embedding=f.normed_embedding, landmarks_68=f.landmark_3d_68, bbox=f.bbox)
        for f in faces
    ]


async def detect_faces(
    image_bytes: bytes, *, priority: int = PRIORITY_BACKGROUND
) -> list[DetectedFace]:
    """Gated by face_inference_gate — pass PRIORITY_LIVE for live-detection."""
    async with face_inference_gate.slot(priority=priority):
        return await asyncio.to_thread(_detect_faces_sync, image_bytes)


def _detect_faces_batch_sync(images: list[bytes]) -> list[list[DetectedFace]]:
    """Process multiple frames under one inference gate acquisition."""
    return [_detect_faces_sync(img) for img in images]


async def detect_faces_batch(
    image_bytes_list: list[bytes], *, priority: int = PRIORITY_BACKGROUND
) -> list[list[DetectedFace]]:
    """Batch face detection — chunks by face_recognition_batch_size."""
    if not image_bytes_list:
        return []
    batch_size = max(1, settings.face_recognition_batch_size)
    all_results: list[list[DetectedFace]] = []
    async with face_inference_gate.slot(priority=priority):
        for i in range(0, len(image_bytes_list), batch_size):
            chunk = image_bytes_list[i : i + batch_size]
            chunk_results = await asyncio.to_thread(_detect_faces_batch_sync, chunk)
            all_results.extend(chunk_results)
    return all_results
