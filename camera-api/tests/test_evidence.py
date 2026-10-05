"""Snapshot ustiga dalil chizish — xato bo'lsa asl kadr yo'qolmaydi."""

import cv2
import numpy as np

from app.services.evidence import Box, Polygon, annotate_snapshot, pose_box, zone_polygon


def _jpeg() -> bytes:
    image = np.full((120, 160, 3), 200, dtype=np.uint8)
    return cv2.imencode(".jpg", image)[1].tobytes()


def test_boxes_and_zone_are_drawn():
    original = _jpeg()
    annotated = annotate_snapshot(
        original,
        [Box(10, 10, 60, 60, label="odam"), Box(0.5, 0.1, 0.9, 0.4, normalized=True),
         Polygon(((0.5, 0.5), (0.9, 0.5), (0.9, 0.9)))],
    )
    assert annotated != original
    decoded = cv2.imdecode(np.frombuffer(annotated, np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (120, 160, 3)


def test_nothing_to_draw_or_broken_frame_returns_the_original():
    original = _jpeg()
    assert annotate_snapshot(original, []) is original
    assert annotate_snapshot(b"jpeg emas", [Box(0, 0, 1, 1)]) == b"jpeg emas"


def test_pose_box_needs_three_visible_points():
    points = np.zeros((33, 4))
    points[0] = [0.4, 0.2, 0, 0.9]
    points[1] = [0.6, 0.8, 0, 0.9]
    assert pose_box(points) is None
    points[2] = [0.5, 0.5, 0, 0.9]
    box = pose_box(points, label="odam")
    assert box is not None and box.normalized
    assert 0.0 <= box.x1 < 0.4 and 0.6 < box.x2 <= 1.0


def test_zone_polygon_parsing():
    assert zone_polygon([[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]]) is not None
    assert zone_polygon([[0.1, 0.1], [0.5, 0.1]]) is None
    assert zone_polygon([["x"], None]) is None
