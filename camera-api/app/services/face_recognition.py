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
import threading
from dataclasses import dataclass

import cv2
import numpy as np
from insightface.app import FaceAnalysis
from insightface.app.common import Face
from insightface.utils import face_align

from app.config import settings
from app.services.inference_cache import inference_cache
from app.services.inference_gate import PRIORITY_BACKGROUND, PRIORITY_LIVE, face_inference_gate

logger = logging.getLogger("app.face_recognition")

_app: FaceAnalysis | None = None
# Birinchi chaqiruvda bir nechta oqim bir vaqtda modelni yuklamasin
# (productionda ai-worker ishga tushganda buffalo_l 3 marta yuklangan).
_app_lock = threading.Lock()
# Tizim o'qiydigan InsightFace modellari — _get_app() izohiga qarang.
REQUIRED_FACE_MODELS = ["detection", "recognition", "landmark_3d_68"]

# Cosine similarity threshold for buffalo_l embeddings. This is a
# reasonable starting point, not a validated production number — real
# deployments should tune this against their own enrollment photos and
# accept a false-accept/false-reject tradeoff explicitly (see TT bo'lim on
# biometrics if it specifies a target FAR/FRR).
MATCH_THRESHOLD = 0.45

# How similar every enrollment frame's embedding must be to the first
# ("frontal") frame — guards the multi-angle enrollment flow
# (extract_enrollment_embedding) against a bad capture session (camera
# handed to someone else mid-scan, wrong face detected in one frame,
# etc.). Deliberately looser than MATCH_THRESHOLD: these are the SAME
# person's own frames from one session, just at different head angles,
# which reduces ArcFace similarity more than two straight-on photos of
# the same person would — but two genuinely different people's embeddings
# still land far below this.
ENROLLMENT_CONSISTENCY_THRESHOLD = 0.35


class NoFaceDetectedError(Exception):
    pass


class InconsistentFacesError(Exception):
    """Raised by extract_enrollment_embedding when the captured frames
    don't look like the same person — see ENROLLMENT_CONSISTENCY_THRESHOLD."""

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


def _int8_model_file(model_file: str, taskname: str) -> str:
    """CPU'da INT8 (dinamik kvantlangan) model — AVX'siz protsessorda
    (production: QEMU, faqat SSE4.2) butun sonli hisob tezroq.

    O'lchov (2026-09-26, production CPU, 40 ta ro'yxat rasmi):
      * ArcFace w600k_r50: 425 -> 243 ms/yuz; cos(fp32, int8) o'rtacha 0.994,
        eng pasti 0.989; 40/40 o'zini topdi — mavjud yuz bazasi (fp32
        vektorlar) qayta hisoblanmaydi;
      * SCRFD det_10g 1280x736: 1657 -> 1286 ms; 24 jonli kadrda bir xil yuzlar.
    Fayl model yonida bir marta yaratiladi; xato bo'lsa — asl fp32 model."""
    wanted = (taskname == "recognition" and settings.face_recognition_int8) or (
        taskname == "detection" and settings.face_detection_int8
    )
    if not wanted:
        return model_file
    target = model_file[:-5] + ".int8.onnx" if model_file.endswith(".onnx") else model_file + ".int8"
    try:
        import os

        if not os.path.exists(target):
            from onnxruntime.quantization import QuantType, quantize_dynamic

            partial = target + ".part"
            quantize_dynamic(model_file, partial, weight_type=QuantType.QUInt8)
            os.replace(partial, target)
            logger.info("INT8 model created", extra={"model": os.path.basename(target)})
        return target
    except Exception:
        logger.warning("INT8 quantization failed — using fp32 model", extra={"model": model_file}, exc_info=True)
        return model_file


