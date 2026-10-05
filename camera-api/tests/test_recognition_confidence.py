"""Davomatda yuz tanish: yumshoq moslik, takroriy tasdiqlash, statistika
va detektorlarning hisoblangan ishonchi.

Audit: "tizimdan o'tganlar va tasdiqlaganlar ko'p, lekin hech kim davomatga
tushmayapti". CCTV kadridagi kichik yuz ro'yxatdagi odamning o'zi bo'lsa
ham 0.47-0.55 oralig'ida qoladi — qat'iy 0.55 chegarasi uni hech qachon
tanimasdi."""

from types import SimpleNamespace

import numpy as np
import pytest

from app.config import settings
from app.services import recognition_stats
from app.services.confidence import below_confidence, exceed_confidence, weakest
from app.services.face_matching import CandidateMatrix


def _unit(*values: float) -> np.ndarray:
    v = np.array(values, dtype=np.float64)
    return v / np.linalg.norm(v)


def _face_with_similarity(target: np.ndarray, similarity: float, other_axis: int) -> np.ndarray:
    """target bilan aynan `similarity` kosinusga ega birlik vektor."""
    orth = np.zeros_like(target)
    orth[other_axis] = 1.0
    return similarity * target + np.sqrt(1 - similarity**2) * orth


@pytest.fixture(autouse=True)
def _clean_stats():
    recognition_stats.reset_for_tests()
    yield
    recognition_stats.reset_for_tests()


class TestGradedMatches:
    def _matrix(self) -> CandidateMatrix:
        # Ikki ro'yxatdagi odam: bir-biriga ortogonal.
        return CandidateMatrix(ids=["ali", "vali"], matrix=np.array([_unit(1, 0, 0, 0), _unit(0, 1, 0, 0)]))

    def _grade(self, face: np.ndarray, *, strict_margin: float = 0.0):
        return self._matrix().graded_matches(
            np.array([face]),
            strict_threshold=0.55,
            relaxed_threshold=0.47,
            margin=0.08,
            strict_margin=strict_margin,
        )[0]

    def test_strong_similarity_is_strict(self):
        match = self._grade(_face_with_similarity(_unit(1, 0, 0, 0), 0.7, other_axis=2))
        assert match.grade == "strict" and match.person_id == "ali"

    def test_near_threshold_with_clear_margin_is_relaxed(self):
        match = self._grade(_face_with_similarity(_unit(1, 0, 0, 0), 0.5, other_axis=2))
        assert match.grade == "relaxed" and match.person_id == "ali"
        assert match.similarity == pytest.approx(0.5)

    def test_near_threshold_between_two_people_is_rejected(self):
        # Ikkalasiga teng (0.50) o'xshash — yumshoq oraliqda, lekin kimligi
        # noaniq (ajralish 0), shuning uchun yozilmaydi.
        face = 0.5 * _unit(1, 0, 0, 0) + 0.5 * _unit(0, 1, 0, 0) + np.sqrt(0.5) * _unit(0, 0, 1, 0)
        match = self._grade(face)
        assert match.grade == "none" and match.person_id is None
        assert match.similarity == pytest.approx(0.5)  # statistika uchun o'xshashlik baribir qaytadi
        assert match.second_similarity == pytest.approx(0.5)

    def test_strict_match_needs_a_clear_winner(self):
        """Ikki odamga barobar (0.60) o'xshash yuz: raqam qat'iy chegaradan
        o'tadi, lekin KIM ekani noaniq. Chegara 0.55 dan 0.50 ga
        tushirilgach bu holat xavfli bo'ldi, shuning uchun margin."""
        face = 0.6 * _unit(1, 0, 0, 0) + 0.6 * _unit(0, 1, 0, 0) + np.sqrt(0.28) * _unit(0, 0, 1, 0)

        assert self._grade(face).grade == "strict"  # marginsiz — eski xatti-harakat
        ambiguous = self._grade(face, strict_margin=0.05)
        assert ambiguous.grade == "none" and ambiguous.person_id is None
        assert ambiguous.similarity == pytest.approx(0.6)

    def test_clear_strict_match_passes_the_margin(self):
        match = self._grade(_face_with_similarity(_unit(1, 0, 0, 0), 0.7, other_axis=2), strict_margin=0.05)
        assert match.grade == "strict" and match.person_id == "ali"

    def test_unnormalized_embeddings_are_normalized(self):
        cm = CandidateMatrix(ids=["ali"], matrix=np.array([_unit(1, 0)]))
        assert cm.best_matches(np.array([[5.0, 0.0]]), 0.55)[0] == ("ali", pytest.approx(1.0))


