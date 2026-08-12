from pathlib import Path

import insightface
import numpy as np

from app.services.face_recognition import detect_faces
from app.services.sleep_detection import (
    EAR_CLOSED_THRESHOLD,
    average_eye_aspect_ratio,
    is_asleep,
)

FACE_IMAGE_PATH = Path(insightface.__file__).parent / "data" / "images" / "t1.jpg"


def _flat_eye_landmarks() -> np.ndarray:
    """A synthetic 68-point array with both eyes squashed nearly flat
    (vertical span ~0.2 vs. a 6.0 horizontal span, per
    sleep_detection.RIGHT_EYE_INDICES/LEFT_EYE_INDICES) — everything else is
    zeroed since average_eye_aspect_ratio only ever reads the eye indices."""
    landmarks = np.zeros((68, 3))
    landmarks[36] = [0.0, 10.0, 0.0]
    landmarks[37] = [2.0, 10.1, 0.0]
    landmarks[38] = [4.0, 10.1, 0.0]
    landmarks[39] = [6.0, 10.0, 0.0]
    landmarks[40] = [4.0, 9.9, 0.0]
    landmarks[41] = [2.0, 9.9, 0.0]
    landmarks[42] = [10.0, 10.0, 0.0]
    landmarks[43] = [12.0, 10.1, 0.0]
    landmarks[44] = [14.0, 10.1, 0.0]
    landmarks[45] = [16.0, 10.0, 0.0]
    landmarks[46] = [14.0, 9.9, 0.0]
    landmarks[47] = [12.0, 9.9, 0.0]
    return landmarks


class TestAverageEyeAspectRatio:
    async def test_real_open_eyed_photo_is_above_threshold(self):
        faces = await detect_faces(FACE_IMAGE_PATH.read_bytes())
        assert len(faces) >= 1
        ear = average_eye_aspect_ratio(faces[0].landmarks_68)
        assert ear > EAR_CLOSED_THRESHOLD

    def test_flat_synthetic_eyes_are_below_threshold(self):
        ear = average_eye_aspect_ratio(_flat_eye_landmarks())
        assert ear < EAR_CLOSED_THRESHOLD


class TestIsAsleep:
    async def test_real_open_eyed_photo_reads_as_awake(self):
        faces = await detect_faces(FACE_IMAGE_PATH.read_bytes())
        assert is_asleep(faces[0].landmarks_68) is False

    def test_flat_synthetic_eyes_read_as_asleep(self):
        assert is_asleep(_flat_eye_landmarks()) is True
