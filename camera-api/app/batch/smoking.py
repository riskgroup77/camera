"""Chekish (#15): klipdagi poza ketma-ketligidan takroriy qo'l-og'iz harakati.

Sigaret kadrda bir necha piksel — umumiy (COCO) detektor uni ko'rmaydi.
Lekin chekish HARAKATI ko'rinadi: qo'l og'izga ko'tariladi, 1-4 soniya
turadi, tushadi va bir necha o'n soniyadan keyin takrorlanadi. Real vaqt
rejimida bitta-ikkita kadr bu takrorni ko'ra olmasdi; kunlik tahlilda 20
soniyalik klip 2 kadr/s bilan o'qiladi va har odamning pozasi kuzatiladi.

Qoida (har poza izi uchun):
  * "qo'l og'izda" — bilak og'iz nuqtasiga yelka kengligining
    `smoking_hand_mouth_ratio` qismidan yaqin va tirsakdan yuqorida;
  * epizod — ketma-ket "qo'l og'izda" kadrlari, 0,5–6 soniya (uzoqroq —
    iyagini qo'liga tirab o'tirgan odam);
  * kamida `smoking_min_episodes` epizod (oralarida qo'l tushgan) — nomzod;
  * istisno: epizod paytida qo'l yonida telefon (qo'ng'iroq), stakan yoki
    shisha (ichish) bo'lsa — rad.
Ixtiyoriy sigaret detektori (`smoking_model_path`) ishonchni oshiradi yoki
pasaytiradi. Natija har doim operator tekshiruviga (sinov rejimi) boradi.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from app.config import settings
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

MIN_VISIBILITY = 0.4
MAX_EPISODE_SECONDS = 6.0
# COCO: 39 shisha, 41 stakan, 67 telefon — qo'l yonida bo'lsa chekish emas.
EXCLUDING_CLASSES = frozenset({39, 41, 67})
CIGARETTE_WORDS = ("cigar", "sigar", "smok", "vape", "chek")


@dataclass
class PoseFrame:
    at: datetime
    poses: list[PoseLandmarks]
    size: tuple[int, int]  # (eni, bo'yi) piksel
    objects: list = field(default_factory=list)  # DetectedObject (piksel bbox)
    cigarettes: list = field(default_factory=list)  # maxsus model topganlari


@dataclass
class SmokingCandidate:
    frame_index: int
    at: datetime
    episodes: int
    confidence: int
    head_box: tuple[float, float, float, float]  # piksel — yuz/kishi bilan bog'lash uchun
    cigarette_seen: bool


def _px(pose: PoseLandmarks, index: int, size: tuple[int, int]) -> tuple[float, float] | None:
    point = pose.points[index]
    if point[3] < MIN_VISIBILITY:
        return None
    return float(point[0]) * size[0], float(point[1]) * size[1]


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def shoulder_width(pose: PoseLandmarks, size: tuple[int, int]) -> float | None:
    left = _px(pose, LEFT_SHOULDER, size)
    right = _px(pose, RIGHT_SHOULDER, size)
    if left is None or right is None:
        return None
    width = _dist(left, right)
    return width if width >= 8 else None


def mouth_point(pose: PoseLandmarks, size: tuple[int, int], width: float) -> tuple[float, float] | None:
    nose = _px(pose, NOSE, size)
    if nose is None:
        return None
    # COCO pozasida og'iz nuqtasi yo'q — burundan biroz pastda.
    return nose[0], nose[1] + 0.18 * width


def anchor(pose: PoseLandmarks, size: tuple[int, int]) -> tuple[float, float] | None:
    """Poza izini bog'lash nuqtasi: yelkalar o'rtasi, bo'lmasa burun."""
    left = _px(pose, LEFT_SHOULDER, size)
    right = _px(pose, RIGHT_SHOULDER, size)
    if left is not None and right is not None:
        return (left[0] + right[0]) / 2, (left[1] + right[1]) / 2
    return _px(pose, NOSE, size)


def hand_at_mouth(pose: PoseLandmarks, size: tuple[int, int]) -> tuple[float, float] | None:
    """Og'izga yaqin bilak nuqtasi (piksel) — yoki None."""
    width = shoulder_width(pose, size)
    if width is None:
        return None
    mouth = mouth_point(pose, size, width)
    if mouth is None:
        return None
    best: tuple[float, tuple[float, float]] | None = None
    for wrist_index, elbow_index in ((LEFT_WRIST, LEFT_ELBOW), (RIGHT_WRIST, RIGHT_ELBOW)):
        wrist = _px(pose, wrist_index, size)
        if wrist is None:
            continue
        elbow = _px(pose, elbow_index, size)
        if elbow is not None and wrist[1] > elbow[1]:
            continue  # bilak tirsakdan past — qo'l ko'tarilmagan
        distance = _dist(wrist, mouth)
        if distance <= settings.smoking_hand_mouth_ratio * width and (best is None or distance < best[0]):
            best = (distance, wrist)
    return None if best is None else best[1]


