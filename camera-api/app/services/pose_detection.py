"""Full-body pose estimation (33 landmarks in BlazePose numbering: nose,
shoulders, hips, knees, ankles, wrists, etc., each with normalized x/y/z
and a visibility score), the third detection backbone alongside
app/services/face_recognition.py (InsightFace, faces) and
app/services/object_detection.py (YOLOv8, generic objects). Used by AI
criteria that need body POSTURE/MOVEMENT rather than identity or object
class (zone entry, fight, smoking, white coat, teacher activity).

Two interchangeable backends produce the SAME PoseLandmarks shape, so no
consumer knows or cares which one ran:

* "mediapipe" — Google's Pose Landmarker (pose_landmarker_lite.task,
  ~5.5MB, the "lite" tier chosen for CPU speed). Verified against a real
  photo — see tests/test_pose_detection.py.
* "yolo" — Ultralytics YOLOv8-pose (yolov8n-pose.pt, COCO 17 keypoints),
  mapped onto the BlazePose indices below. Landmarks COCO does not have
  (eye corners, fingers, heels…) are left with visibility 0, so every
  consumer's visibility check simply skips them.

WHY TWO BACKENDS. mediapipe's compiled .so requires AVX. On a processor
without it (the production server — often a VM whose virtual CPU model
hides AVX) every call dies with a native SIGILL ("this binary was compiled
with avx enabled, but this feature is not available on this processor").
That is a hardware fault, not a Python exception — no try/except catches
it. PyTorch (under YOLO) dispatches at runtime and runs without AVX.

Backend choice (settings.pose_detection_backend):
* "auto" (default) — mediapipe when /proc/cpuinfo lists AVX (or cannot be
  read, e.g. on a developer's Windows/macOS machine), otherwise yolo.
* "mediapipe" / "yolo" — forced.

mediapipe still runs in a dedicated ProcessPoolExecutor, NOT
asyncio.to_thread: a SIGILL inside this process's address space would kill
the whole API instantly. A real OS subprocess boundary means the fault
kills only that worker. And because AVX detection can be wrong (a CPU flag
listed but masked by the hypervisor), a circuit breaker backs it up: after
settings.pose_detection_max_worker_crashes consecutive worker crashes this
process switches to yolo for good. Production logged ~26 crashes a minute
before this existed — each one respawning a full Python interpreter that
imported mediapipe only to die again, burning CPU for zero poses and
leaving every pose-based criterion silently blind.

Landmark indices follow mediapipe's standard BlazePose 33-point topology
(the same numbering every mediapipe Pose consumer uses): 0=nose,
11/12=left/right shoulder, 23/24=left/right hip, 25/26=left/right knee,
27/28=left/right ankle, 15/16=left/right wrist. "Left" is the SUBJECT's
left in both BlazePose and COCO, so the mapping needs no mirroring.
"""

import asyncio
import logging
import multiprocessing
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.config import settings
from app.services.inference_cache import inference_cache

logger = logging.getLogger("app.pose_detection")

NOSE = 0
LEFT_EYE, RIGHT_EYE = 2, 5
LEFT_EAR, RIGHT_EAR = 7, 8
LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_ELBOW, RIGHT_ELBOW = 13, 14
LEFT_WRIST, RIGHT_WRIST = 15, 16
LEFT_HIP, RIGHT_HIP = 23, 24
LEFT_KNEE, RIGHT_KNEE = 25, 26
LEFT_ANKLE, RIGHT_ANKLE = 27, 28

BLAZEPOSE_LANDMARK_COUNT = 33

# COCO keypoint i (YOLOv8-pose output order) -> BlazePose landmark index.
COCO_TO_BLAZEPOSE: tuple[int, ...] = (
    NOSE,
    LEFT_EYE, RIGHT_EYE,
    LEFT_EAR, RIGHT_EAR,
    LEFT_SHOULDER, RIGHT_SHOULDER,
    LEFT_ELBOW, RIGHT_ELBOW,
    LEFT_WRIST, RIGHT_WRIST,
    LEFT_HIP, RIGHT_HIP,
    LEFT_KNEE, RIGHT_KNEE,
    LEFT_ANKLE, RIGHT_ANKLE,
)

BACKEND_MEDIAPIPE = "mediapipe"
BACKEND_YOLO = "yolo"

# cv2/mediapipe are imported lazily, inside the functions that actually run
# in the worker subprocess — keeps the heavy native mediapipe .so out of the
# main API process's address space entirely.
_landmarker = None  # mediapipe PoseLandmarker, set inside the worker process
# YOLOv8-pose: har bir inference oqimi modelning o'z nusxasini ishlatadi
# (object_detection.py dagi izohga qarang — Ultralytics modeli oqimlar
# orasida bo'lishish uchun xavfsiz emas).
_yolo_thread_models = threading.local()
_yolo_load_lock = threading.Lock()
_yolo_executor: ThreadPoolExecutor | None = None
_inference_semaphore = asyncio.Semaphore(settings.pose_detection_inference_concurrency)
_pool: ProcessPoolExecutor | None = None
_backend: str | None = None  # resolved on first use, see _resolve_backend
_consecutive_crashes = 0


