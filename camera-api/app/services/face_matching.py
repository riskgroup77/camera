"""Matches detected faces against the enrolled population — shared by
app/jobs/attendance_ai.py and app/jobs/vision_ai.py, which both need to
answer "who (if anyone) is this face?" against the same
StudentStaff.biometric_embedding pool.

At 10k+ enrolled people, exact numpy matmul is still correct but heavy;
when N >= face_match_faiss_min_size and faiss-cpu is installed, an
IndexFlatIP approximate path is used (exact for normalized vectors).
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import StudentStaff

logger = logging.getLogger("app.face_matching")

try:
    import faiss

    _FAISS_AVAILABLE = True
except ImportError:
    faiss = None  # type: ignore[assignment,misc]
    _FAISS_AVAILABLE = False


@dataclass
class CandidateMatrix:
    ids: list[str]
    matrix: np.ndarray  # shape (N, 512) — rows are L2-normalized ArcFace embeddings
    person_types: dict[str, str] | None = None  # id -> 'talaba' | 'xodim'
    _faiss_index: object | None = field(default=None, repr=False, compare=False)

    @property
    def is_empty(self) -> bool:
        return len(self.ids) == 0

    def person_type(self, person_id: str) -> str | None:
        if self.person_types is None:
            return None
        return self.person_types.get(person_id)

    def best_matches(self, embeddings: np.ndarray, threshold: float) -> list[tuple[str, float] | None]:
        if self.is_empty or len(embeddings) == 0:
            return [None] * len(embeddings)

        if self._faiss_index is not None and _FAISS_AVAILABLE:
            query = embeddings.astype(np.float32)
            sims, indices = self._faiss_index.search(query, 1)  # type: ignore[union-attr]
            out: list[tuple[str, float] | None] = []
            for sim_row, idx_row in zip(sims, indices, strict=True):
                sim = float(sim_row[0])
                idx = int(idx_row[0])
                if idx < 0 or sim < threshold:
                    out.append(None)
                else:
                    out.append((self.ids[idx], sim))
            return out

        similarities = embeddings @ self.matrix.T
        best_idx = np.argmax(similarities, axis=1)
        best_sim = similarities[np.arange(len(embeddings)), best_idx]
        return [
            (self.ids[i], float(s)) if s >= threshold else None for i, s in zip(best_idx, best_sim, strict=True)
        ]

    def best_match(self, embedding: list[float] | np.ndarray, threshold: float) -> tuple[str, float] | None:
        return self.best_matches(np.array([embedding]), threshold)[0]


def _maybe_build_faiss_index(matrix: np.ndarray) -> object | None:
    if not _FAISS_AVAILABLE or matrix.shape[0] < settings.face_match_faiss_min_size:
        return None
    index = faiss.IndexFlatIP(matrix.shape[1])  # type: ignore[union-attr]
    index.add(matrix.astype(np.float32))
    return index


async def load_candidate_matrix(db: AsyncSession) -> CandidateMatrix:
    result = await db.execute(
        select(StudentStaff.id, StudentStaff.biometric_embedding, StudentStaff.type).where(
            StudentStaff.biometric_embedding.is_not(None)
        )
    )
    rows = result.all()
    if not rows:
        return CandidateMatrix(ids=[], matrix=np.empty((0, 0)), person_types={})

    ids = [str(row_id) for row_id, _, _ in rows]
    matrix = np.array([json.loads(embedding_json) for _, embedding_json, _ in rows], dtype=np.float64)
    person_types = {str(row_id): person_type for row_id, _, person_type in rows}
    faiss_index = _maybe_build_faiss_index(matrix)
    if faiss_index is not None:
        logger.debug("FAISS index built", extra={"candidates": len(ids)})
    return CandidateMatrix(ids=ids, matrix=matrix, person_types=person_types, _faiss_index=faiss_index)


CANDIDATE_MATRIX_CACHE_TTL_SECONDS = 30

_cache: CandidateMatrix | None = None
_cache_loaded_at: datetime | None = None


async def load_candidate_matrix_cached(db: AsyncSession) -> CandidateMatrix:
    global _cache, _cache_loaded_at
    now = datetime.now(timezone.utc)
    if (
        _cache is None
        or _cache_loaded_at is None
        or (now - _cache_loaded_at).total_seconds() > CANDIDATE_MATRIX_CACHE_TTL_SECONDS
    ):
        _cache = await load_candidate_matrix(db)
        _cache_loaded_at = now
    return _cache


def invalidate_candidate_matrix_cache() -> None:
    global _cache, _cache_loaded_at
    _cache = None
    _cache_loaded_at = None


def find_best_match(
    embedding: list[float], candidates: list[tuple[str, list[float]]], threshold: float
) -> tuple[str, float] | None:
    if not candidates:
        return None
    ids = [c[0] for c in candidates]
    matrix = np.array([c[1] for c in candidates], dtype=np.float64)
    cm = CandidateMatrix(ids=ids, matrix=matrix, _faiss_index=_maybe_build_faiss_index(matrix))
    return cm.best_match(embedding, threshold)