def _limit_session_threads(app: FaceAnalysis, providers: list[str]) -> None:
    """Har bir InsightFace modelining ONNX sessiyasini cheklangan oqimlar bilan
    qayta yaratadi (settings.face_recognition_intra_op_threads).

    Nega bu yerda, FaceAnalysis(...) argumenti orqali emas: insightface 1.0.1
    modellarga faqat providers/provider_options uzatadi, sess_options esa
    yo'lda tushib qoladi (insightface/model_zoo/model_zoo.py, get_model).
    Har bir model sessiyani `session`, faylni `model_file` da saqlaydi va
    kirish/chiqish nomlarini fayldan oladi — o'sha fayldan qayta yaratilgan
    sessiya bir xil ishlaydi."""
    threads = settings.face_recognition_intra_op_threads
    cpu_only = "CUDAExecutionProvider" not in providers
    if threads <= 0 and not cpu_only:
        return
    import onnxruntime

    for model in app.models.values():
        model_file = getattr(model, "model_file", None)
        if not model_file:
            continue
        if cpu_only:
            model_file = _int8_model_file(model_file, getattr(model, "taskname", ""))
        options = onnxruntime.SessionOptions()
        if threads > 0:
            options.intra_op_num_threads = threads
            options.inter_op_num_threads = 1
        options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
        model.session = onnxruntime.InferenceSession(model_file, sess_options=options, providers=providers)
    logger.info(
        "InsightFace ONNX sessions limited",
        extra={
            "intra_op_threads": threads,
            "inference_concurrency": settings.face_recognition_inference_concurrency,
            "models": sorted(app.models),
        },
    )


# Yuklangan modellar AMALDA ishlatayotgan provayderlar. onnxruntime CUDA
# kutubxonalarini (cuDNN 9, cuBLAS) topa olmasa, ogohlantirish yozib
# jimgina CPU'ga qaytadi — get_available_providers() esa baribir CUDA'ni
# ko'rsatadi. Panel (app/services/gpu_status.py) shu ro'yxatga qaraydi.
_session_providers: list[str] | None = None


def face_session_providers() -> list[str] | None:
    """None — model hali yuklanmagan."""
    return _session_providers


def _preload_cuda_libraries() -> None:
    """onnxruntime-gpu CUDA/cuDNN kutubxonalarini pip'dagi nvidia-* paketlaridan
    (torch cu130 ular bilan keladi — Dockerfile.gpu) yuklaydi. Tizimda CUDA
    toolkit o'rnatilmagan konteynerda busiz CUDA provayderi ishlamaydi."""
    try:
        import onnxruntime

        preload = getattr(onnxruntime, "preload_dlls", None)
        if preload is not None:
            preload()
    except Exception:
        logger.warning("onnxruntime CUDA library preload failed", exc_info=True)


def _get_app() -> FaceAnalysis:
    if _app is None:
        with _app_lock:
            if _app is None:
                _load_app()
    return _app


def _load_app() -> None:
    """_app_lock ichida chaqiriladi."""
    global _app, _session_providers
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
        _preload_cuda_libraries()
    logger.info(
        "loading InsightFace buffalo_l model (first use)",
        extra={"gpu_enabled": settings.face_recognition_gpu_enabled},
    )
    # Faqat tizim haqiqatan o'qiydigan modellar. buffalo_l standart
    # bo'yicha 5 ta modelni HAR BIR YUZ uchun ishga tushiradi; kod esa
    # faqat normed_embedding (recognition), bbox (detection) va
    # landmark_3d_68 (uyqu, frontallik, liveness) ni ishlatadi.
    # genderage va landmark_2d_106 hech qayerda o'qilmaydi — productionda
    # kirish kamerasida kadrga ~21 yuz tushadi, ya'ni kadr boshiga ~42
    # ta befoyda model chaqiruvi CPU chegarasida turgan konteynerda.
    app = FaceAnalysis(name="buffalo_l", providers=providers, allowed_modules=REQUIRED_FACE_MODELS)
    _limit_session_threads(app, providers)
    # ctx_id=0 selects GPU device 0 when CUDAExecutionProvider is
    # active, and is harmless/ignored when it isn't (the CPU-only path
    # this codebase already ran and tested with before GPU support
    # existed also used ctx_id=0).
    app.prepare(ctx_id=0, det_size=(640, 640))
    actual: set[str] = set()
    for model in app.models.values():
        session = getattr(model, "session", None)
        if session is not None:
            actual.update(session.get_providers())
    _session_providers = sorted(actual)
    level = logging.INFO
    if settings.face_recognition_gpu_enabled and "CUDAExecutionProvider" not in actual:
        level = logging.ERROR
    logger.log(level, "InsightFace sessions ready", extra={"providers": _session_providers})
    # Boshqa oqimlar faqat to'liq tayyor modelni ko'rsin.
    _app = app


