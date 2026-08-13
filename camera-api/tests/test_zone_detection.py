import numpy as np

from app.services.pose_detection import LEFT_ANKLE, LEFT_HIP, RIGHT_ANKLE, RIGHT_HIP
from app.services.zone_detection import ground_position, is_inside_zone

SQUARE_ZONE = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]


class TestGroundPosition:
    def test_prefers_ankle_midpoint_when_visible(self):
        points = np.zeros((33, 4))
        points[LEFT_ANKLE] = [0.4, 0.9, 0.0, 1.0]
        points[RIGHT_ANKLE] = [0.6, 0.9, 0.0, 1.0]
        points[LEFT_HIP] = [0.4, 0.5, 0.0, 1.0]
        points[RIGHT_HIP] = [0.6, 0.5, 0.0, 1.0]
        assert ground_position(points) == (0.5, 0.9)

    def test_falls_back_to_hip_midpoint_when_ankles_not_visible(self):
        points = np.zeros((33, 4))
        points[LEFT_ANKLE] = [0.4, 0.9, 0.0, 0.1]
        points[RIGHT_ANKLE] = [0.6, 0.9, 0.0, 0.1]
        points[LEFT_HIP] = [0.4, 0.5, 0.0, 1.0]
        points[RIGHT_HIP] = [0.6, 0.5, 0.0, 1.0]
        assert ground_position(points) == (0.5, 0.5)

    def test_none_when_neither_ankles_nor_hips_are_visible(self):
        points = np.zeros((33, 4))
        assert ground_position(points) is None


class TestIsInsideZone:
    def test_point_well_inside_the_polygon_is_inside(self):
        assert is_inside_zone((0.5, 0.5), SQUARE_ZONE) is True

    def test_point_well_outside_the_polygon_is_outside(self):
        assert is_inside_zone((0.05, 0.05), SQUARE_ZONE) is False

    def test_point_on_the_edge_counts_as_inside(self):
        assert is_inside_zone((0.2, 0.5), SQUARE_ZONE) is True

    def test_degenerate_polygon_is_never_inside(self):
        assert is_inside_zone((0.5, 0.5), [[0.2, 0.2], [0.8, 0.8]]) is False

    def test_empty_polygon_is_never_inside(self):
        assert is_inside_zone((0.5, 0.5), []) is False
