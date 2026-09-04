from pathlib import Path

import insightface
import numpy as np

from app.services.face_recognition import detect_faces
from app.config import settings
from app.services.sleep_detection import (
    is_face_measurable,
    EAR_CLOSED_THRESHOLD,
    average_eye_aspect_ratio,
    frontality_ratio,
    is_asleep,
    is_plausible_frontal,
)

FACE_IMAGE_PATH = Path(insightface.__file__).parent / "data" / "images" / "t1.jpg"


def _flat_eye_landmarks(nose_x: float = 8.0) -> np.ndarray:
    """A synthetic 68-point array with both eyes squashed nearly flat
    (vertical span ~0.2 vs. a 6.0 horizontal span, per
    sleep_detection.RIGHT_EYE_INDICES/LEFT_EYE_INDICES) and a nose tip
    placed at `nose_x` — everything else is zeroed since
    average_eye_aspect_ratio/frontality_ratio only ever read the eye and
    nose-tip indices. Defaults to a frontal-plausible nose position
    (midpoint between the outer eye corners at x=0.0 and x=16.0) so
    callers testing the EAR logic alone don't accidentally trip the
    unrelated pose gate — pass nose_x explicitly to test that gate."""
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
    landmarks[33] = [nose_x, 10.0, 0.0]
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


class TestFrontalityRatio:
    async def test_real_frontal_photo_is_near_midpoint(self):
        faces = await detect_faces(FACE_IMAGE_PATH.read_bytes())
        assert len(faces) >= 1
        ratio = frontality_ratio(faces[0].landmarks_68)
        assert is_plausible_frontal(faces[0].landmarks_68)
        assert 0.3 <= ratio <= 0.7  # a real face looking at the camera sits close to 0.5

    def test_nose_at_midpoint_is_plausible(self):
        assert is_plausible_frontal(_flat_eye_landmarks(nose_x=8.0)) is True

    def test_nose_skewed_hard_to_one_side_is_not_plausible(self):
        # Same eye geometry as the frontal case, but the nose tip sits far
        # to one side — the synthetic equivalent of a head turned sharply
        # away from the camera (see the module docstring's real EAR=1.3
        # example, produced by exactly this kind of oblique angle).
        assert is_plausible_frontal(_flat_eye_landmarks(nose_x=0.5)) is False
        assert is_plausible_frontal(_flat_eye_landmarks(nose_x=15.5)) is False


class TestIsAsleep:
    async def test_real_open_eyed_photo_reads_as_awake(self):
        faces = await detect_faces(FACE_IMAGE_PATH.read_bytes())
        assert is_asleep(faces[0].landmarks_68) is False

    def test_flat_synthetic_eyes_read_as_asleep(self):
        assert is_asleep(_flat_eye_landmarks()) is True

    def test_flat_synthetic_eyes_at_an_oblique_angle_do_not_read_as_asleep(self):
        # The actual bug this gate fixes: low-EAR geometry alone used to be
        # enough to read as "asleep" even when it came from a head turned
        # away from the camera, not genuinely closed eyes — see
        # sleep_detection.py's module docstring. Same eye geometry as
        # test_flat_synthetic_eyes_read_as_asleep above, but with an
        # implausible nose position — must now read as NOT asleep, since
        # the geometry can't be trusted at all at this angle.
        oblique = _flat_eye_landmarks(nose_x=0.5)
        assert average_eye_aspect_ratio(oblique) < EAR_CLOSED_THRESHOLD  # the raw EAR still reads "closed"
        assert is_asleep(oblique) is False  # but the pose gate rejects it before that matters


class TestFaceMeasurability:
    """Eye-aspect-ratio compares distances of a few pixels, and
    InsightFace happily returns 68 landmarks for a face of any size — it
    resamples the crop to 192x192 first, so the numbers keep arriving
    long after they stop describing anything.

    Measured over the sleep alerts stored in production: 19 of 89 had no
    face in the snapshot at all, and of the remaining 70 the MEDIAN face
    was 28 pixels tall. The eye opening on a face that small is about one
    pixel."""

    def test_a_face_below_the_floor_is_not_measurable(self):
        assert is_face_measurable([0, 0, 40, 28]) is False

    def test_a_face_at_the_floor_is(self):
        assert is_face_measurable([0, 0, 60, 80]) is True

    def test_the_floor_is_configurable(self, monkeypatch):
        monkeypatch.setattr(settings, "sleep_min_face_height_px", 20)
        assert is_face_measurable([0, 0, 40, 28]) is True

    def test_it_measures_height_not_width(self):
        """A wide, short box is not a large face — reading the wrong axis
        would let exactly the flat detections through."""
        assert is_face_measurable([0, 0, 400, 30]) is False

    def test_the_production_median_would_have_been_rejected(self):
        assert is_face_measurable([0, 0, 30, 28]) is False
