"""Yuz tanish quvuridagi 2026-09-19 yaxshilanishlar:

* detektor kadrni o'z nisbatida tahlil qiladi (detection_input_size);
* yuz sifati darvozasi (face_quality_ok) — yumshoq moslik uchun;
* kamera-domen galereyasi (odamga bir necha namuna, face_gallery);
* yuz izlari bo'yicha vektorlarni birlashtirish (face_tracks);
* xona kameralarini byudjet doirasida asosiy oqimga o'tkazish (stream_promotion).
"""

import json
import uuid
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import select

from app.config import settings
from app.jobs import attendance_ai
from app.models import FaceGalleryEmbedding, Faculty, StudentStaff
from app.services import face_gallery, face_recognition, recognition_stats, stream_promotion
from app.services.face_matching import CandidateMatrix, GradedMatch, _build_candidate_matrix, anchor_hash, load_candidate_matrix
from app.services.face_recognition import detection_input_size, face_quality_ok
from app.services.face_tracks import TrackStore, track_store
from app.services.frame_grabber import _is_security_camera


def _unit(values) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float64)
    return vector / np.linalg.norm(vector)


# ── Detektor kirish o'lchami ────────────────────────────────────────────────


class TestDetectionInputSize:
    def test_substream_keeps_its_aspect_instead_of_a_square(self):
        # 640x360 -> 640x384 (32 ga karrali), 640x640 emas.
        assert detection_input_size(640, 360) == (640, 384)

    def test_main_stream_is_analysed_at_up_to_max_side(self, monkeypatch):
        monkeypatch.setattr(settings, "face_det_max_side", 1280)
        assert detection_input_size(2560, 1440) == (1280, 736)
        assert detection_input_size(1920, 1080) == (1280, 736)

    def test_small_roi_is_upscaled_like_before(self, monkeypatch):
        monkeypatch.setattr(settings, "face_det_min_side", 640)
        assert detection_input_size(200, 100) == (640, 320)

    def test_disabled_falls_back_to_the_prepared_square(self, monkeypatch):
        monkeypatch.setattr(settings, "face_det_native_resolution", False)
        assert detection_input_size(640, 360) is None

    def test_detector_receives_the_native_size(self, monkeypatch):
        calls: list = []
        bboxes = np.array([[0, 0, 60, 60, 0.95]], dtype=np.float32)
        kpss = np.array([[[20, 20], [40, 20], [30, 30], [22, 45], [38, 45]]], dtype=np.float32)

        def detect(img, max_num, metric, input_size=None):
            calls.append(input_size)
            return bboxes, kpss

        class _Recognition:
            input_size = (112, 112)

            def get_feat(self, crops):
                return np.array([[1.0, 0.0] for _ in crops])

        app = SimpleNamespace(
            det_model=SimpleNamespace(detect=detect), models={"recognition": _Recognition(), "landmark_3d_68": None}
        )
        monkeypatch.setattr(face_recognition, "_get_app", lambda: app)
        monkeypatch.setattr(face_recognition, "_decode_image", lambda data: np.zeros((360, 640, 3), dtype=np.uint8))
        monkeypatch.setattr(
            face_recognition.face_align, "norm_crop", lambda img, landmark, image_size: np.zeros((112, 112, 3), np.uint8)
        )
        faces = face_recognition._detect_faces_sync(b"jpeg", min_face_px=0)
        assert calls == [(640, 384)]
        face = faces[0]
        assert face.det_score == pytest.approx(0.95)
        assert face.yaw == pytest.approx(0.0)  # burun ko'zlar o'rtasida
        assert face.sharpness == pytest.approx(0.0)  # bir xil rangli kesim — xira


# ── Sifat darvozasi ─────────────────────────────────────────────────────────


class TestFaceQuality:
    def _face(self, **kwargs):
        base = {"det_score": 0.9, "yaw": 0.05, "sharpness": 200.0}
        base.update(kwargs)
        return SimpleNamespace(**base)

    def test_good_face_passes(self):
        assert face_quality_ok(self._face())

    @pytest.mark.parametrize(
        "field,value", [("det_score", 0.3), ("yaw", 0.6), ("yaw", -0.6), ("sharpness", 3.0)]
    )
    def test_poor_face_fails(self, field, value):
        assert not face_quality_ok(self._face(**{field: value}))

    def test_unmeasured_face_passes(self):
        assert face_quality_ok(SimpleNamespace())

    def test_gate_can_be_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "face_quality_gate_enabled", False)
        assert face_quality_ok(self._face(yaw=0.9))

    def test_yaw_from_keypoints(self):
        kps = np.array([[20, 20], [40, 20], [38, 30], [22, 45], [38, 45]], dtype=np.float32)
        assert face_recognition._yaw_from_kps(kps) == pytest.approx(0.4)


