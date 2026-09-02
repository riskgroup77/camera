"""app/services/image_size.py reads JPEG dimensions from the header instead
of paying a full cv2.imdecode for two integers. Getting it WRONG is worse
than not having it: app/jobs/unauthorized_person_ai.py's face-size filter
divides by the frame height, so a bad height silently changes which faces
count as "too small to be a real person". These tests check it against
what a real decode reports, for real JPEGs."""

import io
from pathlib import Path

import cv2
import insightface
import numpy as np
import pytest
from PIL import Image

from app.services.image_size import jpeg_dimensions, jpeg_height

FACE_IMAGE_PATH = Path(insightface.__file__).parent / "data" / "images" / "t1.jpg"


def _decoded_dimensions(data: bytes) -> tuple[int, int]:
    """Ground truth: what a real decode says (width, height)."""
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    return img.shape[1], img.shape[0]


def _jpeg_of_size(width: int, height: int, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    Image.frombytes("RGB", (width, height), bytes([128] * width * height * 3)).save(
        buf, format="JPEG", quality=quality
    )
    return buf.getvalue()


class TestJpegDimensions:
    def test_matches_a_real_decode_on_a_real_photo(self):
        data = FACE_IMAGE_PATH.read_bytes()
        assert jpeg_dimensions(data) == _decoded_dimensions(data)

    @pytest.mark.parametrize("width,height", [(640, 360), (1920, 1080), (2560, 1440), (17, 5)])
    def test_matches_a_real_decode_across_sizes(self, width, height):
        data = _jpeg_of_size(width, height)
        assert jpeg_dimensions(data) == (width, height)
        assert jpeg_dimensions(data) == _decoded_dimensions(data)

    def test_progressive_jpeg_is_read_too(self):
        # Progressive JPEGs use SOF2 rather than SOF0 — dimensions live in
        # the same place, and ffmpeg output isn't the only source here.
        buf = io.BytesIO()
        Image.frombytes("RGB", (800, 600), bytes([200] * 800 * 600 * 3)).save(
            buf, format="JPEG", progressive=True
        )
        assert jpeg_dimensions(buf.getvalue()) == (800, 600)

    def test_height_helper_agrees(self):
        data = _jpeg_of_size(320, 240)
        assert jpeg_height(data) == 240

    def test_truncated_frame_reads_as_unknown_not_wrong(self):
        # A half-written MJPEG frame must return None (callers fail open),
        # never a plausible-but-wrong number.
        data = FACE_IMAGE_PATH.read_bytes()
        assert jpeg_dimensions(data[:20]) is None

    def test_non_jpeg_reads_as_unknown(self):
        assert jpeg_dimensions(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64) is None
        assert jpeg_dimensions(b"") is None
        assert jpeg_height(b"not an image at all") == 0
