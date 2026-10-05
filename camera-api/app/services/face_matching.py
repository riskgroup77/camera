"""Matches detected faces against the enrolled population — shared by
app/jobs/attendance_ai.py and app/jobs/vision_ai.py, which both need to
answer "who (if anyone) is this face?" against the same
StudentStaff.biometric_embedding pool.

At 10k+ enrolled people, exact numpy matmul is still correct but heavy;
when N >= face_match_faiss_min_size and faiss-cpu is installed, an
IndexFlatIP approximate path is used (exact for normalized vectors).
"""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import FaceGalleryEmbedding, StudentStaff
from app.redis_bus import _get_redis, _redis_url

logger = logging.getLogger("app.face_matching")

try:
    import faiss

    _FAISS_AVAILABLE = True
except ImportError:
    faiss = None  # type: ignore[assignment,misc]
    _FAISS_AVAILABLE = False


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    """L2 normallashtirish. Ro'yxatga olingan vektorlar allaqachon normal
    (face_recognition.py), lekin nuqta ko'paytma kosinus o'xshashlik bo'lishi
    faqat shu shartda to'g'ri — tashqi import yoki eski yozuv normal
    bo'lmasa, o'xshashlik jimgina buziladi. Arzon himoya."""
    if matrix.ndim != 2 or matrix.shape[0] == 0:
        return matrix
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


@dataclass
class GradedMatch:
    person_id: str | None
    similarity: float
    second_similarity: float
    grade: str  # 'strict' | 'relaxed' | 'none'
    # Asl ro'yxat rasmi bilan o'xshashlik (galereya bo'lmasa = similarity).
    anchor_similarity: float | None = None
    # True — natija bitta kadrdan emas, yuz izining birlashtirilgan
    # vektoridan (app/services/face_tracks.py).
    fused: bool = False


