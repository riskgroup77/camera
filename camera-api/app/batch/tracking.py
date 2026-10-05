"""Klip ichida yuz izlari (track) va ularning birlashtirilgan vektori.

Real vaqt rejimida har kadr alohida tanilardi: kichik yoki qiya yuz bitta
kadrda 0,45 o'xshashlik berib, "tanilmadi" bo'lib qolardi. Videoda bir
odamni ketma-ket bir necha kadrda ko'ramiz — izning vektorlarini sifat
bo'yicha og'irlik bilan o'rtachalash shovqinni kamaytiradi va o'xshashlikni
barqarorlashtiradi (bir xil odamning kadrlari o'zaro 0,6–0,8, boshqa odam
bilan ~0,1). Natijada bitta kuzatuv = bitta iz.

Bog'lash qoidasi (ochko'z): yangi yuz oxirgi ko'rinishi `max_gap` dan
yaqin bo'lgan izga ulanadi, agar
  * ikkalasining vektori bor va o'xshashligi >= APPEARANCE_LINK, yoki
  * ramkalar kesishmasi >= IOU_LINK va vektorlar bir-biriga zid emas
    (o'xshashlik >= APPEARANCE_FLOOR yoki vektor yo'q — yuz juda kichik).
Ikki boshqa odamning ArcFace vektorlari ~0 o'xshash: ramka ustma-ust
tushsa ham (yonma-yon o'tganda) ular bitta izga qo'shilmaydi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

APPEARANCE_LINK = 0.40
APPEARANCE_FLOOR = 0.20
IOU_LINK = 0.30


@dataclass
class FaceSample:
    at: datetime
    frame_index: int
    bbox: tuple[float, float, float, float]
    embedding: np.ndarray | None
    quality: float
    face_px: int
    frontal: bool | None = None
    phone: bool = False
    coat: bool | None = None  # oq / oq emas / noaniq
    coat_fraction: float | None = None


@dataclass
class Track:
    samples: list[FaceSample] = field(default_factory=list)

    @property
    def last(self) -> FaceSample:
        return self.samples[-1]

    @property
    def first_at(self) -> datetime:
        return self.samples[0].at

    @property
    def last_at(self) -> datetime:
        return self.samples[-1].at

    @property
    def face_px(self) -> int:
        return max(sample.face_px for sample in self.samples)

    def last_embedding(self) -> np.ndarray | None:
        for sample in reversed(self.samples):
            if sample.embedding is not None:
                return sample.embedding
        return None

    def fused_embedding(self) -> np.ndarray | None:
        vectors, weights = [], []
        for sample in self.samples:
            if sample.embedding is None:
                continue
            norm = float(np.linalg.norm(sample.embedding))
            if norm <= 0:
                continue
            vectors.append(sample.embedding / norm)
            weights.append(max(sample.quality, 1e-3))
        if not vectors:
            return None
        fused = np.average(np.stack(vectors), axis=0, weights=np.asarray(weights))
        norm = float(np.linalg.norm(fused))
        return fused / norm if norm > 0 else None

    def self_consistency(self) -> float | None:
        """Iz vektorlarining birlashtirilgan vektor bilan eng past
        o'xshashligi — iz ikki odamni aralashtirib yubormaganini tekshirish."""
        fused = self.fused_embedding()
        if fused is None:
            return None
        sims = [
            float(np.dot(sample.embedding / np.linalg.norm(sample.embedding), fused))
            for sample in self.samples
            if sample.embedding is not None and np.linalg.norm(sample.embedding) > 0
        ]
        return min(sims) if sims else None


def iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = (float(v) for v in a[:4])
    bx1, by1, bx2, by2 = (float(v) for v in b[:4])
    ix = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def _unit(vector: np.ndarray | None) -> np.ndarray | None:
    if vector is None:
        return None
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 0 else None


class TrackBuilder:
    """Kadrlar ketma-ket beriladi; uzilgan izlar `add` natijasida qaytadi."""

    def __init__(self, max_gap_seconds: float) -> None:
        self.max_gap = max_gap_seconds
        self.active: list[Track] = []

    def add(self, at: datetime, samples: list[FaceSample]) -> list[Track]:
        finished = [track for track in self.active if (at - track.last_at).total_seconds() > self.max_gap]
        self.active = [track for track in self.active if track not in finished]

        # Har juftlik uchun bal; eng yaxshisidan boshlab bog'lanadi.
        scored: list[tuple[float, int, int]] = []
        for si, sample in enumerate(samples):
            vector = _unit(sample.embedding)
            for ti, track in enumerate(self.active):
                if track.last.frame_index == sample.frame_index:
                    continue
                track_vector = _unit(track.last_embedding())
                similarity = (
                    float(np.dot(vector, track_vector)) if vector is not None and track_vector is not None else None
                )
                if similarity is not None and similarity >= APPEARANCE_LINK:
                    scored.append((1.0 + similarity, si, ti))
                    continue
                if similarity is not None and similarity < APPEARANCE_FLOOR:
                    continue  # boshqa odam
                overlap = iou(sample.bbox, track.last.bbox)
                if overlap >= IOU_LINK:
                    scored.append((overlap, si, ti))
        scored.sort(reverse=True)
        used_samples: set[int] = set()
        used_tracks: set[int] = set()
        for _score, si, ti in scored:
            if si in used_samples or ti in used_tracks:
                continue
            self.active[ti].samples.append(samples[si])
            used_samples.add(si)
            used_tracks.add(ti)
        for si, sample in enumerate(samples):
            if si not in used_samples:
                self.active.append(Track(samples=[sample]))
        return finished

    def flush(self) -> list[Track]:
        finished, self.active = self.active, []
        return finished
