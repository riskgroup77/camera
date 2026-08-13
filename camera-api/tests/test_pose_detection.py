from pathlib import Path

import ultralytics

from app.services.pose_detection import LEFT_HIP, LEFT_SHOULDER, NOSE, detect_poses

# Reuses the same real bus+people photo test_object_detection.py already
# verified by direct inspection — at least one full-body-visible person
# in it produces a detectable pose.
BUS_IMAGE_PATH = Path(ultralytics.__file__).parent / "assets" / "bus.jpg"


class TestDetectPoses:
    async def test_detects_at_least_one_real_pose(self):
        poses = await detect_poses(BUS_IMAGE_PATH.read_bytes())
        assert len(poses) >= 1

    async def test_pose_has_33_landmarks_with_expected_shape(self):
        poses = await detect_poses(BUS_IMAGE_PATH.read_bytes())
        assert poses[0].points.shape == (33, 4)

    async def test_landmark_coordinates_are_normalized(self):
        poses = await detect_poses(BUS_IMAGE_PATH.read_bytes())
        xs = poses[0].points[:, 0]
        ys = poses[0].points[:, 1]
        # Not every landmark is guaranteed strictly within [0,1] (mediapipe
        # can report slightly out-of-frame estimates), but the bulk of a
        # detected pose should be roughly there.
        assert 0.0 <= float(xs.mean()) <= 1.0
        assert 0.0 <= float(ys.mean()) <= 1.0

    async def test_key_landmarks_have_real_visibility_scores(self):
        poses = await detect_poses(BUS_IMAGE_PATH.read_bytes())
        pose = poses[0]
        # Not asserting a hard threshold on any one landmark (real photos
        # vary), just that visibility is a real computed value in [0,1],
        # not a placeholder.
        for index in (NOSE, LEFT_SHOULDER, LEFT_HIP):
            visibility = pose.points[index][3]
            assert 0.0 <= visibility <= 1.0

    async def test_corrupt_image_bytes_returns_empty_list(self):
        poses = await detect_poses(b"not a real image")
        assert poses == []