@dataclass
class FaceCompareResult:
    matched: bool
    confidence: float  # 0-100, rescaled cosine similarity — for display only
    similarity: float  # raw cosine similarity — what MATCH_THRESHOLD is actually compared against
    faces_detected_a: int
    faces_detected_b: int


#: Ochiladigan rasmning eng katta o'lchami (telefon kamerasi ~50 MP gacha).
MAX_DECODE_PIXELS = 50_000_000
PNG_SIGNATURE = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])


def _declared_dimensions(data: bytes) -> tuple[int, int] | None:
    """JPEG yoki PNG sarlavhasidagi (eni, bo'yi); aniqlanmasa None."""
    from app.services.image_size import jpeg_dimensions

    if data[:8] == PNG_SIGNATURE and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return jpeg_dimensions(data)


def _decode_image(image_bytes: bytes) -> np.ndarray:
    """JPEG baytlarini rasmga aylantiradi yoki NoFaceDetectedError tashlaydi.

    Nima uchun alohida funksiya: cv2.imdecode buzuq bufer uchun None
    qaytaradi, lekin BO'SH bufer uchun cv2.error TASHLAYDI. Ikkala holat
    ham "kadrni o'qib bo'lmadi" degani, lekin ikkinchisi tutilmasa
    ishlov beruvchini butunlay yiqitadi.

    Bu ochiq sahifadagi jonli yo'naltirishda aniqlandi: brauzer video
    hali tayyor bo'lmaganda nol baytli kadr yuborishi mumkin, va u har
    safar 500 xatosini berardi. Kamera oqimida ham xuddi shu bo'lishi
    mumkin — ffmpeg uzilish paytida bo'sh kadr qaytaradi.
    """
    if not image_bytes:
        raise NoFaceDetectedError("Rasm bo'sh")
    # Kichik fayl juda katta o'lcham e'lon qilishi mumkin (masalan 2 MB JPEG
    # "60000×60000") — ochishdan oldin sarlavhadagi o'lcham tekshiriladi,
    # aks holda bitta ochiq so'rov gigabaytlab xotira egallardi.
    dims = _declared_dimensions(image_bytes)
    if dims is not None and dims[0] * dims[1] > MAX_DECODE_PIXELS:
        raise NoFaceDetectedError("Rasm juda katta — 50 megapikselgacha rasm yuboring")
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    try:
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except cv2.error as exc:
        raise NoFaceDetectedError("Rasm formatini o'qib bo'lmadi") from exc
    if img is None:
        raise NoFaceDetectedError("Rasm formatini o'qib bo'lmadi")
    return img


def _embed(image_bytes: bytes) -> tuple[np.ndarray | None, int]:
    img = _decode_image(image_bytes)
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