# ── Galereya bilan moslik ───────────────────────────────────────────────────


def _gallery_matrix(anchor_a, gallery_a, anchor_b) -> CandidateMatrix:
    rows = [
        ("a", json.dumps(list(anchor_a)), "xodim"),
        ("b", json.dumps(list(anchor_b)), "xodim"),
    ]
    gallery = [("a", json.dumps(list(gallery_a)), anchor_hash(rows[0][1]))]
    return _build_candidate_matrix(rows, gallery)


class TestGalleryMatching:
    def test_gallery_sample_lifts_the_owner_above_threshold(self):
        anchor_a = _unit([1.0, 0.0, 0.0])
        camera_a = _unit([0.6, 0.8, 0.0])  # kamera sharoitidagi A
        anchor_b = _unit([0.0, 0.0, 1.0])
        matrix = _gallery_matrix(anchor_a, camera_a, anchor_b)
        assert matrix.has_gallery
        assert matrix.ids == ["a", "b"]
        face = _unit([0.55, 0.83, 0.05])
        [match] = matrix.graded_matches(
            face[None, :], strict_threshold=0.5, relaxed_threshold=0.42, margin=0.08, strict_margin=0.05
        )
        assert match.person_id == "a" and match.grade == "strict"
        # Ikkinchi nomzod — B (A ning o'z namunasi emas), shuning uchun margin katta.
        assert match.second_similarity < 0.1
        assert match.anchor_similarity == pytest.approx(float(face @ anchor_a))

    def test_without_gallery_the_same_face_is_not_recognised(self):
        anchor_a = _unit([1.0, 0.0, 0.0])
        anchor_b = _unit([0.0, 0.0, 1.0])
        matrix = CandidateMatrix(ids=["a", "b"], matrix=np.stack([anchor_a, anchor_b]))
        face = _unit([0.55, 0.83, 0.05])
        [match] = matrix.graded_matches(
            face[None, :], strict_threshold=0.7, relaxed_threshold=0.65, margin=0.08
        )
        assert match.person_id is None

    def test_match_through_gallery_alone_is_rejected_below_anchor_floor(self, monkeypatch):
        monkeypatch.setattr(settings, "face_gallery_anchor_floor", 0.3)
        anchor_a = _unit([1.0, 0.0, 0.0])
        camera_a = _unit([0.0, 1.0, 0.0])
        anchor_b = _unit([0.0, 0.0, 1.0])
        matrix = _gallery_matrix(anchor_a, camera_a, anchor_b)
        [match] = matrix.graded_matches(
            _unit([0.05, 1.0, 0.0])[None, :], strict_threshold=0.5, relaxed_threshold=0.42, margin=0.08
        )
        assert match.person_id is None

    def test_samples_of_a_replaced_photo_are_ignored(self):
        rows = [("a", json.dumps([1.0, 0.0]), "xodim")]
        matrix = _build_candidate_matrix(rows, [("a", json.dumps([0.0, 1.0]), "stale-hash")])
        assert not matrix.has_gallery
        assert matrix.matrix.shape == (1, 2)


# ── Yuz izlari ──────────────────────────────────────────────────────────────


def _face_at(bbox, embedding):
    return SimpleNamespace(bbox=np.asarray(bbox, dtype=np.float64), embedding=np.asarray(embedding, dtype=np.float64))


