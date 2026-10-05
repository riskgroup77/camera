"""Ochiq sahifalar himoyasi: ism niqobi va juda katta rasmni ochmaslik."""

import struct

import pytest

from app.routers.enrollment import mask_name
from app.services.face_recognition import PNG_SIGNATURE, NoFaceDetectedError, _decode_image


def test_public_name_is_masked_but_recognisable():
    assert mask_name("Aliyev Anvar Valijon o'g'li") == "A*** Anvar V*** o***"
    assert mask_name("Karimova Dilnoza") == "K*** Dilnoza"


def test_huge_declared_image_is_rejected_before_decoding():
    header = PNG_SIGNATURE + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 60000, 60000) + bytes([8, 2, 0, 0, 0])
    with pytest.raises(NoFaceDetectedError):
        _decode_image(header)