def _extract_enrollment_embedding_sync(frames: list[bytes]) -> list[float]:
    embeddings: list[np.ndarray] = []
    for i, frame in enumerate(frames):
        emb, count = _embed(frame)
        if emb is None:
            raise NoFaceDetectedError(f"{i + 1}-kadrda yuz aniqlanmadi ({count} ta yuz topildi)")
        embeddings.append(emb)

    reference = embeddings[0]
    for i, emb in enumerate(embeddings[1:], start=2):
        similarity = float(np.dot(reference, emb))  # both L2-normalized -> dot product is cosine similarity
        if similarity < ENROLLMENT_CONSISTENCY_THRESHOLD:
            raise InconsistentFacesError(
                f"{i}-kadr birinchi kadrdagi yuzga mos kelmadi — bir xil odam ekanligiga ishonch hosil qiling"
            )

    # Average the per-angle embeddings into one "prototype" vector — a
    # standard technique for multi-shot enrollment: it's more robust to any
    # single frame's noise (motion blur, a harsh shadow at one angle) than
    # picking just one frame, without needing to store N separate vectors
    # per person. Re-normalized since the mean of unit vectors isn't itself
    # unit length, and every consumer (face_matching.py) assumes normalized
    # embeddings for its dot-product-as-cosine-similarity shortcut.
    mean = np.mean(embeddings, axis=0)
    norm = np.linalg.norm(mean)
    prototype = mean / norm if norm > 0 else mean
    return prototype.tolist()


async def extract_enrollment_embedding(frames: list[bytes]) -> list[float]:
    """Multi-angle enrollment (app/routers/enrollment.py's public
    self-service flow): takes several frames of one capture session (e.g.
    straight-on, turned left, turned right) and returns one averaged
    embedding — see _extract_enrollment_embedding_sync for why averaging
    beats picking a single frame, and why the frames are cross-checked for
    consistency first. Gated by face_inference_gate with live priority,
    same as extract_embedding()."""
    async with face_inference_gate.slot(priority=PRIORITY_LIVE):
        return await asyncio.to_thread(_extract_enrollment_embedding_sync, frames)


@dataclass
class DetectedFace:
    # Ikkalasi ham None — yuz tahlil qilinmagan: juda kichik (min_face_px dan
    # past) yoki chaqiruvchi faqat aniqlashni so'ragan (analyse=False).
    # Tanish uchun recognizable_faces() dan o'tkaziladi.
    embedding: np.ndarray | None
    landmarks_68: np.ndarray | None  # (68, 3) — the standard iBUG scheme; see app/services/sleep_detection.py
    bbox: np.ndarray  # (4,) — [x1, y1, x2, y2] in the source image's pixel coordinates
    # True — oldingi kadrda tanilgan odam (skip_boxes), ataylab tahlil qilinmagan.
    tracked: bool = False
    # True — kuzatilayotgan yuz yaqinda tahlil qilingan ANIQ NOTANISH odamniki
    # (app/jobs/attendance_ai.py, unknown_skip).
    tracked_unknown: bool = False
    # Sifat o'lchovlari (faqat tahlil qilingan yuzlar uchun; aks holda None) —
    # face_quality_ok() ga qarang.
    det_score: float | None = None
    # Burilish: burun uchi ko'z o'rtasidan ko'zlar oralig'iga nisbatan qancha
    # siljigan (0 — to'g'ri qarab turibdi, ~0.5 — yarim profil).
    yaw: float | None = None
    # Hizalangan 112x112 kesimning Laplas dispersiyasi (xiralik o'lchovi).
    sharpness: float | None = None


def face_quality_ok(face) -> bool:
    """Yuz vektori ishonchli bo'lishi uchun yetarlicha sifatlimi.

    Faqat "yumshoq" moslik va avtomatik galereya uchun ishlatiladi
    (app/jobs/attendance_ai.py): qat'iy moslik o'z chegarasi bilan
    himoyalangan, uni sifat bo'yicha kesish tanishni kamaytirardi. Profil,
    xira yoki detektor ikkilangan yuzning ArcFace vektori boshqa odamnikiga
    tasodifan yaqin chiqishi mumkin — yumshoq chegarada aynan shu xavfli.
    Sifat o'lchanmagan (eski/soxta) yuz — tekshiruvdan o'tgan hisoblanadi."""
    if not settings.face_quality_gate_enabled:
        return True
    det_score = getattr(face, "det_score", None)
    if det_score is not None and det_score < settings.face_quality_min_det_score:
        return False
    yaw = getattr(face, "yaw", None)
    if yaw is not None and abs(yaw) > settings.face_quality_max_yaw:
        return False
    sharpness = getattr(face, "sharpness", None)
    if sharpness is not None and sharpness < settings.face_quality_min_sharpness:
        return False
    return True