def link_pose_tracks(frames: list[PoseFrame]) -> list[list[tuple[int, PoseLandmarks]]]:
    """Kadrlar bo'ylab bir odamning pozalarini bog'laydi (eng yaqin yelka
    o'rtasi, yelka kengligidan uzoq bo'lmasa)."""
    tracks: list[list[tuple[int, PoseLandmarks]]] = []
    for index, frame in enumerate(frames):
        taken: set[int] = set()
        for pose in frame.poses:
            point = anchor(pose, frame.size)
            if point is None:
                continue
            width = shoulder_width(pose, frame.size) or 40.0
            best_track, best_distance = None, None
            for track_index, track in enumerate(tracks):
                if track_index in taken:
                    continue
                last_index, last_pose = track[-1]
                if index - last_index > 3:
                    continue
                last_point = anchor(last_pose, frames[last_index].size)
                if last_point is None:
                    continue
                distance = _dist(point, last_point)
                if distance <= 1.2 * width and (best_distance is None or distance < best_distance):
                    best_track, best_distance = track_index, distance
            if best_track is None:
                tracks.append([(index, pose)])
                taken.add(len(tracks) - 1)
            else:
                tracks[best_track].append((index, pose))
                taken.add(best_track)
    return tracks


def _near(point: tuple[float, float], box, radius: float) -> bool:
    x1, y1, x2, y2 = (float(v) for v in box[:4])
    cx, cy = min(max(point[0], x1), x2), min(max(point[1], y1), y2)
    return math.hypot(point[0] - cx, point[1] - cy) <= radius


def _episodes(flags: list[bool], fps: float) -> list[tuple[int, int]]:
    max_frames = max(1, int(MAX_EPISODE_SECONDS * fps))
    runs: list[tuple[int, int]] = []
    start = None
    for i, flag in enumerate(flags + [False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start <= max_frames:
                runs.append((start, i - 1))
            start = None
    return runs


def _head_box(pose: PoseLandmarks, size: tuple[int, int]) -> tuple[float, float, float, float]:
    width = shoulder_width(pose, size) or 40.0
    nose = _px(pose, NOSE, size) or anchor(pose, size) or (0.0, 0.0)
    half = 0.45 * width
    return nose[0] - half, nose[1] - 1.2 * half, nose[0] + half, nose[1] + half


def detect_smoking(frames: list[PoseFrame], fps: float) -> list[SmokingCandidate]:
    candidates: list[SmokingCandidate] = []
    model_configured = bool(settings.smoking_model_path.strip())
    for track in link_pose_tracks(frames):
        if len(track) < 3:
            continue
        by_frame = {index: pose for index, pose in track}
        first, last = track[0][0], track[-1][0]
        flags: list[bool] = []
        wrists: list[tuple[float, float] | None] = []
        for index in range(first, last + 1):
            pose = by_frame.get(index)
            wrist = hand_at_mouth(pose, frames[index].size) if pose is not None else None
            flags.append(wrist is not None)
            wrists.append(wrist)
        episodes = _episodes(flags, fps)
        if len(episodes) < settings.smoking_min_episodes:
            continue
        excluded = False
        cigarette_seen = False
        for start, end in episodes:
            for offset in range(start, end + 1):
                wrist = wrists[offset]
                frame = frames[first + offset]
                pose = by_frame.get(first + offset)
                if wrist is None or pose is None:
                    continue
                radius = 0.6 * (shoulder_width(pose, frame.size) or 40.0)
                if any(
                    getattr(obj, "class_id", None) in EXCLUDING_CLASSES and _near(wrist, obj.bbox, radius)
                    for obj in frame.objects
                ):
                    excluded = True
                if any(_near(wrist, box, radius * 1.5) for box in frame.cigarettes):
                    cigarette_seen = True
        if excluded:
            continue
        confidence = 45 + 12 * (len(episodes) - settings.smoking_min_episodes)
        if cigarette_seen:
            confidence += 25
        elif model_configured:
            confidence -= 15
        confidence = int(max(5, min(95, confidence)))
        best_start, best_end = max(episodes, key=lambda run: run[1] - run[0])
        frame_index = first + (best_start + best_end) // 2
        pose = by_frame.get(frame_index) or track[-1][1]
        candidates.append(
            SmokingCandidate(
                frame_index=frame_index,
                at=frames[frame_index].at,
                episodes=len(episodes),
                confidence=confidence,
                head_box=_head_box(pose, frames[frame_index].size),
                cigarette_seen=cigarette_seen,
            )
        )
    return candidates


def cigarette_boxes(detections: list) -> list[tuple[float, float, float, float]]:
    """Maxsus model natijalaridan sigaret/vape sinflari."""
    out = []
    for detection in detections:
        name = str(getattr(detection, "class_name", "")).lower()
        if any(word in name for word in CIGARETTE_WORDS):
            out.append(tuple(float(v) for v in detection.bbox[:4]))
    return out


def movement_score(pose_a: PoseLandmarks, pose_b: PoseLandmarks, size: tuple[int, int]) -> float | None:
    """O'qituvchi faolligi (#21): ikki poza orasidagi o'rtacha siljish,
    yelka kengligiga nisbatan (kameradan masofaga bog'liq emas), 0-100."""
    width = shoulder_width(pose_a, size) or shoulder_width(pose_b, size)
    if width is None:
        return None
    displacements = []
    for i in range(pose_a.points.shape[0]):
        a, b = _px(pose_a, i, size), _px(pose_b, i, size)
        if a is not None and b is not None:
            displacements.append(_dist(a, b))
    if not displacements:
        return None
    relative = float(np.mean(displacements)) / width
    # 0,5 yelka kengligi siljish (qadam, qo'l harakati) — to'liq faollik.
    return float(min(100.0, relative / 0.5 * 100.0))
