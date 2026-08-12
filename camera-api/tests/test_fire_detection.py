import io
from pathlib import Path

import insightface
import numpy as np
import pytest
from PIL import Image

from app.services.fire_detection import fire_pixel_fraction, is_likely_fire

FACE_IMAGE_PATH = Path(insightface.__file__).parent / "data" / "images" / "t1.jpg"


def _jpeg_bytes(rgb: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _solid(rgb: tuple[int, int, int]) -> bytes:
    arr = np.zeros((100, 100, 3), dtype=np.uint8)
    arr[:, :] = rgb
    return _jpeg_bytes(arr)


class TestFirePixelFraction:
    def test_identical_real_photo_has_no_flicker(self):
        # The exact false-positive case that killed the earlier
        # color-only attempt (~20-26% of a real human photo's pixels
        # read as fire-colored) — with the flicker requirement added,
        # two identical frames of the same photo must read as zero,
        # since nothing changes between them.
        real_photo = FACE_IMAGE_PATH.read_bytes()
        assert fire_pixel_fraction(real_photo, real_photo) == 0.0
        assert is_likely_fire(real_photo, real_photo) is False

    def test_static_fire_colored_region_without_flicker_is_not_fire(self):
        static_orange = _solid((255, 140, 20))
        frac = fire_pixel_fraction(static_orange, static_orange)
        assert frac == 0.0
        assert is_likely_fire(static_orange, static_orange) is False

    def test_flickering_fire_colored_region_is_fire(self):
        dim = _solid((140, 70, 10))
        bright = _solid((255, 140, 20))
        frac = fire_pixel_fraction(dim, bright)
        assert frac > 0.5
        assert is_likely_fire(dim, bright) is True

    def test_flickering_non_fire_color_is_not_fire(self):
        dim_blue = _solid((10, 20, 80))
        bright_blue = _solid((20, 40, 200))
        frac = fire_pixel_fraction(dim_blue, bright_blue)
        assert frac == 0.0
        assert is_likely_fire(dim_blue, bright_blue) is False

    def test_mismatched_frame_sizes_returns_zero_without_raising(self):
        small = _jpeg_bytes(np.zeros((50, 50, 3), dtype=np.uint8))
        large = _jpeg_bytes(np.zeros((100, 100, 3), dtype=np.uint8))
        assert fire_pixel_fraction(small, large) == 0.0

    def test_undecodable_bytes_returns_zero_without_raising(self):
        assert fire_pixel_fraction(b"not an image", b"also not an image") == 0.0
