"""A partially decoded keyframe is not a frame the decoder rejects — it
is a normal-looking picture with a slab of garbage in it, and it reaches
the detectors as if it were real footage.

Telling that apart from a sunlit window is the whole difficulty, and no
single-frame metric does it: measured across both populations the
texture inside the block scored 69.7 on a corrupt frame and 67.5 on a
sunlit classroom. A first version used block size alone and blinded 29
of 107 cameras on the first sunny morning. What separates them is
persistence — a window stays put, damage moves — so these tests are
mostly about pairs of frames, not single ones.
"""

import cv2
import numpy as np
import pytest

from app.config import settings
from app.services.frame_quality import (
    FlatBlock,
    largest_flat_block,
    looks_like_decode_damage,
    measure_frame,
)


def encode(image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    assert ok
    return buffer.tobytes()


def scene(*, block: tuple[int, int, int, int] | None = None) -> bytes:
    """A textured room, optionally with a white slab at (x, y, w, h)."""
    rng = np.random.default_rng(1234)
    image = rng.integers(20, 200, size=(480, 640, 3), dtype=np.uint8)
    if block:
        x, y, w, h = block
        image[y : y + h, x : x + w] = 255
    return encode(image)


class TestLargestFlatBlock:
    def test_a_textured_scene_has_no_large_flat_block(self):
        assert largest_flat_block(scene()).fraction < 0.01

    def test_a_slab_is_measured_by_area_and_located(self):
        found = largest_flat_block(scene(block=(320, 0, 320, 480)))
        assert 0.4 < found.fraction < 0.6
        x, _y, w, _h = found.box
        assert x > 30  # right-hand half, in the 1/8-scale grid (80 wide)
        assert w > 20

    def test_undecodable_bytes_report_nothing(self):
        assert largest_flat_block(b"this is not a jpeg") is None


class TestLooksLikeDecodeDamage:
    def test_a_clean_frame_passes(self):
        block = measure_frame(scene())
        assert looks_like_decode_damage(block, None) is False

    def test_a_slab_that_was_not_there_before_is_damage(self):
        clean = measure_frame(scene())
        damaged = measure_frame(scene(block=(320, 0, 320, 480)))
        assert looks_like_decode_damage(damaged, clean) is True

    def test_a_slab_in_the_same_place_as_before_is_the_room(self):
        """A blown-out window is in every frame. Rejecting it means
        rejecting every frame that camera will ever produce."""
        window = (500, 0, 140, 480)
        first = measure_frame(scene(block=window))
        second = measure_frame(scene(block=window))
        assert looks_like_decode_damage(second, first) is False

    def test_a_slab_that_moved_is_damage(self):
        left = measure_frame(scene(block=(0, 0, 200, 480)))
        right = measure_frame(scene(block=(440, 0, 200, 480)))
        assert looks_like_decode_damage(right, left) is True

    def test_the_first_frame_is_never_rejected(self):
        """Nothing to compare against yet. One possibly bad frame beats
        blinding a camera every time its reader restarts."""
        damaged = measure_frame(scene(block=(320, 0, 320, 480)))
        assert looks_like_decode_damage(damaged, None) is False

    def test_a_small_bright_patch_is_never_damage(self):
        small = measure_frame(scene(block=(300, 200, 40, 40)))
        clean = measure_frame(scene())
        assert looks_like_decode_damage(small, clean) is False

    def test_undecodable_bytes_are_rejected(self):
        assert looks_like_decode_damage(None, None) is True

    def test_the_size_threshold_is_configurable(self, monkeypatch):
        clean = measure_frame(scene())
        block = measure_frame(scene(block=(560, 0, 80, 480)))  # ~12%
        monkeypatch.setattr(settings, "frame_corruption_max_flat_block_fraction", 0.04)
        assert looks_like_decode_damage(block, clean) is True
        monkeypatch.setattr(settings, "frame_corruption_max_flat_block_fraction", 0.5)
        assert looks_like_decode_damage(block, clean) is False


class TestMeasureFrame:
    def test_no_frame_measures_nothing(self):
        assert measure_frame(None) is None
        assert measure_frame(b"") is None

    def test_a_failing_measurement_does_not_filter(self, monkeypatch):
        """The check failing must not blind a camera — this filter has
        already done that once by rejecting too much."""

        def boom(_frame):
            raise RuntimeError("decoder exploded")

        monkeypatch.setattr("app.services.frame_quality.largest_flat_block", boom)
        measured = measure_frame(scene(block=(320, 0, 320, 480)))
        assert measured is not None
        assert looks_like_decode_damage(measured, None) is False


@pytest.mark.parametrize(
    "fraction, expected",
    [
        (0.000, False),  # empty corridor at night
        (0.018, False),  # brightest intact frame in the sampled events
        (0.066, True),   # least damaged corrupt frame
        (0.288, True),   # worst measured
    ],
)
def test_the_size_threshold_sits_in_the_measured_gap(fraction, expected):
    """Size alone no longer decides, but it is still the first filter, and
    it has to keep straddling the gap the production sample showed."""
    clean = FlatBlock(0.0, (0, 0, 0, 0))
    moved = FlatBlock(fraction, (0, 0, 40, 40))
    assert looks_like_decode_damage(moved, clean) is expected
