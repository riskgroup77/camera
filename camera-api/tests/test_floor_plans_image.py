"""Qavat rejasi rasmini tekshirish: tur sehrli baytlardan, o'lcham sarlavhadan."""

import cv2
import numpy as np
import pytest

from app.services.floor_plans import MAX_PLAN_SIDE, PlanImageError, inspect_plan_image


def _encode(ext: str, width: int, height: int, params=None) -> bytes:
    ok, buf = cv2.imencode(ext, np.full((height, width, 3), 127, dtype=np.uint8), params or [])
    assert ok
    return buf.tobytes()


def _riff(chunk: bytes, payload: bytes) -> bytes:
    body = b"WEBP" + chunk + len(payload).to_bytes(4, "little") + payload
    return b"RIFF" + len(body).to_bytes(4, "little") + body


@pytest.mark.parametrize(
    ("ext", "content_type", "extension"),
    [(".png", "image/png", "png"), (".jpg", "image/jpeg", "jpg")],
)
def test_png_and_jpeg(ext, content_type, extension):
    image = inspect_plan_image(_encode(ext, 321, 123))
    assert (image.content_type, image.extension) == (content_type, extension)
    assert (image.width, image.height) == (321, 123)


def test_webp_from_encoder():
    try:
        data = _encode(".webp", 200, 100)
    except (cv2.error, AssertionError):
        pytest.skip("OpenCV bu muhitda WebP kodlay olmaydi")
    image = inspect_plan_image(data)
    assert image.content_type == "image/webp"
    assert (image.width, image.height) == (200, 100)


def test_webp_lossy_header():
    # VP8: 3 bayt kadr tegi, 9D 01 2A, en/bo'y 14 bitdan.
    payload = b"\x00\x00\x00" + b"\x9d\x01\x2a" + (640).to_bytes(2, "little") + (480).to_bytes(2, "little")
    image = inspect_plan_image(_riff(b"VP8 ", payload + b"\x00" * 16))
    assert (image.width, image.height) == (640, 480)


def test_webp_lossless_header():
    width, height = 1000, 700
    w, h = width - 1, height - 1
    bits = w | (h << 14)
    payload = b"\x2f" + bits.to_bytes(4, "little")
    image = inspect_plan_image(_riff(b"VP8L", payload + b"\x00" * 16))
    assert (image.width, image.height) == (width, height)


def test_webp_extended_header():
    payload = b"\x00\x00\x00\x00" + (1919).to_bytes(3, "little") + (1079).to_bytes(3, "little")
    image = inspect_plan_image(_riff(b"VP8X", payload + b"\x00" * 16))
    assert (image.width, image.height) == (1920, 1080)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"GIF89a" + b"\x00" * 40,
        b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
        b"\xff\xd8\xff" + b"\x00" * 10,  # JPEG boshi, lekin SOF yo'q
        b"RIFF\x00\x00\x00\x00WEBPXXXX" + b"\x00" * 30,
    ],
)
def test_rejects_invalid(data):
    with pytest.raises(PlanImageError):
        inspect_plan_image(data)


def test_rejects_huge_dimensions():
    png = bytearray(_encode(".png", 20, 20))
    png[16:20] = (MAX_PLAN_SIDE + 1).to_bytes(4, "big")
    with pytest.raises(PlanImageError, match="piksel"):
        inspect_plan_image(bytes(png))


def test_rejects_tiny_image():
    with pytest.raises(PlanImageError, match="kichik"):
        inspect_plan_image(_encode(".png", 4, 4))