@dataclass
class CandidateMatrix:
    ids: list[str]
    matrix: np.ndarray  # shape (N, 512) — rows are L2-normalized ArcFace embeddings
    person_types: dict[str, str] | None = None  # id -> 'talaba' | 'xodim'
    _faiss_index: object | None = field(default=None, repr=False, compare=False)
    # Galereya (app/services/face_gallery.py): matritsada bir odamga bir necha
    # qator bo'lishi mumkin. Qatorlar odam bo'yicha guruhlangan; group_starts[k]
    # — k-odamning birinchi (ASL rasm) qatori. None — har qator = bitta odam.
    group_starts: np.ndarray | None = field(default=None, repr=False, compare=False)

    @property
    def has_gallery(self) -> bool:
        return self.group_starts is not None and len(self.group_starts) < self.matrix.shape[0]

    def _person_similarities(self, embeddings: np.ndarray) -> np.ndarray:
        """(yuzlar, odamlar) — har odam uchun uning barcha namunalaridan eng yaqini."""
        similarities = embeddings @ self.matrix.T
        if self.group_starts is None:
            return similarities
        return np.maximum.reduceat(similarities, self.group_starts, axis=1)

    def anchor_similarities(self, embeddings: np.ndarray, person_indices: np.ndarray) -> np.ndarray:
        """Har yuzning ko'rsatilgan odamning ASL rasmi bilan o'xshashligi."""
        embeddings = _normalize_rows(np.asarray(embeddings, dtype=np.float64))
        indices = np.asarray(person_indices, dtype=np.int64)
        rows = indices if self.group_starts is None else self.group_starts[indices]
        return np.einsum("ij,ij->i", embeddings, self.matrix[rows])

    @property
    def is_empty(self) -> bool:
        return len(self.ids) == 0

    def person_type(self, person_id: str) -> str | None:
        if self.person_types is None:
            return None
        return self.person_types.get(person_id)

    def top_two(self, embeddings: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Har bir yuz uchun eng yaqin ikki nomzod: (eng_yaqin_indeks,
        eng_yaqin_o'xshashlik, ikkinchi_o'xshashlik). Ikkinchisi — "ajralish"
        (margin) uchun: eng yaqin nomzod qolganlardan qanchalik uzoqlashgani
        moslikka ishonchning o'zi. Bitta nomzod bo'lsa ikkinchisi -1."""
        embeddings = _normalize_rows(np.asarray(embeddings, dtype=np.float64))
        n = len(self.ids)
        if self._faiss_index is not None and _FAISS_AVAILABLE and self.group_starts is None:
            k = 2 if n >= 2 else 1
            sims, indices = self._faiss_index.search(embeddings.astype(np.float32), k)  # type: ignore[union-attr]
            best_idx = indices[:, 0].astype(np.int64)
            best_sim = sims[:, 0].astype(np.float64)
            second = sims[:, 1].astype(np.float64) if k == 2 else np.full(len(embeddings), -1.0)
            return best_idx, best_sim, second

        similarities = self._person_similarities(embeddings)
        best_idx = np.argmax(similarities, axis=1)
        rows = np.arange(len(embeddings))
        best_sim = similarities[rows, best_idx]
        if n >= 2:
            masked = similarities.copy()
            masked[rows, best_idx] = -np.inf
            second = masked.max(axis=1)
        else:
            second = np.full(len(embeddings), -1.0)
        return best_idx, best_sim, second

    def best_matches(
        self, embeddings: np.ndarray, threshold: float, *, margin: float = 0.0
    ) -> list[tuple[str, float] | None]:
        """`margin` berilsa, eng yaqin nomzod ikkinchisidan shuncha uzoq
        bo'lishi shart. Odamning ISMI yoziladigan joylarda (uxlab qolish
        signali, o'qituvchi o'rniga boshqasi) shu shart qo'yiladi:
        chegara pasaytirilgandan keyin (2026-09-16) "ikki nomzod deyarli
        barobar" holati noto'g'ri odamni nomlash xavfini tug'diradi."""
        if self.is_empty or len(embeddings) == 0:
            return [None] * len(embeddings)
        best_idx, best_sim, second = self.top_two(embeddings)
        return [
            (self.ids[int(i)], float(s))
            if int(i) >= 0 and s >= threshold and (s - s2) >= margin
            else None
            for i, s, s2 in zip(best_idx, best_sim, second, strict=True)
        ]

    def graded_matches(
        self,
        embeddings: np.ndarray,
        *,
        strict_threshold: float,
        relaxed_threshold: float,
        margin: float,
        strict_margin: float = 0.0,
    ) -> list["GradedMatch"]:
        """Har bir yuz uchun baholangan natija (hech qachon None emas —
        statistika uchun eng yaqin o'xshashlik ham kerak).

        * strict  — o'xshashlik >= strict_threshold VA eng yaqin nomzod
          ikkinchisidan kamida `strict_margin` ga uzoq. Margin qat'iy
          yo'lga 2026-09-16 kalibrlashda qo'shildi: chegara pasaytirilgach
          (0.55 -> 0.50) "ikki nomzod deyarli barobar" holati xavfli
          bo'ladi, ya'ni raqam yetarli, lekin QAYSI odam ekani noaniq.
          Bunday yuz umuman hisobga olinmaydi — noto'g'ri odamga davomat
          yozgandan ko'ra yozmagan yaxshi.
        * relaxed — relaxed_threshold <= o'xshashlik < strict_threshold VA
          eng yaqin nomzod ikkinchisidan kamida `margin` ga uzoq. CCTV
          kadridagi kichik/qiya yuz odatda 0.45-0.55 oralig'ida qoladi —
          qat'iy 0.55 chegara ro'yxatdan o'tgan odamni ham "tanimaydi".
          Bunday moslik bir marta yetarli emas: chaqiruvchi uni takroriy
          ko'rinish bilan tasdiqlashi kerak (app/services/recognition_stats.py).
        * none    — tanilmadi."""
        if self.is_empty or len(embeddings) == 0:
            return [GradedMatch(None, -1.0, -1.0, "none") for _ in range(len(embeddings))]
        best_idx, best_sim, second = self.top_two(embeddings)
        if self.has_gallery:
            anchors = self.anchor_similarities(embeddings, np.clip(best_idx, 0, None))
        else:
            anchors = best_sim
        floor = settings.face_gallery_anchor_floor
        out: list[GradedMatch] = []
        for i, s, s2, a in zip(best_idx, best_sim, second, anchors, strict=True):
            idx = int(i)
            sim = float(s)
            sim2 = float(s2)
            anchor = float(a)
            if idx < 0:
                out.append(GradedMatch(None, -1.0, -1.0, "none"))
            elif self.has_gallery and anchor < floor:
                # Faqat galereya namunasi orqali topilgan, asl rasmga esa
                # deyarli o'xshamaydi — namunaga ishonib nom berilmaydi.
                out.append(GradedMatch(None, sim, sim2, "none", anchor))
            elif sim >= strict_threshold and (sim - sim2) >= strict_margin:
                out.append(GradedMatch(self.ids[idx], sim, sim2, "strict", anchor))
            elif sim >= relaxed_threshold and (sim - sim2) >= margin:
                out.append(GradedMatch(self.ids[idx], sim, sim2, "relaxed", anchor))
            else:
                out.append(GradedMatch(None, sim, sim2, "none", anchor))
        return out

    def best_match(
        self, embedding: list[float] | np.ndarray, threshold: float, *, margin: float = 0.0
    ) -> tuple[str, float] | None:
        return self.best_matches(np.array([embedding]), threshold, margin=margin)[0]


