import numpy as np
import pytest

from app.services.fall_detection import _bbox_aspect_ratio, _torso_angle_from_vertical, is_fallen
from app.services.pose_detection import LEFT_HIP, LEFT_SHOULDER, RIGHT_HIP, RIGHT_SHOULDER


def _make_points(shoulder_y, hip_y, shoulder_x=0.5, hip_x=0.5, visibility=1.0):
    points = np.zeros((33, 4))
    points[LEFT_SHOULDER] = [shoulder_x, shoulder_y, 0.0, visibility]
    points[RIGHT_SHOULDER] = [shoulder_x, shoulder_y, 0.0, visibility]
    points[LEFT_HIP] = [hip_x, hip_y, 0.0, visibility]
    points[RIGHT_HIP] = [hip_x, hip_y, 0.0, visibility]
    return points


class TestTorsoAngleFromVertical:
    def test_standing_posture_reads_near_zero(self):
        points = _make_points(shoulder_y=0.2, hip_y=0.5, shoulder_x=0.5, hip_x=0.5)
        assert _torso_angle_from_vertical(points) == pytest.approx(0.0, abs=0.01)

    def test_fallen_posture_reads_near_ninety(self):
        points = _make_points(shoulder_y=0.5, hip_y=0.5, shoulder_x=0.3, hip_x=0.7)
        assert _torso_angle_from_vertical(points) == pytest.approx(90.0, abs=0.01)

    def test_leaning_posture_reads_an_intermediate_angle(self):
        # dx == dy -> exactly 45 degrees regardless of scale
        points = _make_points(shoulder_y=0.3, hip_y=0.6, shoulder_x=0.2, hip_x=0.5)
        assert _torso_angle_from_vertical(points) == pytest.approx(45.0, abs=0.01)

    def test_low_visibility_landmarks_return_none(self):
        points = _make_points(shoulder_y=0.5, hip_y=0.5, shoulder_x=0.3, hip_x=0.7, visibility=0.1)
        assert _torso_angle_from_vertical(points) is None


class TestBboxAspectRatio:
    def test_too_few_visible_points_returns_none(self):
        points = np.zeros((33, 4))
        points[0] = [0.5, 0.5, 0.0, 1.0]
        assert _bbox_aspect_ratio(points) is None

    def test_tall_narrow_box_has_low_aspect_ratio(self):
        points = np.zeros((33, 4))
        points[0] = [0.5, 0.1, 0.0, 1.0]
        points[1] = [0.5, 0.9, 0.0, 1.0]
        points[2] = [0.48, 0.5, 0.0, 1.0]
        points[3] = [0.52, 0.5, 0.0, 1.0]
        assert _bbox_aspect_ratio(points) < 0.2

    def test_wide_flat_box_has_high_aspect_ratio(self):
        points = np.zeros((33, 4))
        points[0] = [0.1, 0.5, 0.0, 1.0]
        points[1] = [0.9, 0.5, 0.0, 1.0]
        points[2] = [0.5, 0.48, 0.0, 1.0]
        points[3] = [0.5, 0.52, 0.0, 1.0]
        assert _bbox_aspect_ratio(points) > 5.0


class TestIsFallen:
    def test_standing_is_not_fallen(self):
        points = _make_points(shoulder_y=0.2, hip_y=0.6, shoulder_x=0.5, hip_x=0.5)
        points[25] = [0.5, 0.8, 0.0, 1.0]  # left knee
        points[27] = [0.5, 1.0, 0.0, 1.0]  # left ankle
        assert is_fallen(points) is False

    def test_horizontal_torso_is_fallen_via_angle(self):
        points = _make_points(shoulder_y=0.5, hip_y=0.52, shoulder_x=0.2, hip_x=0.6)
        assert is_fallen(points) is True

    def test_wide_flat_silhouette_without_a_clear_torso_angle_is_still_fallen_via_aspect_ratio(self):
        points = np.zeros((33, 4))
        # shoulders/hips present but too low-confidence to trust the angle from
        points[LEFT_SHOULDER] = [0.4, 0.5, 0.0, 0.1]
        points[RIGHT_SHOULDER] = [0.6, 0.5, 0.0, 0.1]
        points[LEFT_HIP] = [0.3, 0.5, 0.0, 0.1]
        points[RIGHT_HIP] = [0.7, 0.5, 0.0, 0.1]
        # other landmarks spread wide and flat, high confidence
        points[0] = [0.1, 0.48, 0.0, 1.0]
        points[16] = [0.9, 0.52, 0.0, 1.0]
        points[28] = [0.5, 0.55, 0.0, 1.0]
        points[27] = [0.5, 0.45, 0.0, 1.0]
        assert is_fallen(points) is True

    def test_no_visible_landmarks_at_all_is_not_fallen(self):
        points = np.zeros((33, 4))
        assert is_fallen(points) is False
