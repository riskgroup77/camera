"""Kadrlar bo'yicha yuz izlari va vektorlarni birlashtirish (fusion).

Muammo (production, 2026-09-19): xona kameralarida yuz kichik va bitta
kadrdagi ArcFace vektori shovqinli — odamning o'zi ham 0.40-0.50
o'xshashlikda qoladi va hech qachon tanilmaydi. Auditoriyada o'tirgan odam
esa bir joyda uzoq qoladi: shu joydagi yuzning bir necha kadrdagi
vektorlari o'rtachalansa, tasodifiy shovqin kamayadi va o'xshashlik
odatda sezilarli ko'tariladi (bir odamning N ta shovqinli namunasi
o'rtachasi uning "haqiqiy" vektoriga yaqinroq).

Iz — kamerada bir joyda (IoU >= face_track_iou) ketma-ket ko'ringan va
o'zaro o'xshash (>= face_track_min_self_similarity) yuzlar. O'xshashlik
sharti boshqa odam o'sha joyga o'tirsa izni yangidan boshlaydi. Iz
face_track_max_age_seconds davomida yangilanmasa o'chadi.

Faqat xotirada, jarayon ichida; hech narsa bazaga yozilmaydi.
"""

import threading
from dataclasses import dataclass

import numpy as np

from app.config import settings


def _iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = (float(v) for v in a[:4])
    bx1, by1, bx2, by2 = (float(v) for v in b[:4])
    width, height = min(ax2, bx2) - max(ax1, bx1), min(ay2, by2) - max(ay1, by1)
    if width <= 0 or height <= 0:
        return 0.0
    inter = width * height
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 0 else vector


@dataclass
class _Track:
    bbox: np.ndarray
    total: np.ndarray  # birlik vektorlar yig'indisi
    frames: int
    updated_at: float

    @property
    def mean(self) -> np.ndarray:
        return _unit(self.total)


@dataclass
class FusedFace:
    embedding: np.ndarray | None  # None — iz hali yetarlicha uzun emas
    frames: int


class TrackStore:
    def __init__(self) -> None:
        self._tracks: dict[str, list[_Track]] = {}
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._tracks.clear()

    def update(self, camera_key: str, faces: list, now: float) -> list[FusedFace]:
        """`faces` — embedding'i bor yuzlar. Har yuz uchun uning izining
        birlashtirilgan vektori (iz face_track_min_frames dan qisqa bo'lsa None)."""
        iou_min = settings.face_track_iou
        self_min = settings.face_track_min_self_similarity
        max_frames = max(1, settings.face_track_max_frames)
        min_frames = max(2, settings.face_track_min_frames)
        with self._lock:
            tracks = [
                t for t in self._tracks.get(camera_key, []) if now - t.updated_at <= settings.face_track_max_age_seconds
            ]
            claimed: set[int] = set()
            out: list[FusedFace] = []
            for face in faces:
                vector = _unit(np.asarray(face.embedding, dtype=np.float64))
                best, best_iou = None, iou_min
                for index, track in enumerate(tracks):
                    if index in claimed:
                        continue
                    overlap = _iou(face.bbox, track.bbox)
                    if overlap >= best_iou:
                        best, best_iou = index, overlap
                if best is not None and float(tracks[best].mean @ vector) >= self_min:
                    track = tracks[best]
                    if track.frames >= max_frames:
                        # Sirpanuvchi oyna: eski kadrlarning ulushi kamayadi.
                        track.total = track.total * ((max_frames - 1) / track.frames)
                        track.frames = max_frames - 1
                    track.total = track.total + vector
                    track.frames += 1
                    track.bbox = np.asarray(face.bbox, dtype=np.float64)
                    track.updated_at = now
                    claimed.add(best)
                else:
                    if best is not None:
                        # Boshqa odam o'sha joyda — eski iz almashtiriladi.
                        tracks.pop(best)
                        claimed = {i if i < best else i - 1 for i in claimed if i != best}
                    track = _Track(np.asarray(face.bbox, dtype=np.float64), vector.copy(), 1, now)
                    tracks.append(track)
                    claimed.add(len(tracks) - 1)
                out.append(FusedFace(track.mean if track.frames >= min_frames else None, track.frames))
            self._tracks[camera_key] = tracks
            return out


track_store = TrackStore()