def _maybe_build_faiss_index(matrix: np.ndarray) -> object | None:
    if not _FAISS_AVAILABLE or matrix.shape[0] < settings.face_match_faiss_min_size:
        return None
    index = faiss.IndexFlatIP(matrix.shape[1])  # type: ignore[union-attr]
    index.add(matrix.astype(np.float32))
    return index


def anchor_hash(embedding_json: str) -> str:
    """Asl vektor matnining xeshi — galereya namunasi qaysi rasmga bog'liq."""
    return hashlib.sha256(embedding_json.encode("utf-8")).hexdigest()


def _build_with_gallery(rows: list, gallery_rows: list) -> CandidateMatrix | None:
    """Galereyali matritsa; mos namuna bo'lmasa None."""
    hashes = {str(row_id): anchor_hash(embedding_json) for row_id, embedding_json, _ in rows}
    extra: dict[str, list[str]] = {}
    for person_id, embedding_json, row_hash in gallery_rows:
        key = str(person_id)
        if hashes.get(key) == row_hash:
            extra.setdefault(key, []).append(embedding_json)
    if not extra:
        return None
    ids: list[str] = []
    vectors: list[list[float]] = []
    starts: list[int] = []
    person_types: dict[str, str] = {}
    for row_id, embedding_json, person_type in rows:
        key = str(row_id)
        ids.append(key)
        person_types[key] = person_type
        starts.append(len(vectors))
        vectors.append(json.loads(embedding_json))
        vectors.extend(json.loads(item) for item in extra.get(key, ()))
    matrix = _normalize_rows(np.array(vectors, dtype=np.float64))
    return CandidateMatrix(
        ids=ids, matrix=matrix, person_types=person_types, group_starts=np.array(starts, dtype=np.int64)
    )


def _build_candidate_matrix(rows: list, gallery_rows: list | None = None) -> CandidateMatrix:
    """JSON matnlaridan matritsa — CPU ishi (10 000 odam × 512 son), shuning
    uchun chaqiruvchi uni alohida oqimda bajaradi: event loop'da bir necha
    soniya turib qolsa, shu vaqt ichida API ham, sweeplar ham to'xtaydi.

    `gallery_rows` — (odam_id, vektor_json, anchor_hash) kamera namunalari
    (app/services/face_gallery.py); faqat asl vektori hozirgisi bilan bir xil
    bo'lganlari qo'shiladi."""
    if gallery_rows:
        with_gallery = _build_with_gallery(rows, gallery_rows)
        if with_gallery is not None:
            return with_gallery
    ids = [str(row_id) for row_id, _, _ in rows]
    matrix = _normalize_rows(np.array([json.loads(embedding_json) for _, embedding_json, _ in rows], dtype=np.float64))
    person_types = {str(row_id): person_type for row_id, _, person_type in rows}
    faiss_index = _maybe_build_faiss_index(matrix)
    if faiss_index is not None:
        logger.debug("FAISS index built", extra={"candidates": len(ids)})
    return CandidateMatrix(ids=ids, matrix=matrix, person_types=person_types, _faiss_index=faiss_index)


async def matrix_from_rows(rows: list) -> CandidateMatrix:
    """(id, embedding_json, type) qatorlaridan matritsa — kichik ro'yxatlar
    uchun ham (masalan bitta darsning guruhi va o'qituvchisi)."""
    if not rows:
        return CandidateMatrix(ids=[], matrix=np.empty((0, 0)), person_types={})
    return await asyncio.to_thread(_build_candidate_matrix, rows)


async def load_candidate_matrix(db: AsyncSession) -> CandidateMatrix:
    result = await db.execute(
        select(StudentStaff.id, StudentStaff.biometric_embedding, StudentStaff.type).where(
            StudentStaff.biometric_embedding.is_not(None),
            # Faolsizlantirilgan (bitirgan, ishdan ketgan) odam tanilmaydi —
            # biometrikasi saqlash muddatigacha bazada tursa ham
            # (app/jobs/cleanup.py). Faollik o'zgarganda
            # app/routers/privacy.py announce_roster_change() ni chaqiradi.
            StudentStaff.active.is_(True),
            # Tekshiruvda turgan yuz tanilmaydi. 2026-09-20 gacha bu faqat
            # o'zini o'zi ro'yxatdan o'tkazganlarga tegishli edi: ro'yxatdagi
            # odam uchun topshirilgan shubhali yuz ("kutilmoqda") baribir
            # tanish ro'yxatida qolardi, ya'ni tekshiruvga qo'yishning
            # ma'nosi yo'q edi (app/routers/enrollment.py).
            StudentStaff.biometrics_status != "kutilmoqda",
        )
    )
    rows = result.all()
    if not rows:
        return CandidateMatrix(ids=[], matrix=np.empty((0, 0)), person_types={})
    gallery_rows: list = []
    if settings.face_gallery_enabled:
        gallery_rows = list(
            (
                await db.execute(
                    select(
                        FaceGalleryEmbedding.student_staff_id,
                        FaceGalleryEmbedding.embedding,
                        FaceGalleryEmbedding.anchor_hash,
                    ).order_by(FaceGalleryEmbedding.created_at)
                )
            ).all()
        )
    return await asyncio.to_thread(_build_candidate_matrix, rows, gallery_rows)


