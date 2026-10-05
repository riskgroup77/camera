"""Chekish (#15) — sintetik poza ketma-ketliklari bilan.

Ijobiy holat: qo'l og'izga bir necha marta ko'tariladi. Salbiy holatlar:
bir marta (burun qashish), qo'l uzoq og'izda (iyak tirab o'tirish),
telefonda gaplashish, ichish, qo'l ko'tarilmagan, ikki odam yonma-yon."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.batch.smoking import (
    PoseFrame,
    detect_smoking,
    hand_at_mouth,
    link_pose_tracks,
    movement_score,
)
from app.config import settings
from app.services.object_detection import DetectedObject
from app.services.pose_detection import (
    LEFT_ELBOW,
    LEFT_SHOULDER,
    LEFT_WRIST,
    NOSE,
    RIGHT_ELBOW,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
    PoseLandmarks,
)

SIZE = (1280, 720)
FPS = 2.0
T0 = datetime(2026, 10, 5, 7, 0, tzinfo=timezone.utc)


def pose(cx=0.5, hand_up=False, visible=0.9, shift=0.0) -> PoseLandmarks:
    points = np.zeros((33, 4))
    x = cx + shift
    points[NOSE] = (x, 0.38, 0, visible)
    points[LEFT_SHOULDER] = (x - 0.05, 0.50, 0, visible)
    points[RIGHT_SHOULDER] = (x + 0.05, 0.50, 0, visible)
    points[LEFT_ELBOW] = (x - 0.07, 0.62, 0, visible)
    points[RIGHT_ELBOW] = (x + 0.06, 0.58, 0, visible)
    points[LEFT_WRIST] = (x - 0.08, 0.75, 0, visible)
    if hand_up:
        mouth_y = (0.38 * SIZE[1] + 0.18 * 0.10 * SIZE[0]) / SIZE[1]
        points[RIGHT_WRIST] = (x + 0.01, mouth_y + 0.005, 0, visible)
    else:
        points[RIGHT_WRIST] = (x + 0.08, 0.75, 0, visible)
    return PoseLandmarks(points=points)


def sequence(up_frames: set[int], n=40, people=1, objects=None, cigarettes=None) -> list[PoseFrame]:
    frames = []
    for i in range(n):
        poses = [pose(hand_up=i in up_frames)]
        if people > 1:
            poses.append(pose(cx=0.8))
        frames.append(
            PoseFrame(
                at=T0 + timedelta(seconds=i / FPS),
                poses=poses,
                size=SIZE,
                objects=(objects or {}).get(i, []),
                cigarettes=(cigarettes or {}).get(i, []),
            )
        )
    return frames


def phone_at_wrist(i):
    x = (0.51) * SIZE[0]
    y = ((0.38 * SIZE[1] + 0.18 * 0.10 * SIZE[0]) / SIZE[1] + 0.005) * SIZE[1]
    return DetectedObject(class_id=67, class_name="cell phone", confidence=0.8, bbox=(x - 10, y - 15, x + 10, y + 15))


def test_hand_at_mouth_geometry():
    assert hand_at_mouth(pose(hand_up=True), SIZE) is not None
    assert hand_at_mouth(pose(hand_up=False), SIZE) is None
    # Ko'rinmas nuqtalar — qaror yo'q.
    assert hand_at_mouth(pose(hand_up=True, visible=0.1), SIZE) is None


def test_repeated_hand_to_mouth_is_smoking():
    frames = sequence({4, 5, 6, 16, 17, 18, 30, 31})
    found = detect_smoking(frames, FPS)
    assert len(found) == 1
    assert found[0].episodes == 3
    assert found[0].confidence == 45 + 12
    assert 4 <= found[0].frame_index <= 31
    x1, y1, x2, y2 = found[0].head_box
    assert x1 < 0.5 * SIZE[0] < x2 and y1 < 0.38 * SIZE[1] < y2


def test_single_gesture_is_not_smoking():
    assert detect_smoking(sequence({10, 11}), FPS) == []


def test_hand_resting_at_chin_for_long_is_not_smoking():
    # 8 s uzluksiz + qisqa epizod — uzuni hisobga kirmaydi.
    up = set(range(2, 18)) | {30, 31}
    assert detect_smoking(sequence(up), FPS) == []


def test_phone_call_is_excluded():
    up = {4, 5, 6, 16, 17, 18}
    objects = {i: [phone_at_wrist(i)] for i in up}
    assert detect_smoking(sequence(up, objects=objects), FPS) == []


def test_drinking_is_excluded():
    up = {4, 5, 16, 17}
    cup = {i: [DetectedObject(41, "cup", 0.7, phone_at_wrist(i).bbox)] for i in up}
    assert detect_smoking(sequence(up, objects=cup), FPS) == []


def test_unrelated_object_far_away_does_not_exclude():
    up = {4, 5, 16, 17}
    far = {i: [DetectedObject(67, "cell phone", 0.8, (10, 10, 30, 40))] for i in up}
    assert len(detect_smoking(sequence(up, objects=far), FPS)) == 1


def test_cigarette_model_raises_confidence(monkeypatch):
    up = {4, 5, 16, 17}
    cig = {5: [phone_at_wrist(5).bbox]}
    found = detect_smoking(sequence(up, cigarettes=cig), FPS)
    assert found[0].cigarette_seen and found[0].confidence == 45 + 25
    # Model sozlangan, lekin sigaret ko'rmadi — ishonch pasayadi.
    monkeypatch.setattr(settings, "smoking_model_path", "smoking.pt")
    found = detect_smoking(sequence(up), FPS)
    assert found[0].confidence == 45 - 15


def test_second_person_nearby_is_tracked_separately():
    frames = sequence({4, 5, 16, 17}, people=2)
    tracks = link_pose_tracks(frames)
    assert len(tracks) == 2
    assert all(len(track) == 40 for track in tracks)
    assert len(detect_smoking(frames, FPS)) == 1


def test_short_track_is_ignored():
    frames = sequence({0, 2}, n=2)
    assert detect_smoking(frames, FPS) == []


def test_frames_without_people_are_harmless():
    frames = [PoseFrame(at=T0, poses=[], size=SIZE) for _ in range(10)]
    assert detect_smoking(frames, FPS) == []
    assert link_pose_tracks(frames) == []


@pytest.mark.parametrize("min_episodes, expected", [(2, 1), (3, 1), (4, 0)])
def test_min_episodes_setting(monkeypatch, min_episodes, expected):
    monkeypatch.setattr(settings, "smoking_min_episodes", min_episodes)
    assert len(detect_smoking(sequence({2, 3, 10, 11, 20, 21}), FPS)) == expected


def test_movement_score_scale():
    still = movement_score(pose(), pose(), SIZE)
    assert still == 0
    walked = movement_score(pose(), pose(shift=0.05), SIZE)  # yarim yelka kengligi
    assert walked == pytest.approx(100.0, abs=1)
    small = movement_score(pose(), pose(shift=0.01), SIZE)
    assert 10 < small < 30
    invisible = pose(visible=0.0)
    assert movement_score(invisible, invisible, SIZE) is None