class TestTrackFusion:
    def test_noisy_frames_average_towards_the_true_identity(self):
        rng = np.random.default_rng(0)
        truth = _unit(rng.normal(size=64))
        store = TrackStore()
        single = []
        fused = None
        for step in range(6):
            noisy = _unit(truth + rng.normal(scale=0.12, size=64))
            single.append(float(noisy @ truth))
            [result] = store.update("cam", [_face_at([10, 10, 40, 40], noisy)], now=float(step))
            fused = result
        assert fused.frames == 6
        assert float(fused.embedding @ truth) > max(single)

    def test_single_frame_gives_no_fused_vector(self):
        store = TrackStore()
        [result] = store.update("cam", [_face_at([0, 0, 30, 30], [1.0, 0.0])], now=0.0)
        assert result.embedding is None and result.frames == 1

    def test_a_different_person_in_the_same_seat_restarts_the_track(self):
        store = TrackStore()
        store.update("cam", [_face_at([0, 0, 30, 30], [1.0, 0.0])], now=0.0)
        [result] = store.update("cam", [_face_at([0, 0, 30, 30], [0.0, 1.0])], now=1.0)
        assert result.frames == 1

    def test_old_tracks_expire(self, monkeypatch):
        monkeypatch.setattr(settings, "face_track_max_age_seconds", 10.0)
        store = TrackStore()
        store.update("cam", [_face_at([0, 0, 30, 30], [1.0, 0.0])], now=0.0)
        [result] = store.update("cam", [_face_at([0, 0, 30, 30], [1.0, 0.0])], now=100.0)
        assert result.frames == 1

    def test_fusion_upgrades_an_unrecognised_face(self, monkeypatch):
        monkeypatch.setattr(settings, "face_track_min_self_similarity", -1.0)
        truth = _unit([1.0, 0.0, 0.0])
        candidates = CandidateMatrix(ids=["a", "b"], matrix=np.stack([truth, _unit([0.0, 0.0, 1.0])]))
        faces = [
            _face_at([0, 0, 50, 50], _unit([0.5, 0.6, 0.1])),
            _face_at([1, 1, 51, 51], _unit([0.5, -0.6, 0.1])),
        ]
        none = GradedMatch(None, 0.4, 0.0, "none")
        attendance_ai._fuse_tracks("cam-x", [faces[0]], [none], candidates)
        [match] = attendance_ai._fuse_tracks("cam-x", [faces[1]], [none], candidates)
        assert match.person_id == "a" and match.fused and match.grade == "strict"
        track_store.clear()


# ── Galereyaga avtomatik qo'shish (baza) ────────────────────────────────────


def _strict(person_id, similarity=0.7, second=0.1) -> GradedMatch:
    return GradedMatch(person_id, similarity, second, "strict", similarity)


def _big_face(embedding):
    return SimpleNamespace(
        bbox=np.array([0, 0, 90, 90], dtype=np.float64),
        embedding=np.asarray(embedding, dtype=np.float64),
        det_score=0.9,
        yaw=0.0,
        sharpness=200.0,
    )


@pytest.mark.usefixtures("seeded")
class TestGalleryAutoAdd:
    async def _person(self, db_session, embedding):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        person = StudentStaff(
            full_name="Galereya", type="xodim", faculty_id=faculty.id, group_or_position="1",
            biometric_embedding=json.dumps(embedding),
        )
        db_session.add(person)
        await db_session.commit()
        return person

    async def test_confident_big_face_is_added_and_used_for_matching(self, db_session):
        person = await self._person(db_session, [1.0, 0.0, 0.0, 0.0])
        face = _big_face(_unit([0.8, 0.6, 0.0, 0.0]))
        assert await face_gallery.maybe_add(db_session, face, _strict(str(person.id)), now=0.0)
        await db_session.commit()
        rows = (await db_session.execute(select(FaceGalleryEmbedding))).scalars().all()
        assert len(rows) == 1 and rows[0].face_px == 90
        matrix = await load_candidate_matrix(db_session)
        assert matrix.has_gallery and matrix.matrix.shape == (2, 4)

    async def test_interval_duplicates_and_cap_are_respected(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "face_gallery_max_per_person", 2)
        monkeypatch.setattr(settings, "face_gallery_min_interval_seconds", 10)
        person = await self._person(db_session, [1.0, 0.0, 0.0, 0.0])
        pid = str(person.id)
        assert await face_gallery.maybe_add(db_session, _big_face(_unit([0.8, 0.6, 0, 0])), _strict(pid), now=0.0)
        await db_session.commit()
        # Juda tez — o'tkazib yuboriladi.
        assert not await face_gallery.maybe_add(db_session, _big_face(_unit([0.8, 0, 0.6, 0])), _strict(pid), now=5.0)
        # Deyarli bir xil namuna — takror.
        assert not await face_gallery.maybe_add(db_session, _big_face(_unit([0.8, 0.6, 0.01, 0])), _strict(pid), now=20.0)
        assert await face_gallery.maybe_add(db_session, _big_face(_unit([0.8, 0, 0.6, 0])), _strict(pid), now=40.0)
        await db_session.commit()
        # Chegara (2) to'lgan.
        assert not await face_gallery.maybe_add(db_session, _big_face(_unit([0.8, 0, 0, 0.6])), _strict(pid), now=60.0)

    @pytest.mark.parametrize(
        "match,face_kwargs",
        [
            (GradedMatch("x", 0.52, 0.1, "strict", 0.52), {}),  # o'xshashlik past
            (GradedMatch("x", 0.7, 0.65, "strict", 0.7), {}),  # ajralish kichik
            (GradedMatch("x", 0.7, 0.1, "relaxed", 0.7), {}),  # yumshoq moslik
            (GradedMatch("x", 0.7, 0.1, "strict", 0.7), {"bbox": np.array([0, 0, 30, 30.0])}),  # kichik yuz
            (GradedMatch("x", 0.7, 0.1, "strict", 0.7), {"yaw": 0.7}),  # profil
            (GradedMatch("x", 0.7, 0.1, "strict", 0.45), {}),  # faqat galereya orqali
        ],
    )
    def test_weak_evidence_never_qualifies(self, match, face_kwargs):
        face = _big_face([1.0, 0.0])
        for key, value in face_kwargs.items():
            setattr(face, key, value)
        assert not face_gallery.qualifies(face, match)


