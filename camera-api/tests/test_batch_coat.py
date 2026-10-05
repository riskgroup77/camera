"""Oq xalat (#10) — sintetik kadrlar bilan rang qoidasi va kunlik ovoz.

Kadrlar haqiqiy CCTV holatlarini taqlid qiladi: xira xona, sariq lampa,
orqada oq devor, oq xalat va to'q kiyim, kadr chetidagi odam."""

import cv2
import numpy as np
import pytest

from app.batch import coat
from app.config import settings

H, W = 720, 1280


def scene(background=(90, 90, 90), torso=(240, 240, 240), light=1.0, cast=(1.0, 1.0, 1.0), wall=None,
          face_box=(600, 200, 660, 270), noise=6, seed=0):
    """BGR kadr: fon, yuz (teri rangi) va tana (yuz ostida)."""
    rng = np.random.default_rng(seed)
    image = np.zeros((H, W, 3), np.float32)
    image[:] = background
    if wall is not None:
        image[:, :] = wall
    x1, y1, x2, y2 = face_box
    fw, fh = x2 - x1, y2 - y1
    cx = (x1 + x2) // 2
    # Tana: yelka kengligi ~2.4 yuz, yuzdan pastga ~3 yuz balandligi.
    cv2.rectangle(image, (int(cx - 1.2 * fw), int(y2 + 0.2 * fh)), (int(cx + 1.2 * fw), int(y2 + 3.0 * fh)), torso, -1)
    cv2.rectangle(image, (x1, y1), (x2, y2), (120, 150, 200), -1)  # yuz
    image *= light
    image *= np.array(cast, np.float32)
    image += rng.normal(0, noise, image.shape)
    return np.clip(image, 0, 255).astype(np.uint8), face_box


def person_box(face_box):
    x1, y1, x2, y2 = face_box
    fw, fh = x2 - x1, y2 - y1
    cx = (x1 + x2) / 2
    return (cx - 1.25 * fw, y1 - 0.2 * fh, cx + 1.25 * fw, y2 + 3.1 * fh)


@pytest.mark.parametrize(
    "case, kwargs, expected",
    [
        ("oq xalat, oddiy yorug'lik", {}, True),
        ("to'q ko'k kiyim", {"torso": (90, 50, 30)}, False),
        ("qora kiyim", {"torso": (25, 25, 25)}, False),
        ("qizil kofta", {"torso": (40, 40, 200)}, False),
        ("oq xalat, xira xona", {"background": (40, 40, 40), "light": 0.65}, True),
        ("oq xalat, sariq lampa", {"cast": (0.78, 0.95, 1.12)}, True),
        ("kulrang kiyim yorug' xonada", {"torso": (120, 120, 120), "background": (150, 150, 150)}, False),
    ],
)
def test_single_sample_classification(case, kwargs, expected):
    image, face = scene(**kwargs)
    sample = coat.evaluate(image, face, person_box(face))
    assert sample is not None, case
    assert sample.is_white is expected, f"{case}: ulush {sample.fraction:.2f}"


def test_white_wall_behind_dark_clothes_is_not_a_coat():
    """Oq devor oldida to'q kiyim — odam ramkasi bo'lmasa soha devorni ham
    oladi; ramka bilan kesilganda devor hisobga kirmaydi."""
    image, face = scene(torso=(70, 45, 30), wall=(235, 235, 235))
    with_box = coat.evaluate(image, face, person_box(face))
    assert with_box is not None and with_box.is_white is False


def test_face_at_frame_bottom_has_no_torso_to_judge():
    image, _ = scene()
    sample = coat.evaluate(image, (600, 650, 660, 715))
    assert sample is None


def test_roi_is_clipped_to_person_and_frame():
    roi = coat.torso_roi((10, 10, 50, 60), (H, W, 3), person_box((10, 10, 50, 60)))
    assert roi is not None
    x1, y1, x2, y2 = roi
    assert x1 >= 0 and y1 > 60 and x2 <= W and y2 <= H


def test_degenerate_face_box():
    assert coat.torso_roi((10, 10, 10, 10), (H, W, 3)) is None


def test_white_balance_gains_neutralize_cast():
    image, _ = scene(cast=(0.75, 0.95, 1.15))
    gains = coat.white_balance_gains(image)
    bright = image.reshape(-1, 3)[image.reshape(-1, 3).mean(axis=1) > 180].astype(np.float32).mean(axis=0)
    balanced = bright * gains
    assert balanced.max() - balanced.min() < 0.25 * (bright.max() - bright.min()) + 4


def test_observation_vote_majority():
    assert coat.observation_vote(3, 3) is True
    assert coat.observation_vote(0, 2) is False
    assert coat.observation_vote(1, 2) is None
    assert coat.observation_vote(0, 0) is None


def test_day_verdict_thresholds(monkeypatch):
    monkeypatch.setattr(settings, "coat_min_samples", 3)
    assert coat.day_verdict([True, True, True, False], True) == coat.COAT_YES
    assert coat.day_verdict([False, False, False, True], True) == coat.COAT_NO
    assert coat.day_verdict([True, False, True, False], True) == coat.COAT_UNKNOWN
    assert coat.day_verdict([False, False], True) == coat.COAT_UNKNOWN  # namuna kam
    assert coat.day_verdict([False, False, False], False) == coat.COAT_NOT_REQUIRED


def test_coat_requirement_by_type_and_position(monkeypatch):
    monkeypatch.setattr(settings, "coat_required_types", "talaba")
    assert coat.coat_required("talaba", None)
    assert coat.coat_required("xodim", "Katta o'qituvchi")
    assert coat.coat_required("xodim", None, "Anatomiya kafedrasi dotsenti")
    assert coat.coat_required("xodim", "Kafedra mudiri")
    assert not coat.coat_required("xodim", "Buxgalter")
    assert not coat.coat_required("xodim", None, "Xo'jalik bo'limi")
    assert coat.coat_required("xodim", "o‘qituvchi")  # boshqa apostrof


def test_noise_and_compression_do_not_flip_the_verdict():
    for seed in range(5):
        image, face = scene(seed=seed, noise=14)
        ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 55])
        decoded = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        assert coat.evaluate(decoded, face, person_box(face)).is_white is True
        image, face = scene(seed=seed, noise=14, torso=(80, 60, 40))
        ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 55])
        decoded = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        assert coat.evaluate(decoded, face, person_box(face)).is_white is False
