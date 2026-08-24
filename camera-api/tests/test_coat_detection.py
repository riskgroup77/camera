import numpy as np
import pytest

from app.services.coat_detection import is_wearing_white_coat, torso_bbox, white_fraction
from app.services.pose_detection import LEFT_HIP, LEFT_SHOULDER, RIGHT_HIP, RIGHT_SHOULDER


def _make_points(shoulder_y=0.2, hip_y=0.5, shoulder_x_l=0.4, shoulder_x_r=0.6, visibility=1.0):
    points = np.zeros((33, 4))
    points[LEFT_SHOULDER] = [shoulder_x_l, shoulder_y, 0.0, visibility]
    points[RIGHT_SHOULDER] = [shoulder_x_r, shoulder_y, 0.0, visibility]
    points[LEFT_HIP] = [shoulder_x_l, hip_y, 0.0, visibility]
    points[RIGHT_HIP] = [shoulder_x_r, hip_y, 0.0, visibility]
    return points


def _white_frame(width=200, height=200):
    return np.full((height, width, 3), 250, dtype=np.uint8)  # near-white BGR


def _colored_frame(width=200, height=200, bgr=(40, 40, 200)):  # saturated red
    return np.full((height, width, 3), bgr, dtype=np.uint8)


class TestTorsoBbox:
    def test_returns_none_when_landmarks_not_visible(self):
        points = _make_points(visibility=0.1)
        assert torso_bbox(points, 200, 200) is None

    def test_returns_a_sane_box_when_visible(self):
        points = _make_points()
        bbox = torso_bbox(points, 200, 200)
        assert bbox is not None
        x1, y1, x2, y2 = bbox
        assert 0 <= x1 < x2 <= 200
        assert 0 <= y1 < y2 <= 200


class TestWhiteFraction:
    def test_all_white_region_is_fully_white(self):
        frame = _white_frame()
        assert white_fraction(frame, (50, 50, 150, 150)) == pytest.approx(1.0)

    def test_saturated_red_region_is_not_white(self):
        frame = _colored_frame()
        assert white_fraction(frame, (50, 50, 150, 150)) == pytest.approx(0.0)

    def test_empty_bbox_is_zero(self):
        frame = _white_frame()
        assert white_fraction(frame, (10, 10, 10, 10)) == 0.0


class TestIsWearingWhiteCoat:
    def test_white_torso_region_is_detected(self):
        points = _make_points()
        frame = _white_frame()
        assert is_wearing_white_coat(frame, points) is True

    def test_colored_torso_region_is_not_detected(self):
        points = _make_points()
        frame = _colored_frame()
        assert is_wearing_white_coat(frame, points) is False

    def test_low_visibility_landmarks_is_not_detected(self):
        points = _make_points(visibility=0.1)
        frame = _white_frame()
        assert is_wearing_white_coat(frame, points) is False