class TestRelaxedConfirmation:
    def test_another_camera_confirms_quickly(self):
        assert recognition_stats.confirm_relaxed("ali", "kam-1", now=100.0) is False
        assert recognition_stats.confirm_relaxed("ali", "kam-2", now=101.0) is True
        # Tasdiqlangandan keyin navbat tozalanadi — keyingisi yana ikkitani talab qiladi.
        assert recognition_stats.confirm_relaxed("ali", "kam-2", now=102.0) is False

    def test_same_camera_needs_a_real_gap(self):
        """Eshik oldida turgan o'xshash begona ketma-ket kadrlar bilan o'zini tasdiqlamasin."""
        gap = settings.attendance_relaxed_same_camera_gap_seconds
        assert recognition_stats.confirm_relaxed("ali", "kam-1", now=100.0) is False
        assert recognition_stats.confirm_relaxed("ali", "kam-1", now=101.0) is False
        assert recognition_stats.confirm_relaxed("ali", "kam-1", now=100.0 + gap) is True

    def test_sightings_too_far_apart_do_not_confirm(self):
        window = settings.attendance_relaxed_confirm_window_seconds
        assert recognition_stats.confirm_relaxed("ali", now=0.0) is False
        assert recognition_stats.confirm_relaxed("ali", now=window + 5.0) is False

    def test_same_instant_is_not_a_second_sighting(self):
        assert recognition_stats.confirm_relaxed("ali", "kam-1", now=10.0) is False
        assert recognition_stats.confirm_relaxed("ali", "kam-2", now=10.1) is False


class TestProcessCameraFrameWithRelaxedMatches:
    async def test_relaxed_match_needs_a_second_frame_then_writes_attendance(self, db_session, seeded):
        from sqlalchemy import select

        from app.jobs.attendance_ai import process_camera_frame
        from app.models import AttendanceRecord, Building, Camera, StudentStaff
        from app.timezone import local_now

        building = (await db_session.execute(select(Building))).scalars().first()
        camera = Camera(name="Kirish-T", ip="10.9.0.1", building_id=building.id, zone="Kirish",
                        resolution="1080p", status="faol", is_entrance=True)
        person = StudentStaff(full_name="Sinov Talaba Birinchi", type="talaba", group_or_position="1-kurs",
                              biometrics_status="tasdiqlangan")
        db_session.add_all([camera, person])
        await db_session.commit()

        enrolled = np.zeros(512)
        enrolled[0] = 1.0
        other = np.zeros(512)
        other[1] = 1.0
        candidates = CandidateMatrix(ids=[str(person.id), "boshqa"], matrix=np.array([enrolled, other]),
                                     person_types={str(person.id): "talaba", "boshqa": "talaba"})
        # Yumshoq oraliq (0.42-0.50) ichidagi o'xshashlik.
        face_vec = _face_with_similarity(enrolled, 0.46, other_axis=5)
        face = SimpleNamespace(embedding=face_vec, bbox=np.array([0, 0, 90, 110]))

        first = await process_camera_frame(b"f1", db_session, camera, occurred_at=local_now(),
                                           candidates=candidates, faces=[face])
        assert first == []
        assert (await db_session.execute(select(AttendanceRecord))).scalars().all() == []

        # O'sha kamera — birinchi ko'rinish kamida same_camera_gap oldin bo'lgan bo'lishi kerak.
        recognition_stats._pending_relaxed[str(person.id)] -= settings.attendance_relaxed_same_camera_gap_seconds + 1
        second = await process_camera_frame(b"f2", db_session, camera, occurred_at=local_now(),
                                            candidates=candidates, faces=[face])
        assert len(second) == 1

        stats = recognition_stats.snapshot(str(camera.id))
        assert stats.frames == 2 and stats.faces == 2
        assert stats.relaxed_pending == 1 and stats.relaxed_confirmed == 1
        assert stats.buckets["0.40-0.47"] == 2

    async def test_tiny_face_never_gets_a_relaxed_match(self, db_session, seeded):
        from app.jobs.attendance_ai import process_camera_frame

        enrolled = np.zeros(512)
        enrolled[0] = 1.0
        candidates = CandidateMatrix(ids=["p1"], matrix=np.array([enrolled]), person_types={"p1": "talaba"})
        # 0.50 — qat'iy chegaradan o'tadi, lekin yuz 24 piksel: kichik
        # yuzlar uchun chegara baribir 0.55 bo'lib qoladi.
        face = SimpleNamespace(embedding=_face_with_similarity(enrolled, 0.50, other_axis=3),
                               bbox=np.array([0, 0, 20, 24]))
        for _ in range(3):
            assert await process_camera_frame(b"f", db_session, None, candidates=candidates, faces=[face]) == []


