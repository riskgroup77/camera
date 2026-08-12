"""Matches detected faces against the enrolled population — shared by
app/jobs/attendance_ai.py and app/jobs/vision_ai.py, which both need to
answer "who (if anyone) is this face?" against the same
StudentStaff.biometric_embedding pool.

Replaces an earlier version of this logic (a plain Python for-loop
computing one np.dot per candidate) that does not scale: at 10,000+
enrolled people, comparing a single detected face meant 10,000 sequential
Python-level dot products, repeated for every face in every camera's
frame, every sweep tick, on every camera. CandidateMatrix instead loads
every embedding into one (N, 512) numpy array and does the whole
comparison as a single matrix multiply (BLAS-backed, not a Python loop) —
one np.ndarray.__matmul__ call replaces N Python-level operations. Still
O(N) work overall (this is exact nearest-neighbor, not an approximate
index), but the constant factor drops by orders of magnitude, and it lets
a sweep loop load the candidate pool ONCE per sweep instead of once per
camera (see run_attendance_ai_sweep_once/run_vision_ai_sweep_once), which
matters just as much at hundreds of cameras: that was hundreds of
redundant DB round-trips and JSON-parses of the same data every tick.

If the enrolled population grows well past what an exact matrix multiply
can do in real time (tens of thousands+), the next step is an approximate
nearest-neighbor index (FAISS or pgvector's ANN index) instead of this
exact search — noted here rather than built preemptively, since it adds
real complexity (index rebuilds on enrollment changes) that isn't
justified until measured to be necessary.
"""

import json
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import StudentStaff


@dataclass
class CandidateMatrix:
    ids: list[str]
    matrix: np.ndarray  # shape (N, 512) — rows are L2-normalized ArcFace embeddings

    @property
    def is_empty(self) -> bool:
        return len(self.ids) == 0

    def best_matches(self, embeddings: np.ndarray, threshold: float) -> list[tuple[str, float] | None]:
        """embeddings: shape (F, 512), one row per detected face. Returns
        one (student_staff_id, similarity) or None per row, in order — the
        vectorized equivalent of calling best_match() once per face."""
        if self.is_empty or len(embeddings) == 0:
            return [None] * len(embeddings)

        similarities = embeddings @ self.matrix.T  # (F, N) — cosine similarity, both sides L2-normalized
        best_idx = np.argmax(similarities, axis=1)
        best_sim = similarities[np.arange(len(embeddings)), best_idx]
        return [
            (self.ids[i], float(s)) if s >= threshold else None for i, s in zip(best_idx, best_sim, strict=True)
        ]

    def best_match(self, embedding: list[float] | np.ndarray, threshold: float) -> tuple[str, float] | None:
        return self.best_matches(np.array([embedding]), threshold)[0]


async def load_candidate_matrix(db: AsyncSession) -> CandidateMatrix:
    result = await db.execute(
        select(StudentStaff.id, StudentStaff.biometric_embedding).where(
            StudentStaff.biometric_embedding.is_not(None)
        )
    )
    rows = result.all()
    if not rows:
        return CandidateMatrix(ids=[], matrix=np.empty((0, 0)))

    ids = [str(row_id) for row_id, _ in rows]
    matrix = np.array([json.loads(embedding_json) for _, embedding_json in rows], dtype=np.float64)
    return CandidateMatrix(ids=ids, matrix=matrix)


def find_best_match(
    embedding: list[float], candidates: list[tuple[str, list[float]]], threshold: float
) -> tuple[str, float] | None:
    """Single-embedding, list-of-tuples convenience wrapper kept for
    callers that already have candidates in that shape (mainly tests) —
    builds a CandidateMatrix on the fly. Sweep loops should use
    load_candidate_matrix()/CandidateMatrix.best_matches() directly and
    reuse the matrix across every face/camera in the sweep instead of
    rebuilding it on every call, which is what this wrapper does."""
    if not candidates:
        return None
    ids = [c[0] for c in candidates]
    matrix = np.array([c[1] for c in candidates], dtype=np.float64)
    return CandidateMatrix(ids=ids, matrix=matrix).best_match(embedding, threshold)