@dataclass
class PoseLandmarks:
    points: np.ndarray  # (33, 4) — columns: x, y (normalized 0-1 of frame width/height), z, visibility

    def visible(self, index: int, min_visibility: float) -> bool:
        return bool(self.points[index][3] >= min_visibility)


# ── backend selection ────────────────────────────────────────────────────


def cpu_supports_avx(cpuinfo_text: str | None = None) -> bool | None:
    """True/False from the "flags" line of /proc/cpuinfo; None when that
    cannot be determined (not Linux, file unreadable, no flags line)."""
    if cpuinfo_text is None:
        try:
            cpuinfo_text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    for line in cpuinfo_text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "flags":
            return "avx" in value.split()
    return None


def choose_backend(configured: str, avx: bool | None) -> str:
    configured = (configured or "auto").strip().lower()
    if configured in (BACKEND_MEDIAPIPE, BACKEND_YOLO):
        return configured
    # "auto" (and anything unrecognized): only an explicit "no AVX" rules
    # mediapipe out — an unknown CPU keeps the verified default.
    return BACKEND_YOLO if avx is False else BACKEND_MEDIAPIPE


def _mediapipe_model_present() -> bool:
    return Path(settings.pose_detection_model_path).is_file()


def _resolve_backend() -> str:
    global _backend
    if _backend is None:
        avx = cpu_supports_avx()
        _backend = choose_backend(settings.pose_detection_backend, avx)
        if (
            _backend == BACKEND_MEDIAPIPE
            and (settings.pose_detection_backend or "auto").strip().lower() == "auto"
            and not _mediapipe_model_present()
        ):
            # Mediapipe modeli (pose_landmarker_lite.task) avtomatik
            # yuklanmaydi — u yo'q bo'lsa poza umuman ishlamasdi (chekish
            # #15 va o'qituvchi faolligi #21 jimgina o'chib qolardi).
            # YOLO-pose og'irliklari birinchi chaqiruvda o'zi yuklanadi.
            _backend = BACKEND_YOLO
        logger.info(
            "pose detection backend selected",
            extra={"backend": _backend, "configured": settings.pose_detection_backend, "cpu_avx": avx},
        )
    return _backend


def active_pose_backend() -> str:
    """Which backend detect_poses() uses right now (for diagnostics)."""
    return _resolve_backend()


# ── mediapipe (worker subprocess) ────────────────────────────────────────


def _get_landmarker():
    global _landmarker
    if _landmarker is None:
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode

        logger.info(
            "loading mediapipe pose landmarker (first use)",
            extra={"model": settings.pose_detection_model_path},
        )
        options = PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=settings.pose_detection_model_path),
            running_mode=RunningMode.IMAGE,
            num_poses=settings.pose_detection_max_poses,
        )
        _landmarker = PoseLandmarker.create_from_options(options)
    return _landmarker


def _detect_sync(image_bytes: bytes) -> list[PoseLandmarks]:
    """Runs inside the dedicated worker subprocess (see _get_pool) — a
    native crash here (e.g. mediapipe's AVX SIGILL) takes down only this
    disposable process, never the API itself."""
    import cv2
    import mediapipe as mp

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return []

    landmarker = _get_landmarker()
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    result = landmarker.detect(mp_image)

    poses: list[PoseLandmarks] = []
    for pose in result.pose_landmarks:
        points = np.array([[lm.x, lm.y, lm.z, lm.visibility] for lm in pose])
        poses.append(PoseLandmarks(points=points))
    return poses


def _get_pool() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(
            max_workers=settings.pose_detection_inference_concurrency,
            mp_context=multiprocessing.get_context("spawn"),
        )
    return _pool


def _discard_pool() -> None:
    global _pool
    broken, _pool = _pool, None
    if broken is not None:
        try:
            broken.shutdown(wait=False, cancel_futures=True)
        except Exception:  # a broken pool may refuse even this — nothing left to clean
            pass


class _WorkerCrashed(Exception):
    """Ishchi jarayon yiqilgan kadr — natija "poza yo'q", lekin keshga
    yozilmaydi (inference_cache xatolarni saqlamaydi): shu kadr qayta
    so'ralsa, qayta urinib ko'riladi."""


async def _run_mediapipe_worker(image_bytes: bytes) -> list[PoseLandmarks]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_get_pool(), _detect_sync, image_bytes)


async def _detect_mediapipe(image_bytes: bytes) -> list[PoseLandmarks]:
    global _backend, _consecutive_crashes
    try:
        poses = await _run_mediapipe_worker(image_bytes)
    except BrokenProcessPool:
        _consecutive_crashes += 1
        _discard_pool()
        limit = max(1, settings.pose_detection_max_worker_crashes)
        if _consecutive_crashes < limit:
            logger.error(
                "pose detection worker crashed (native fault) — resetting pool",
                extra={"consecutive_crashes": _consecutive_crashes, "limit": limit},
            )
            raise _WorkerCrashed from None
        if _backend != BACKEND_YOLO:
            logger.error(
                "mediapipe pose worker keeps crashing — switching to YOLOv8-pose for this process",
                extra={"consecutive_crashes": _consecutive_crashes},
            )
            _backend = BACKEND_YOLO
        return await _run_yolo(_detect_yolo_sync, image_bytes)
    _consecutive_crashes = 0
    return poses


