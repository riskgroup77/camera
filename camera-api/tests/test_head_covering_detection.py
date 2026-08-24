import numpy as np
import pytest

from app.services.head_covering_detection import color_uniformity, head_top_bbox, is_wearing_head_covering
from app.services.pose_detection import LEFT_EAR, NOSE, RIGHT_EAR


def _make_points(nose_y=0.3, ear_y=0.28, ear_x_l=0.42, ear_x_r=0.58, visibility=1.0):
    points = np.zeros((33, 4))
    points[NOSE] = [(ear_x_l + ear_x_r) / 2, nose_y, 0.0, visibility]
    points[LEFT_EAR] = [ear_x_l, ear_y, 0.0, visibility]
    points[RIGHT_EAR] = [ear_x_r, ear_y, 0.0, visibility]
    return points


def _solid_color_frame(width=200, height=200, bgr=(200, 50, 50)):
    return np.full((height, width, 3), bgr, dtype=np.uint8)


def _noisy_frame(width=200, height=200, seed=0):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)


class TestHeadTopBbox:
    def test_returns_none_when_landmarks_not_visible(self):
        points = _make_points(visibility=0.1)
        assert head_top_bbox(points, 200, 200) is None

    def test_returns_a_sane_box_above_the_face(self):
        points = _make_points()
        bbox = head_top_bbox(points, 200, 200)
        assert bbox is not None
        x1, y1, x2, y2 = bbox
        assert 0 <= x1 < x2 <= 200
        assert 0 <= y1 < y2 <= 200


class TestColorUniformity:
    def test_solid_color_region_is_highly_uniform(self):
        frame = _solid_color_frame()
        assert color_uniformity(frame, (50, 50, 150, 150)) > 0.9

    def test_random_noise_region_is_not_uniform(self):
        frame = _noisy_frame()
        assert color_uniformity(frame, (50, 50, 150, 150)) < 0.55

    def test_empty_bbox_is_zero(self):
        frame = _solid_color_frame()
        assert color_uniformity(frame, (10, 10, 10, 10)) == 0.0


class TestIsWearingHeadCovering:
    def test_solid_color_head_region_is_detected(self):
        points = _make_points()
        frame = _solid_color_frame()
        assert is_wearing_head_covering(frame, points) is True

    def test_noisy_head_region_is_not_detected(self):
        points = _make_points()
        frame = _noisy_frame()
        assert is_wearing_head_covering(frame, points) is False

    def test_low_visibility_landmarks_is_not_detected(self):
        points = _make_points(visibility=0.1)
        frame = _solid_color_frame()
        assert is_wearing_head_covering(frame, points) is False