# Ro'yxat versiyasi — worker'lar o'rtasida kesh bekor qilinishini ulashish.
#
# Productionda ikkita API jarayoni bor, AI sweeplari esa faqat bittasida.
# Odam o'chirilganda yoki yuzi qayta tasdiqlanganda so'rov IKKINCHI
# jarayonga tushsa, uning xotirasidagi keshni tozalash AI jarayoniga yetib
# bormasdi — o'chirilgan odam yana 5 daqiqagacha tanilardi. Endi
# o'zgarish Redis'dagi hisoblagichni oshiradi, har bir jarayon keshni
# ishlatishdan oldin uni solishtiradi (bitta GET).
ROSTER_VERSION_KEY = "camera:faces:roster_version"


@dataclass
class _CacheSlot:
    ttl_setting: str
    matrix: CandidateMatrix | None = None
    loaded_at: datetime | None = None
    version: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def clear(self) -> None:
        self.matrix = None
        self.loaded_at = None
        self.version = None

    def is_fresh(self, now: datetime, version: str | None) -> bool:
        if self.matrix is None or self.loaded_at is None:
            return False
        if (now - self.loaded_at).total_seconds() > getattr(settings, self.ttl_setting):
            return False
        return version is None or version == self.version

    async def get(self, db: AsyncSession) -> CandidateMatrix:
        version = await _roster_version()
        if self.is_fresh(datetime.now(timezone.utc), version):
            return self.matrix
        # Muddati bir vaqtda tugagan bir nechta sweep bazani birdaniga
        # o'qimasligi uchun: birinchisi yuklaydi, qolganlari uni kutadi.
        async with self.lock:
            now = datetime.now(timezone.utc)
            if not self.is_fresh(now, version):
                self.matrix = await load_candidate_matrix(db)
                self.loaded_at = now
                self.version = version
            return self.matrix


_live_cache = _CacheSlot("candidate_matrix_cache_ttl_seconds")
_sweep_cache = _CacheSlot("candidate_matrix_sweep_cache_ttl_seconds")


async def _roster_version() -> str | None:
    """Redis'dagi ro'yxat versiyasi; Redis yo'q bo'lsa None (bitta
    jarayonli o'rnatish — mahalliy bekor qilish yetarli)."""
    if not _redis_url():
        return None
    client = await _get_redis()
    if client is None:
        return None
    try:
        return str(await client.get(ROSTER_VERSION_KEY) or "0")
    except Exception:
        logger.warning("could not read face roster version", exc_info=True)
        return None


async def load_candidate_matrix_cached(db: AsyncSession) -> CandidateMatrix:
    return await _live_cache.get(db)


async def load_candidate_matrix_for_sweep(db: AsyncSession) -> CandidateMatrix:
    """Longer-TTL cache for AI sweep loops — one DB read per few minutes
    instead of every camera tick across 10k+ enrolled embeddings."""
    matrix = await _sweep_cache.get(db)
    logger.debug("sweep candidate matrix ready", extra={"candidates": len(matrix.ids)})
    return matrix


def invalidate_candidate_matrix_cache() -> None:
    """Faqat SHU jarayonning keshi. Ro'yxat o'zgarganda
    announce_roster_change() ni chaqiring — u boshqa jarayonlarga ham yetadi."""
    _live_cache.clear()
    _sweep_cache.clear()


async def announce_roster_change() -> None:
    """Yuzlar ro'yxati o'zgardi (odam qo'shildi, o'chirildi, yuzi yoki turi
    o'zgardi) — barcha API jarayonlaridagi kesh keyingi so'rovda qayta
    yuklanadi. Redis ishlamasa, kamida shu jarayonniki tozalanadi."""
    invalidate_candidate_matrix_cache()
    if not _redis_url():
        return
    client = await _get_redis()
    if client is None:
        return
    try:
        await client.incr(ROSTER_VERSION_KEY)
    except Exception:
        logger.warning("could not publish face roster change", exc_info=True)


def find_best_match(
    embedding: list[float], candidates: list[tuple[str, list[float]]], threshold: float
) -> tuple[str, float] | None:
    if not candidates:
        return None
    ids = [c[0] for c in candidates]
    matrix = _normalize_rows(np.array([c[1] for c in candidates], dtype=np.float64))
    cm = CandidateMatrix(ids=ids, matrix=matrix, _faiss_index=_maybe_build_faiss_index(matrix))
    return cm.best_match(embedding, threshold)