# ── YOLOv8-pose (API process, worker thread) ─────────────────────────────


def _get_yolo_model():
    model = getattr(_yolo_thread_models, "model", None)
    if model is None:
        from ultralytics import YOLO

        with _yolo_load_lock:
            logger.info(
                "loading YOLOv8-pose model for a worker thread",
                extra={"model": settings.pose_detection_yolo_model_path},
            )
            model = YOLO(settings.pose_detection_yolo_model_path)
        _yolo_thread_models.model = model
    return model


def _get_yolo_executor() -> ThreadPoolExecutor:
    global _yolo_executor
    if _yolo_executor is None:
        _yolo_executor = ThreadPoolExecutor(
            max_workers=max(1, settings.pose_detection_inference_concurrency),
            thread_name_prefix="yolo-pose",
        )
    return _yolo_executor


async def _run_yolo(func, *args):
    return await asyncio.get_running_loop().run_in_executor(_get_yolo_executor(), func, *args)


def coco_keypoints_to_poses(
    xyn: np.ndarray,
    keypoint_conf: np.ndarray | None,
    box_conf: np.ndarray,
    max_poses: int,
) -> list[PoseLandmarks]:
    """(N,17,2) normalized COCO keypoints -> BlazePose-shaped poses, most
    confident person first. Without per-keypoint confidences a keypoint
    counts as visible only if the model placed it (non-zero coordinates)."""
    xyn = np.asarray(xyn, dtype=np.float64).reshape(-1, len(COCO_TO_BLAZEPOSE), 2)
    box_conf = np.asarray(box_conf, dtype=np.float64).reshape(-1)
    order = np.argsort(-box_conf, kind="stable")[: max(0, max_poses)]
    targets = list(COCO_TO_BLAZEPOSE)

    poses: list[PoseLandmarks] = []
    for i in order:
        points = np.zeros((BLAZEPOSE_LANDMARK_COUNT, 4), dtype=np.float64)
        points[targets, 0:2] = xyn[i]
        if keypoint_conf is not None:
            points[targets, 3] = np.clip(np.asarray(keypoint_conf, dtype=np.float64).reshape(xyn.shape[0], -1)[i], 0.0, 1.0)
        else:
            points[targets, 3] = (np.abs(xyn[i]).sum(axis=1) > 0).astype(np.float64)
        poses.append(PoseLandmarks(points=points))
    return poses


def _detect_yolo_sync(image_bytes: bytes) -> list[PoseLandmarks]:
    import cv2

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR) if arr.size else None
    if img is None:
        return []

    model = _get_yolo_model()
    results = model.predict(
        img,
        conf=settings.pose_detection_yolo_confidence,
        # YOLO-pose oqimlar hovuzida (process emas) — CUDA xavfsiz. GPU
        # bayrog'i obyekt aniqlash (YOLO) bilan umumiy: ikkalasi bitta torch.
        device=0 if settings.object_detection_gpu_enabled else "cpu",
        verbose=False,
    )
    poses: list[PoseLandmarks] = []
    for result in results:
        keypoints = result.keypoints
        if keypoints is None or result.boxes is None or len(result.boxes) == 0:
            continue
        xyn = keypoints.xyn.cpu().numpy()
        conf = keypoints.conf.cpu().numpy() if keypoints.conf is not None else None
        box_conf = result.boxes.conf.cpu().numpy()
        poses.extend(coco_keypoints_to_poses(xyn, conf, box_conf, settings.pose_detection_max_poses))
    return poses[: settings.pose_detection_max_poses]


# ── public API ───────────────────────────────────────────────────────────


async def detect_poses(image_bytes: bytes) -> list[PoseLandmarks]:
    """Gated by _inference_semaphore, same rationale as
    face_recognition.detect_faces(). Returns up to
    settings.pose_detection_max_poses poses (order not guaranteed to be
    left-to-right). Never raises for a worker crash: the call that hit the
    crash sees "no poses" (or, once the breaker trips, the YOLO result)."""
    async def run() -> list[PoseLandmarks]:
        async with _inference_semaphore:
            if _resolve_backend() == BACKEND_YOLO:
                return await _run_yolo(_detect_yolo_sync, image_bytes)
            return await _detect_mediapipe(image_bytes)

    # Bir kadrning pozasi bir marta hisoblanadi: jang, zona, chekish, xalat va
    # dars modullari kadr tarixidan bir xil kadrni olganda natijani bo'lishadi
    # (app/services/inference_cache.py).
    try:
        return await inference_cache.get_or_run(image_bytes, ("poses",), run)
    except _WorkerCrashed:
        return []


async def shutdown_pose_detection_pool() -> None:
    """Cleanly tears down the worker process(es) — called from main.py's
    lifespan teardown, same pattern as stream_cache.shutdown_stream_cache."""
    _discard_pool()