def _yaw_from_kps(kps: np.ndarray) -> float | None:
    """5 nuqta: chap ko'z, o'ng ko'z, burun, og'iz chap/o'ng burchagi."""
    try:
        left_eye, right_eye, nose = kps[0], kps[1], kps[2]
    except (IndexError, TypeError):
        return None
    eye_distance = float(np.hypot(*(right_eye[:2] - left_eye[:2])))
    if eye_distance <= 1e-6:
        return None
    eye_mid_x = (float(left_eye[0]) + float(right_eye[0])) / 2.0
    return (float(nose[0]) - eye_mid_x) / eye_distance


def _sharpness(crop: np.ndarray) -> float:
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def detection_input_size(width: int, height: int) -> tuple[int, int] | None:
    """Detektor kirish o'lchami (w, h) — kadrning o'z nisbatida.

    Ilgari har kadr 640x640 ga siqilardi. Bu ikki tomonga ham yomon edi:
      * substream (640x360) kadr kvadratga to'ldirilib, 44% bo'sh piksel
        ham hisoblanardi;
      * asosiy oqim (1920x1080, 2560x1440) kadri 3-4 marta kichraytirilib,
        40 pikselli yuz 10-13 px bo'lib qolardi — detektor uni topmasdi.
    Endi kadr uzun tomoni face_det_max_side dan oshmaydigan qilib (kichik
    kadr — face_det_min_side gacha kattalashtiriladi, eski xatti-harakat
    kabi) o'z nisbatida, 32 ga karrali o'lchamda tahlil qilinadi.
    None — eski usul (prepare() dagi 640x640)."""
    if not settings.face_det_native_resolution or width <= 0 or height <= 0:
        return None
    long_side = max(width, height)
    max_side = max(32, settings.face_det_max_side)
    min_side = min(max(32, settings.face_det_min_side), max_side)
    scale = min(1.0, max_side / long_side)
    if long_side * scale < min_side:
        scale = min_side / long_side

    def up32(value: float) -> int:
        return max(32, int(np.ceil(value / 32.0)) * 32)

    return up32(width * scale), up32(height * scale)


def recognizable_faces(faces: list) -> list:
    """Embedding'i bor yuzlar — faqat ularni ro'yxat bilan solishtirish mumkin."""
    return [face for face in faces if getattr(face, "embedding", None) is not None]


Box = tuple[float, float, float, float]


def _iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = (float(v) for v in a[:4])
    bx1, by1, bx2, by2 = (float(v) for v in b[:4])
    width, height = min(ax2, bx2) - max(ax1, bx1), min(ay2, by2) - max(ay1, by1)
    if width <= 0 or height <= 0:
        return 0.0
    inter = width * height
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


TRACK_IOU = 0.4
"""Oldingi kadrda tanilgan yuz bilan shuncha ustma-ust tushgan yuz o'sha odam
hisoblanadi (kalit kadrlar ~1 s oraliqda — eshikdan o'tayotgan odam shu
vaqtda o'z yuzi o'lchamidan ko'p siljimaydi)."""


