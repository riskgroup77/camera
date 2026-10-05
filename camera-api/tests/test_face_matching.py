import asyncio
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy import select

from app.models import Faculty, StudentStaff
from app.services import face_matching
from app.services.face_matching import (
    CandidateMatrix,
    find_best_match,
    invalidate_candidate_matrix_cache,
    load_candidate_matrix,
    load_candidate_matrix_cached,
    load_candidate_matrix_for_sweep,
)
from app.config import settings

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


@pytest.mark.usefixtures("seeded")
class TestLoadCandidateMatrixCached:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        # Module-level cache is a process-wide global -- isolate each test
        # from whatever an earlier test left behind, and from whatever the
        # next one expects to find empty.
        invalidate_candidate_matrix_cache()
        yield
        invalidate_candidate_matrix_cache()

    async def _enroll_one(self, db_session, faculty, name="Birinchi"):
        person = StudentStaff(
            full_name=name, type="talaba", faculty_id=faculty.id, group_or_position="1",
            biometric_embedding=json.dumps([1.0, 0.0]),
        )
        db_session.add(person)
        await db_session.commit()
        return person

    async def test_first_call_loads_from_db(self, db_session):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        person = await self._enroll_one(db_session, faculty)

        candidates = await load_candidate_matrix_cached(db_session)
        assert candidates.ids == [str(person.id)]

    async def test_second_call_within_ttl_reuses_the_cached_matrix(self, db_session, monkeypatch):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        await self._enroll_one(db_session, faculty)
        await load_candidate_matrix_cached(db_session)  # warms the cache

        calls = {"n": 0}
        real_load = face_matching.load_candidate_matrix

        async def counting_load(db):
            calls["n"] += 1
            return await real_load(db)

        monkeypatch.setattr(face_matching, "load_candidate_matrix", counting_load)

        # A second enrolled person exists in the DB now, but the cache is
        # still fresh -- the stale result (only the first person) proves
        # the DB wasn't hit again, not just that the count matches.
        second = await self._enroll_one(db_session, faculty, name="Ikkinchi")
        candidates = await load_candidate_matrix_cached(db_session)
        assert calls["n"] == 0
        assert str(second.id) not in candidates.ids

    async def test_expired_ttl_forces_a_fresh_reload(self, db_session):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        await self._enroll_one(db_session, faculty)
        await load_candidate_matrix_cached(db_session)

        # Simulate the TTL having elapsed without needing a real sleep.
        face_matching._live_cache.loaded_at = datetime.now(timezone.utc) - timedelta(
            seconds=settings.candidate_matrix_cache_ttl_seconds + 1
        )

        second = await self._enroll_one(db_session, faculty, name="Ikkinchi")
        candidates = await load_candidate_matrix_cached(db_session)
        assert str(second.id) in candidates.ids

    async def test_invalidate_forces_a_fresh_reload_immediately(self, db_session):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        await self._enroll_one(db_session, faculty)
        await load_candidate_matrix_cached(db_session)

        second = await self._enroll_one(db_session, faculty, name="Ikkinchi")
        invalidate_candidate_matrix_cache()

        candidates = await load_candidate_matrix_cached(db_session)
        assert str(second.id) in candidates.ids


@pytest.mark.usefixtures("seeded")
class TestLoadCandidateMatrixForSweep:
    @pytest.fixture(autouse=True)
    def _reset_cache(self):
        invalidate_candidate_matrix_cache()
        yield
        invalidate_candidate_matrix_cache()

    async def _enroll_one(self, db_session, faculty, name="Birinchi"):
        person = StudentStaff(
            full_name=name, type="talaba", faculty_id=faculty.id, group_or_position="1",
            biometric_embedding=json.dumps([1.0, 0.0]),
        )
        db_session.add(person)
        await db_session.commit()
        return person

    async def test_sweep_cache_reuses_matrix_within_long_ttl(self, db_session, monkeypatch):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        await self._enroll_one(db_session, faculty)
        await load_candidate_matrix_for_sweep(db_session)

        calls = {"n": 0}
        real_load = face_matching.load_candidate_matrix

        async def counting_load(db):
            calls["n"] += 1
            return await real_load(db)

        monkeypatch.setattr(face_matching, "load_candidate_matrix", counting_load)
        await self._enroll_one(db_session, faculty, name="Ikkinchi")

        candidates = await load_candidate_matrix_for_sweep(db_session)
        assert calls["n"] == 0
        assert len(candidates.ids) == 1

    async def test_invalidate_clears_sweep_cache(self, db_session):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        await self._enroll_one(db_session, faculty)
        await load_candidate_matrix_for_sweep(db_session)
        second = await self._enroll_one(db_session, faculty, name="Ikkinchi")
        invalidate_candidate_matrix_cache()
        candidates = await load_candidate_matrix_for_sweep(db_session)
        assert str(second.id) in candidates.ids

    async def test_live_and_sweep_caches_are_independent(self, db_session):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        person = await self._enroll_one(db_session, faculty)
        sweep = await load_candidate_matrix_for_sweep(db_session)
        live = await load_candidate_matrix_cached(db_session)
        assert sweep.ids == live.ids == [str(person.id)]


