"""A partially decoded keyframe is not a broken frame the decoder
rejects — it is a normal-looking picture with a slab of garbage in it,
and it reaches the detectors as if it were real footage. Measured on
production: 4 of 23 sampled event snapshots carried that damage, and all
four had produced a false event.

The numbers in these tests are the ones measured on that sample: intact
frames peaked at a 1.8% largest flat block, damaged ones started at 6.6%.
"""

import cv2
import numpy as np
import pytest

from app.config import settings
from app.services.frame_quality import is_frame_corrupt, largest_flat_block_fraction


def encode(image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    assert ok
    return buffer.tobytes()


def textured_scene(width: int = 640, height: int = 480) -> np.ndarray:
    """Stand-in for a real room: varied, no large flat area."""
    rng = np.random.default_rng(1234)
    return rng.integers(20, 200, size=(height, width, 3), dtype=np.uint8)


class TestLargestFlatBlockFraction:
    def test_a_textured_scene_has_no_large_flat_block(self):
        assert largest_flat_block_fraction(encode(textured_scene())) < 0.01

    def test_a_pasted_white_slab_is_measured_by_its_area(self):
        image = textured_scene()
        image[:, 480:] = 255  # a quarter of the width, full height
        fraction = largest_flat_block_fraction(encode(image))
        assert 0.2 < fraction < 0.3

    def test_undecodable_bytes_report_nothing_rather_than_zero(self):
        assert largest_flat_block_fraction(b"this is not a jpeg") is None


class TestIsFrameCorrupt:
    def test_a_clean_frame_passes(self):
        assert is_frame_corrupt(encode(textured_scene())) is False

    def test_a_frame_with_a_quarter_width_slab_is_rejected(self):
        image = textured_scene()
        image[:, 480:] = 255
        assert is_frame_corrupt(encode(image)) is True

    def test_scattered_bright_spots_are_not_damage(self):
        """A sunlit room is bright in many places at once. Damage is one
        solid slab — which is why the check measures the largest CONNECTED
        region and not the total bright area."""
        image = textured_scene()
        for x in range(0, 640, 40):
            image[100:140, x : x + 20] = 255
        assert is_frame_corrupt(encode(image)) is False

    def test_a_narrow_full_height_white_band_passes(self):
        """A white door frame or a curtain edge spans the full height
        without covering much of the picture."""
        image = textured_scene()
        image[:, 300:315] = 255
        assert is_frame_corrupt(encode(image)) is False

    def test_undecodable_bytes_are_rejected(self):
        assert is_frame_corrupt(b"not a jpeg at all") is True

    def test_no_frame_is_not_treated_as_corrupt(self):
        """Callers already distinguish "no frame available"; turning that
        into "corrupt" would double-count the same condition."""
        assert is_frame_corrupt(None) is False
        assert is_frame_corrupt(b"") is False

    def test_the_threshold_is_configurable(self, monkeypatch):
        image = textured_scene()
        image[:, 590:] = 255  # ~8% of the frame
        frame = encode(image)
        monkeypatch.setattr(settings, "frame_corruption_max_flat_block_fraction", 0.04)
        assert is_frame_corrupt(frame) is True
        monkeypatch.setattr(settings, "frame_corruption_max_flat_block_fraction", 0.5)
        assert is_frame_corrupt(frame) is False

    def test_a_failing_check_lets_the_frame_through(self, monkeypatch):
        """A quality gate that throws must not take a sweep down with it —
        and must fail toward keeping footage, not discarding it."""

        def boom(_frame):
            raise RuntimeError("decoder exploded")

        monkeypatch.setattr("app.services.frame_quality.largest_flat_block_fraction", boom)
        assert is_frame_corrupt(encode(textured_scene())) is False


@pytest.mark.parametrize(
    "measured_fraction, expected",
    [
        (0.000, False),  # empty corridor, night
        (0.018, False),  # brightest intact frame in the sample (a lit window)
        (0.066, True),   # least damaged corrupt frame
        (0.081, True),
        (0.220, True),
        (0.288, True),   # worst measured
    ],
)
def test_threshold_separates_the_production_sample(measured_fraction, expected):
    """Guards the gap the threshold sits in. If someone later moves
    frame_corruption_max_flat_block_fraction past either side of the
    measured spread, this is what says so."""
    assert (measured_fraction >= settings.frame_corruption_max_flat_block_fraction) is expected