def _detect_faces_sync(
    image_bytes: bytes,
    min_face_px: int = 0,
    analyse: bool = True,
    roi: Box | None = None,
    skip_boxes: tuple[Box, ...] = (),
    landmarks: bool = True,
) -> list[DetectedFace]:
    """Every face in the frame (not just the largest) with its bounding box,
    and — for faces worth it — its embedding and 68-point landmarks.

    NEGA FaceAnalysis.get() EMAS. U HAR bir topilgan yuz uchun ArcFace R50
    embedding va 3D landmark hisoblaydi — 8 pikselli yuz uchun ham.
    Productionda (2026-09-18) 96 ta xona kamerasining 60 tasida yuzlar
    o'rtacha 8-20 px edi: tanib bo'lmaydi (chegara 40 px), lekin har biri
    to'liq R50 chaqiruvini olardi — AVX'siz CPU'da AI vaqtining asosiy
    qismi shunga ketardi. Endi get() ning o'zi takrorlanadi, faqat:

      * `min_face_px` dan kichik yuz — faqat bbox (tashxis uchun sanaladi);
      * `analyse=False` — hech bir yuz tahlil qilinmaydi (masalan niqob
        tekshiruvi faqat yuz o'rnini so'raydi);
      * embeddinglar bitta ONNX chaqiruvida (batch) hisoblanadi.

    Katta yuzlar uchun natija get() bilan aynan bir xil: o'sha hizalash
    (face_align.norm_crop), o'sha model va normallash.

    `roi` — normallashgan (x1, y1, x2, y2): faqat shu hudud to'liq
    sifatda tahlil qilinadi (kirish eshigi atrofi, Camera.face_roi). 4K
    kadrda detektor butun kadrni 640 px ga kichraytiradi va 60 px lik yuz
    ~10 px bo'lib qoladi; qirqilgan hududda o'sha yuz bir necha barobar
    katta ko'rinadi, hisob esa kamayadi. Natijadagi koordinatalar baribir
    TO'LIQ kadrga nisbatan.

    `skip_boxes` — oldingi kadrda allaqachon tanilgan yuzlar (to'liq kadr
    koordinatalarida). Ular bilan ustma-ust tushgan yuz qayta
    embedding qilinmaydi: bugun uning davomati yozilgan, olomonda esa bir
    odamni har soniyada qayta hisoblash CPU'ni behuda yeydi.

    `landmarks=False` — 68 nuqtali 3D belgilar hisoblanmaydi. Ularni faqat
    uyqu, frontallik va ro'yxatga olish o'qiydi; davomat esa yo'q. Model
    (1k3d68, 143 MB) har yuzga ~0.16 s oladi — ArcFace'ning deyarli
    yarmi (productionda o'lchandi, 2026-09-24)."""
    img = _decode_image(image_bytes)
    offset_x = offset_y = 0
    if roi is not None:
        height, width = img.shape[:2]
        x1, y1 = int(roi[0] * width), int(roi[1] * height)
        x2, y2 = max(int(roi[2] * width), x1 + 1), max(int(roi[3] * height), y1 + 1)
        img = np.ascontiguousarray(img[y1:y2, x1:x2])
        offset_x, offset_y = x1, y1
    offset = np.array([offset_x, offset_y, offset_x, offset_y], dtype=np.float32)
    app = _get_app()
    input_size = detection_input_size(img.shape[1], img.shape[0])
    if input_size is None:
        bboxes, kpss = app.det_model.detect(img, max_num=0, metric="default")
    else:
        bboxes, kpss = app.det_model.detect(img, input_size=input_size, max_num=0, metric="default")
    faces: list[DetectedFace] = []
    to_analyse: list[tuple[DetectedFace, Face]] = []
    for i in range(bboxes.shape[0]):
        local_bbox = bboxes[i, 0:4]
        face = DetectedFace(embedding=None, landmarks_68=None, bbox=local_bbox + offset)
        faces.append(face)
        kps = kpss[i] if kpss is not None else None
        face.det_score = float(bboxes[i, 4]) if bboxes.shape[1] > 4 else None
        if kps is not None:
            face.yaw = _yaw_from_kps(kps)
        if not analyse or kps is None or (local_bbox[3] - local_bbox[1]) < min_face_px:
            continue
        if any(_iou(face.bbox, box) >= TRACK_IOU for box in skip_boxes):
            face.tracked = True
            continue
        to_analyse.append((face, Face(bbox=local_bbox, kps=kps, det_score=bboxes[i, 4])))
    if not to_analyse:
        return faces

    recognition = app.models.get("recognition")
    if recognition is not None:
        size = recognition.input_size[0]
        crops = [face_align.norm_crop(img, landmark=raw.kps, image_size=size) for _, raw in to_analyse]
        for (face, _), crop in zip(to_analyse, crops, strict=True):
            face.sharpness = _sharpness(crop)
        for (face, _), feat in zip(to_analyse, recognition.get_feat(crops), strict=True):
            norm = np.linalg.norm(feat)
            face.embedding = feat / norm if norm > 0 else feat
    landmark_model = app.models.get("landmark_3d_68") if landmarks else None
    if landmark_model is not None:
        for face, raw in to_analyse:
            landmark_model.get(img, raw)
            points = raw.landmark_3d_68
            if points is not None and (offset_x or offset_y):
                points = points.copy()
                points[:, 0] += offset_x
                points[:, 1] += offset_y
            face.landmarks_68 = points
    return faces


