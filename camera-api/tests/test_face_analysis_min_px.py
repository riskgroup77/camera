"""Kichik yuzlar tahlil qilinmaydi — app/services/face_recognition.py
_detect_faces_sync. Model o'rniga soxta detektor/modellar: tekshirilayotgani
qaysi yuz qaysi modelga tushishi."""

from types import SimpleNamespace

import numpy as np
import pytest

from app.services import face_recognition
from app.services.face_recognition import recognizable_faces


class _FakeRecognition:
    input_size = (112, 112)

    def __init__(self):
        self.batches: list[int] = []

    def get_feat(self, crops):
        self.batches.append(len(crops))
        return np.array([[3.0, 4.0] + [0.0] * 510 for _ in crops])


class _FakeLandmarks:
    def __init__(self):
        self.calls = 0

    def get(self, img, face):
        self.calls += 1
        face.landmark_3d_68 = np.zeros((68, 3))


@pytest.fixture
def fake_app(monkeypatch):
    # Uch yuz: balandligi 10, 30 va 60 px.
    bboxes = np.array([[0, 0, 10, 10, 0.9], [0, 0, 30, 30, 0.9], [0, 0, 60, 60, 0.9]], dtype=np.float32)
    kpss = np.zeros((3, 5, 2), dtype=np.float32)
    recognition, landmarks = _FakeRecognition(), _FakeLandmarks()
    app = SimpleNamespace(
        det_model=SimpleNamespace(detect=lambda img, max_num, metric, input_size=None: (bboxes, kpss)),
        models={"detection": None, "recognition": recognition, "landmark_3d_68": landmarks},
    )
    monkeypatch.setattr(face_recognition, "_get_app", lambda: app)
    monkeypatch.setattr(face_recognition, "_decode_image", lambda data: np.zeros((100, 100, 3), dtype=np.uint8))
    monkeypatch.setattr(face_recognition.face_align, "norm_crop", lambda img, landmark, image_size: img)
    return recognition, landmarks


def test_small_faces_keep_only_their_box(fake_app):
    recognition, landmarks = fake_app
    faces = face_recognition._detect_faces_sync(b"jpeg", min_face_px=20)

    assert len(faces) == 3  # tashxis uchun hammasi qaytadi
    assert faces[0].embedding is None and faces[0].landmarks_68 is None
    assert recognizable_faces(faces) == faces[1:]
    # Embeddinglar BITTA chaqiruvda, landmark har katta yuzga bir marta.
    assert recognition.batches == [2]
    assert landmarks.calls == 2
    # Normallangan: (3, 4) -> (0.6, 0.8).
    assert np.allclose(faces[1].embedding[:2], [0.6, 0.8])


def test_detection_only_mode_runs_no_model(fake_app):
    recognition, landmarks = fake_app
    faces = face_recognition._detect_faces_sync(b"jpeg", min_face_px=0, analyse=False)
    assert len(faces) == 3 and recognizable_faces(faces) == []
    assert recognition.batches == [] and landmarks.calls == 0


def test_zero_threshold_analyses_everything(fake_app):
    recognition, _ = fake_app
    faces = face_recognition._detect_faces_sync(b"jpeg", min_face_px=0)
    assert len(recognizable_faces(faces)) == 3
    assert recognition.batches == [3]


def test_roi_crops_the_frame_and_returns_full_frame_coordinates(fake_app, monkeypatch):
    """Eshik hududi (Camera.face_roi): detektor faqat qirqilgan qismni ko'radi,
    natijadagi ramkalar esa to'liq kadrga nisbatan."""
    shapes: list[tuple] = []
    app = face_recognition._get_app()
    original_detect = app.det_model.detect

    def detect(img, max_num, metric, input_size=None):
        shapes.append(img.shape[:2])
        return original_detect(img, max_num, metric)

    monkeypatch.setattr(app.det_model, "detect", detect)
    faces = face_recognition._detect_faces_sync(b"jpeg", min_face_px=0, roi=(0.5, 0.2, 1.0, 1.0))
    assert shapes == [(80, 50)]  # 100x100 kadrning o'ng pastki qismi
    assert list(faces[0].bbox) == [50.0, 20.0, 60.0, 30.0]


def test_faces_identified_in_the_previous_frame_are_not_recomputed(fake_app):
    recognition, _ = fake_app
    faces = face_recognition._detect_faces_sync(b"jpeg", min_face_px=0, skip_boxes=((0.0, 0.0, 60.0, 60.0),))
    assert [face.tracked for face in faces] == [False, False, True]
    assert faces[2].embedding is None
    assert recognition.batches == [2]


def test_attendance_can_skip_the_3d_landmarks(fake_app):
    """Davomat 68 nuqtali belgilarni o'qimaydi — ular hisoblanmaydi (~0.16 s/yuz)."""
    recognition, landmarks = fake_app
    faces = face_recognition._detect_faces_sync(b"jpeg", min_face_px=20, landmarks=False)
    assert recognition.batches == [2]
    assert landmarks.calls == 0
    assert all(face.landmarks_68 is None for face in faces)
