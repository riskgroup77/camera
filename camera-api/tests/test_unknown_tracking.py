"""Aniq notanish yuz har kadrda qayta tahlil qilinmaydi (app/jobs/attendance_ai.py).

Bazada yuzi yo'q odam (2026-09-24: 73%) kamerada turgan bo'yi har kadrda
ArcFace olardi (~0.42 s/yuz). Endi u kadrdan kadrga kuzatiladi va
settings.unknown_recheck_seconds da bir qayta tekshiriladi."""

from time import monotonic
from types import SimpleNamespace

import numpy as np

from app.jobs import attendance_ai


def _face(x: float, *, tracked: bool = False):
    return SimpleNamespace(
        bbox=np.array([x, 10.0, x + 40.0, 60.0]), embedding=None, tracked=tracked, tracked_unknown=False, landmarks_68=None
    )


def test_tracked_face_over_an_unknown_box_stays_unknown_with_its_old_deadline():
    until = monotonic() + 2.0
    faces = [_face(12.0, tracked=True), _face(300.0, tracked=True)]
    out: list = []
    attendance_ai._mark_tracked_unknown(faces, known_boxes=((300.0, 10.0, 340.0, 60.0),), unknown_skip=(((10.0, 10.0, 50.0, 60.0), until),), unknown_out=out)
    assert faces[0].tracked_unknown is True
    assert faces[1].tracked_unknown is False  # tanilgan odamning izi
    assert len(out) == 1 and out[0][1] == until  # muddat uzaymaydi


def test_overlay_shows_a_tracked_unknown_as_unknown_not_as_recognised():
    face = _face(12.0, tracked=True)
    face.tracked_unknown = True
    entries = attendance_ai._overlay_entries([face], [], [], {})
    assert entries[0]["status"] == "notanish"
    attendance_ai._link_tracks(entries, [], lambda: 1, now=1.0)
    assert entries[0]["status"] == "notanish"


async def test_clearly_unknown_good_faces_are_handed_to_the_tracker(monkeypatch):
    """Faqat sifatli va ANIQ notanish yuz kuzatuvga beriladi — kulrang zonadagi
    (o'xshashligi chegaraga yaqin) yuz har kadrda tekshirilaveradi."""
    from app.services.face_matching import CandidateMatrix, GradedMatch

    clear = SimpleNamespace(bbox=np.array([0.0, 0.0, 60.0, 70.0]), embedding=np.ones(2) / np.sqrt(2), tracked=False,
                            det_score=0.9, yaw=0.0, sharpness=500.0, landmarks_68=None)
    grey = SimpleNamespace(bbox=np.array([100.0, 0.0, 160.0, 70.0]), embedding=np.ones(2) / np.sqrt(2), tracked=False,
                           det_score=0.9, yaw=0.0, sharpness=500.0, landmarks_68=None)

    async def fake_detect(*_args, **_kwargs):
        return [clear, grey]

    def fake_graded(self, embeddings, **_kwargs):
        return [GradedMatch(None, 0.10, 0.05, "none"), GradedMatch(None, 0.41, 0.30, "none")]

    monkeypatch.setattr(attendance_ai, "detect_faces", fake_detect)
    monkeypatch.setattr(CandidateMatrix, "graded_matches", fake_graded)
    monkeypatch.setattr(attendance_ai.settings, "face_track_fusion_enabled", False)
    candidates = CandidateMatrix(ids=["p1"], matrix=np.array([[1.0, 0.0]]))
    out: list = []
    await attendance_ai.process_camera_frame(b"jpg", db=None, camera=None, candidates=candidates, unknown_out=out, allow_zoom=False)
    assert [tuple(box[:1]) for box, _until in out] == [(0.0,)]