def _min_face_px(min_face_px: int | None) -> int:
    return settings.face_analysis_min_px if min_face_px is None else max(0, min_face_px)


async def detect_faces(
    image_bytes: bytes,
    *,
    priority: int = PRIORITY_BACKGROUND,
    min_face_px: int | None = None,
    analyse: bool = True,
    roi: Box | None = None,
    skip_boxes: tuple[Box, ...] = (),
    landmarks: bool = True,
) -> list[DetectedFace]:
    """Gated by face_inference_gate — pass PRIORITY_LIVE for live-detection.

    `min_face_px` — shundan kichik yuz tahlil qilinmaydi (None:
    settings.face_analysis_min_px). Ro'yxatga olish kabi yuzning har
    burchagi kerak bo'lgan joylar 0 beradi. `analyse=False` — faqat bbox.
    `roi`, `skip_boxes`, `landmarks` — _detect_faces_sync izohiga qarang.

    Bir xil kadr uchun natija qisqa muddat eslab qolinadi
    (app/services/inference_cache.py): kadr tarixidan bir xil kadrni olgan
    bir nechta modul modelni qayta ishga tushirmaydi."""
    threshold = _min_face_px(min_face_px)
    key = (
        "faces",
        threshold,
        analyse,
        roi,
        tuple(tuple(round(float(v), 1) for v in box[:4]) for box in skip_boxes),
        landmarks,
    )

    async def run() -> list[DetectedFace]:
        async with face_inference_gate.slot(priority=priority):
            return await asyncio.to_thread(
                _detect_faces_sync, image_bytes, threshold, analyse, roi, tuple(skip_boxes), landmarks
            )

    return await inference_cache.get_or_run(image_bytes, key, run)


def _detect_faces_batch_sync(images: list[bytes], min_face_px: int = 0) -> list[list[DetectedFace]]:
    """Process multiple frames under one inference gate acquisition."""
    return [_detect_faces_sync(img, min_face_px) for img in images]


async def detect_faces_batch(
    image_bytes_list: list[bytes], *, priority: int = PRIORITY_BACKGROUND, min_face_px: int | None = None
) -> list[list[DetectedFace]]:
    """Batch face detection — chunks by face_recognition_batch_size."""
    if not image_bytes_list:
        return []
    batch_size = max(1, settings.face_recognition_batch_size)
    threshold = _min_face_px(min_face_px)
    all_results: list[list[DetectedFace]] = []
    async with face_inference_gate.slot(priority=priority):
        for i in range(0, len(image_bytes_list), batch_size):
            chunk = image_bytes_list[i : i + batch_size]
            chunk_results = await asyncio.to_thread(_detect_faces_batch_sync, chunk, threshold)
            all_results.extend(chunk_results)
    return all_results
