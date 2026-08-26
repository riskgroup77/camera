"""P3 feature tests — FAISS path, MediaMTX sharding, heuristic detectors."""

import numpy as np

from app.services.face_matching import CandidateMatrix, _maybe_build_faiss_index
from app.services.video_gateway import _shard_index


class TestFaissMatching:
    def test_faiss_and_matmul_agree_on_small_set(self, monkeypatch):
        monkeypatch.setattr("app.services.face_matching.settings.face_match_faiss_min_size", 3)
        ids = ["a", "b", "c"]
        matrix = np.random.randn(3, 512).astype(np.float64)
        matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
        index = _maybe_build_faiss_index(matrix)
        cm = CandidateMatrix(ids=ids, matrix=matrix, _faiss_index=index)
        query = matrix[1:2]
        faiss_match = cm.best_matches(query, threshold=0.0)[0]
        cm_plain = CandidateMatrix(ids=ids, matrix=matrix)
        matmul_match = cm_plain.best_matches(query, threshold=0.0)[0]
        assert faiss_match is not None and matmul_match is not None
        assert faiss_match[0] == matmul_match[0]


class TestMediaMTXSharding:
    def test_shard_index_is_stable(self):
        a = _shard_index("camera-uuid-1", 3)
        b = _shard_index("camera-uuid-1", 3)
        assert a == b
        assert 0 <= a < 3
