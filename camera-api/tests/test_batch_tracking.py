"""Klip ichidagi yuz izlari (app/batch/tracking.py)."""

from datetime import datetime, timedelta, timezone

import numpy as np

from app.batch.tracking import FaceSample, TrackBuilder, iou

T0 = datetime(2026, 10, 5, 3, 0, tzinfo=timezone.utc)
RNG = np.random.default_rng(7)


def unit(v):
    return v / np.linalg.norm(v)


PERSON_A = unit(RNG.normal(size=512))
PERSON_B = unit(RNG.normal(size=512))


def noisy(identity, noise=0.9, seed=0):
    rng = np.random.default_rng(seed)
    return unit(identity + noise * unit(rng.normal(size=512)))


def sample(t, frame, box, emb=None, quality=0.8, px=60):
    return FaceSample(at=T0 + timedelta(seconds=t), frame_index=frame, bbox=box, embedding=emb, quality=quality, face_px=px)


def test_iou():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0
    assert abs(iou((0, 0, 10, 10), (5, 0, 15, 10)) - 1 / 3) < 1e-9


def test_same_person_moving_fast_is_linked_by_appearance():
    builder = TrackBuilder(2.5)
    for i in range(5):
        # Kadrlar orasida yuz kengligidan ko'p siljiydi — IoU nol.
        builder.add(T0 + timedelta(seconds=i), [sample(i, i, (100 + 80 * i, 100, 140 + 80 * i, 150), noisy(PERSON_A, seed=i))])
    tracks = builder.flush()
    assert len(tracks) == 1 and len(tracks[0].samples) == 5


def test_two_people_crossing_are_not_merged():
    builder = TrackBuilder(2.5)
    for i in range(4):
        a = sample(i, i, (100 + 30 * i, 100, 150 + 30 * i, 160), noisy(PERSON_A, seed=i))
        b = sample(i, i, (190 - 30 * i, 100, 240 - 30 * i, 160), noisy(PERSON_B, seed=100 + i))
        builder.add(T0 + timedelta(seconds=i), [a, b])
    tracks = builder.flush()
    assert len(tracks) == 2
    for track in tracks:
        fused = track.fused_embedding()
        assert max(np.dot(fused, PERSON_A), np.dot(fused, PERSON_B)) > 0.6


def test_small_faces_without_embedding_link_by_overlap():
    builder = TrackBuilder(2.5)
    builder.add(T0, [sample(0, 0, (100, 100, 115, 118))])
    builder.add(T0 + timedelta(seconds=1), [sample(1, 1, (102, 101, 117, 119))])
    builder.add(T0 + timedelta(seconds=2), [sample(2, 2, (400, 100, 415, 118))])
    tracks = builder.flush()
    assert sorted(len(t.samples) for t in tracks) == [1, 2]


def test_gap_closes_the_track():
    builder = TrackBuilder(2.5)
    builder.add(T0, [sample(0, 0, (100, 100, 150, 160), noisy(PERSON_A, seed=1))])
    finished = builder.add(T0 + timedelta(seconds=5), [sample(5, 5, (100, 100, 150, 160), noisy(PERSON_A, seed=2))])
    assert len(finished) == 1
    assert len(builder.flush()) == 1


def test_fused_embedding_beats_single_noisy_frames():
    """Shovqinli kadrlar (kichik/qiya yuz) — har biri alohida chegara
    atrofida, birlashtirilgani esa aniq."""
    builder = TrackBuilder(2.5)
    singles = []
    for i in range(6):
        emb = noisy(PERSON_A, noise=1.3, seed=200 + i)
        singles.append(float(np.dot(emb, PERSON_A)))
        builder.add(T0 + timedelta(seconds=i * 0.5), [sample(i * 0.5, i, (100, 100, 140, 150), emb)])
    track = builder.flush()[0]
    fused = float(np.dot(track.fused_embedding(), PERSON_A))
    assert fused > max(singles) + 0.1
    assert track.self_consistency() > 0.3


def test_quality_weighting_prefers_good_frames():
    builder = TrackBuilder(2.5)
    good = noisy(PERSON_A, noise=0.3, seed=1)
    bad = noisy(PERSON_B, noise=0.3, seed=2)  # noto'g'ri bog'langan yomon kadr
    builder.add(T0, [sample(0, 0, (100, 100, 140, 150), good, quality=0.9)])
    track = builder.active[0]
    track.samples.append(sample(1, 1, (100, 100, 140, 150), bad, quality=0.05))
    fused = track.fused_embedding()
    assert np.dot(fused, PERSON_A) > 0.9


def test_same_frame_faces_never_join_one_track():
    builder = TrackBuilder(2.5)
    emb = noisy(PERSON_A, seed=3)
    builder.add(T0, [sample(0, 0, (100, 100, 140, 150), emb), sample(0, 0, (300, 100, 340, 150), emb)])
    assert len(builder.flush()) == 2