# ── Asosiy oqimga o'tkazish ─────────────────────────────────────────────────


def _feed(camera_id: str, faces: int, px: int) -> None:
    for _ in range(faces):
        recognition_stats.record_frame(
            camera_id, [SimpleNamespace(bbox=np.array([0, 0, px, px], dtype=np.float64))], []
        )


class TestStreamPromotion:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        recognition_stats.reset_for_tests()
        monkeypatch.setattr(settings, "ai_main_stream_promotion_enabled", True)
        monkeypatch.setattr(settings, "ai_main_stream_promotion_budget", 1)
        monkeypatch.setattr(settings, "ai_main_stream_promotion_min_faces", 4)
        monkeypatch.setattr(settings, "ai_main_stream_promotion_min_px", 10)
        monkeypatch.setattr(settings, "ai_main_stream_promotion_max_px", 40)
        monkeypatch.setattr(settings, "ai_main_stream_promotion_hold_seconds", 100)
        monkeypatch.setattr(settings, "ai_main_stream_promotion_refresh_seconds", 0)
        yield
        recognition_stats.reset_for_tests()

    def test_busiest_small_face_camera_wins_the_budget(self):
        _feed("busy", 20, 16)
        _feed("quiet", 5, 16)
        _feed("tiny", 50, 6)  # asosiy oqimda ham tanib bo'lmaydi
        _feed("large", 50, 80)  # substream yetarli
        for camera_id in ("quiet", "tiny", "large", "busy"):
            stream_promotion.is_promoted(camera_id, now=1.0)
        # "quiet" birinchi ko'rildi va bo'sh o'rinni oldi; byudjet 1.
        assert stream_promotion.promoted_cameras() == ["quiet"]
        stream_promotion.reset_for_tests()
        for camera_id in ("quiet", "tiny", "large", "busy"):
            stream_promotion._room_cameras.add(camera_id)
        stream_promotion.refresh(now=2.0)
        assert stream_promotion.promoted_cameras() == ["busy"]

    def test_camera_without_new_faces_is_released_and_cooled_down(self):
        _feed("busy", 20, 16)
        stream_promotion.is_promoted("busy", now=1.0)
        assert stream_promotion.is_promoted("busy", now=2.0)
        stream_promotion.refresh(now=200.0)  # muddat tugadi, yangi yuz yo'q
        assert stream_promotion.promoted_cameras() == []
        stream_promotion.refresh(now=250.0)  # sovish davrida qayta tanlanmaydi
        assert stream_promotion.promoted_cameras() == []

    def test_camera_that_keeps_seeing_faces_stays(self):
        _feed("busy", 20, 16)
        stream_promotion.is_promoted("busy", now=1.0)
        _feed("busy", 10, 60)
        stream_promotion.refresh(now=200.0)
        assert stream_promotion.promoted_cameras() == ["busy"]

    def test_frame_grabber_reads_the_main_stream_for_promoted_room_cameras(self, monkeypatch):
        monkeypatch.setattr(settings, "attendance_all_cameras", True)
        monkeypatch.setattr(settings, "ai_room_cameras_main_stream", False)
        camera_id = uuid.uuid4()
        room = SimpleNamespace(id=camera_id, is_entrance=False, is_perimeter=False)
        _feed(str(camera_id), 20, 16)
        assert _is_security_camera(room)
        monkeypatch.setattr(settings, "ai_main_stream_promotion_enabled", False)
        assert not _is_security_camera(room)