class TestConfidenceScale:
    def test_exceed_starts_at_floor_and_saturates(self):
        assert exceed_confidence(1.0, 1.0, floor=35, ceiling=75) == 35
        assert exceed_confidence(1.5, 1.0, floor=35, ceiling=75) == 55
        assert exceed_confidence(9.0, 1.0, floor=35, ceiling=75) == 75
        assert exceed_confidence(5.0, 0.0, floor=35) == 35

    def test_below_grows_as_value_shrinks(self):
        assert below_confidence(0.10, 0.10, floor=35, ceiling=80) == 35
        assert below_confidence(0.05, 0.10, floor=35, ceiling=80) == 58
        assert below_confidence(0.0, 0.10, floor=35, ceiling=80) == 80

    def test_weakest_frame_wins(self):
        assert weakest(80, 55, default=40) == 55
        assert weakest(None, None, default=40) == 40


class TestDetectorConfidencesAreComputed:
    def test_unauthorized_confidence_depends_on_how_unfamiliar_the_face_is(self):
        from app.jobs.unauthorized_person_ai import _unmatched_confidence

        enrolled = _unit(1, 0, 0)
        candidates = CandidateMatrix(ids=["p1"], matrix=np.array([enrolled]))
        # "Tanish" chegarasi — undan yuqori yuz begona emas (unauthorized_known_similarity).
        threshold = settings.unauthorized_known_similarity
        stranger = SimpleNamespace(embedding=_unit(0, 0, 1))
        # Chegaraga yaqin, lekin undan past: ishonch chegaraga NISBATAN
        # hisoblanadi (70 + 25 * (chegara - o'xshashlik) / chegara),
        # shuning uchun kutilgan qiymat ham shu formuladan olinadi —
        # chegara kalibrlanganda test o'zi bilan birga siljiydi.
        lookalike = SimpleNamespace(embedding=_face_with_similarity(enrolled, threshold - 0.06, other_axis=2))
        expected = round(70 + 25 * 0.06 / threshold)
        assert _unmatched_confidence([stranger], candidates) == 95
        assert _unmatched_confidence([lookalike], candidates) == expected
        assert _unmatched_confidence([lookalike], candidates) < _unmatched_confidence([stranger], candidates)

    def test_substitution_confidence_tracks_face_similarity(self):
        from app.jobs.teacher_punctuality_ai import _substitution_confidence

        assert _substitution_confidence(None) == 70
        assert _substitution_confidence(settings.attendance_ai_match_threshold) == 70
        assert _substitution_confidence(0.95) == 95
