import json

import numpy as np
import pytest
from sqlalchemy import select

from app.models import Faculty, StudentStaff
from app.services.face_matching import CandidateMatrix, find_best_match, load_candidate_matrix

THRESHOLD = 0.55


class TestCandidateMatrixBestMatch:
    def test_empty_matrix_returns_none(self):
        empty = CandidateMatrix(ids=[], matrix=np.empty((0, 0)))
        assert empty.best_match([1.0, 0.0], THRESHOLD) is None

    def test_identical_vector_matches(self):
        matrix = CandidateMatrix(ids=["person-a"], matrix=np.array([[1.0, 0.0, 0.0]]))
        result = matrix.best_match([1.0, 0.0, 0.0], THRESHOLD)
        assert result == ("person-a", pytest.approx(1.0))

    def test_orthogonal_vector_is_below_threshold(self):
        matrix = CandidateMatrix(ids=["person-a"], matrix=np.array([[0.0, 1.0]]))
        assert matrix.best_match([1.0, 0.0], THRESHOLD) is None

    def test_picks_the_closer_of_two_candidates(self):
        matrix = CandidateMatrix(ids=["far", "close"], matrix=np.array([[0.0, 1.0], [0.99, 0.14]]))
        result = matrix.best_match([1.0, 0.0], THRESHOLD)
        assert result is not None
        assert result[0] == "close"


class TestCandidateMatrixBestMatches:
    """The vectorized, multi-face path — what run_attendance_ai_sweep_once
    and run_vision_ai_sweep_once actually call, since they compare every
    detected face against the candidate pool in one matrix multiply
    instead of one np.dot per (face, candidate) pair."""

    def test_each_face_gets_its_own_independent_match(self):
        matrix = CandidateMatrix(
            ids=["alice", "bob"], matrix=np.array([[1.0, 0.0], [0.0, 1.0]])
        )
        faces = np.array([[1.0, 0.0], [0.0, 1.0]])  # face 0 looks like alice, face 1 looks like bob
        results = matrix.best_matches(faces, THRESHOLD)
        assert results == [("alice", pytest.approx(1.0)), ("bob", pytest.approx(1.0))]

    def test_unmatched_face_among_matched_ones_gets_none(self):
        matrix = CandidateMatrix(ids=["alice"], matrix=np.array([[1.0, 0.0]]))
        faces = np.array([[1.0, 0.0], [0.0, 1.0]])  # face 0 matches alice, face 1 doesn't match anyone
        results = matrix.best_matches(faces, THRESHOLD)
        assert results[0] is not None and results[0][0] == "alice"
        assert results[1] is None

    def test_empty_candidates_returns_one_none_per_face(self):
        empty = CandidateMatrix(ids=[], matrix=np.empty((0, 0)))
        faces = np.array([[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]])
        assert empty.best_matches(faces, THRESHOLD) == [None, None, None]

    def test_no_faces_returns_empty_list(self):
        matrix = CandidateMatrix(ids=["alice"], matrix=np.array([[1.0, 0.0]]))
        assert matrix.best_matches(np.empty((0, 2)), THRESHOLD) == []


class TestFindBestMatchWrapper:
    def test_no_candidates_returns_none(self):
        assert find_best_match([1.0, 0.0], [], THRESHOLD) is None

    def test_matches_list_of_tuples_shape(self):
        result = find_best_match([1.0, 0.0, 0.0], [("person-a", [1.0, 0.0, 0.0])], THRESHOLD)
        assert result == ("person-a", pytest.approx(1.0))


@pytest.mark.usefixtures("seeded")
class TestLoadCandidateMatrix:
    async def test_no_enrolled_people_returns_empty_matrix(self, db_session):
        candidates = await load_candidate_matrix(db_session)
        assert candidates.is_empty

    async def test_loads_every_enrolled_embedding_once(self, db_session):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        a = StudentStaff(
            full_name="Birinchi", type="talaba", faculty_id=faculty.id, group_or_position="1",
            biometric_embedding=json.dumps([1.0, 0.0]),
        )
        b = StudentStaff(
            full_name="Ikkinchi", type="talaba", faculty_id=faculty.id, group_or_position="1",
            biometric_embedding=json.dumps([0.0, 1.0]),
        )
        unenrolled = StudentStaff(
            full_name="Ro'yxatga olinmagan", type="talaba", faculty_id=faculty.id, group_or_position="1",
        )
        db_session.add_all([a, b, unenrolled])
        await db_session.commit()

        candidates = await load_candidate_matrix(db_session)
        assert not candidates.is_empty
        assert set(candidates.ids) == {str(a.id), str(b.id)}
        assert candidates.matrix.shape == (2, 2)