class _FakeRedis:
    def __init__(self):
        self.values: dict[str, int] = {}

    async def get(self, key):
        value = self.values.get(key)
        return None if value is None else str(value)

    async def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]


@pytest.mark.usefixtures("seeded")
class TestRosterChangeReachesEveryWorker:
    """Productionda ikkita API jarayoni bor: odam ikkinchi jarayon orqali
    o'chirilsa, AI jarayonidagi kesh 5 daqiqagacha eskicha qolardi va
    o'chirilgan odam kameralarda tanilishda davom etardi."""

    @pytest.fixture(autouse=True)
    def _shared_redis(self, monkeypatch):
        fake = _FakeRedis()

        async def get_fake():
            return fake

        monkeypatch.setattr(face_matching, "_redis_url", lambda: "redis://fake")
        monkeypatch.setattr(face_matching, "_get_redis", get_fake)
        invalidate_candidate_matrix_cache()
        yield fake
        invalidate_candidate_matrix_cache()

    async def _enroll(self, db_session, name):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        person = StudentStaff(
            full_name=name, type="xodim", faculty_id=faculty.id, group_or_position="1",
            biometric_embedding=json.dumps([1.0, 0.0]),
        )
        db_session.add(person)
        await db_session.commit()
        return person

    async def test_another_workers_change_forces_a_reload(self, db_session, _shared_redis):
        await self._enroll(db_session, "Birinchi")
        assert len((await face_matching.load_candidate_matrix_for_sweep(db_session)).ids) == 1

        second = await self._enroll(db_session, "Ikkinchi")
        # Boshqa jarayon: faqat Redis hisoblagichini oshiradi, BU jarayonning
        # xotirasiga tegmaydi.
        await _shared_redis.incr(face_matching.ROSTER_VERSION_KEY)

        candidates = await face_matching.load_candidate_matrix_for_sweep(db_session)
        assert str(second.id) in candidates.ids

    async def test_unchanged_version_keeps_the_cache(self, db_session, monkeypatch):
        await self._enroll(db_session, "Birinchi")
        await face_matching.load_candidate_matrix_for_sweep(db_session)
        calls = {"n": 0}
        real_load = face_matching.load_candidate_matrix

        async def counting_load(db):
            calls["n"] += 1
            return await real_load(db)

        monkeypatch.setattr(face_matching, "load_candidate_matrix", counting_load)
        await face_matching.load_candidate_matrix_for_sweep(db_session)
        assert calls["n"] == 0

    async def test_announce_bumps_the_shared_version(self, _shared_redis):
        await face_matching.announce_roster_change()
        await face_matching.announce_roster_change()
        assert _shared_redis.values[face_matching.ROSTER_VERSION_KEY] == 2

    async def test_concurrent_callers_load_the_database_once(self, db_session, monkeypatch):
        await self._enroll(db_session, "Birinchi")
        calls = {"n": 0}
        real_load = face_matching.load_candidate_matrix

        async def slow_load(db):
            calls["n"] += 1
            await asyncio.sleep(0.05)
            return await real_load(db)

        monkeypatch.setattr(face_matching, "load_candidate_matrix", slow_load)
        results = await asyncio.gather(
            *(face_matching.load_candidate_matrix_for_sweep(db_session) for _ in range(5))
        )
        assert calls["n"] == 1
        assert all(len(r.ids) == 1 for r in results)
