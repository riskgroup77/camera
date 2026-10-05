"""Tergov qidiruvi: rasm bo'yicha odam topish va uning kunlik yo'li.

Bu yerda faqat hisob-kitob (o'xshashlik, to'xtashlarga yig'ish) — HTTP,
huquq va audit app/routers/person_locator.py da. Ikkala qism ham sof
funksiyalar: ularni bazasiz sinash mumkin.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from app.services.face_matching import CandidateMatrix, _normalize_rows

# Bir kamerada shu oraliqdan qisqa tanaffus bilan ketma-ket kelgan
# tashriflar bitta "to'xtash" bo'ladi. PresenceVisit o'zi ham yaqin
# ko'rinishlarni birlashtiradi (presence_visit_gap_minutes), lekin
# odam kamera chetiga chiqib-kirganda baribir bir necha qator hosil
# bo'ladi — yo'l ko'rinishida ular bitta joy.
STOP_MERGE_GAP = timedelta(minutes=3)


def top_people(matrix: CandidateMatrix, embedding: list[float], limit: int, minimum: float) -> list[tuple[str, float]]:
    """Ro'yxatdagi eng yaqin `limit` odam (o'xshashlik >= minimum), kamayish
    tartibida. Galereya bo'lsa har odamning eng yaqin namunasi olinadi —
    tanish bilan bir xil qoida (CandidateMatrix._person_similarities)."""
    if matrix.is_empty:
        return []
    query = _normalize_rows(np.asarray([embedding], dtype=np.float64))
    sims = matrix._person_similarities(query)[0]
    order = np.argsort(-sims)[:limit]
    return [(matrix.ids[int(i)], float(sims[int(i)])) for i in order if sims[int(i)] >= minimum]


def score_embeddings(embedding: list[float], stored: list[str]) -> list[float]:
    """Saqlangan JSON vektorlar bilan kosinus o'xshashlik. Buzilgan yoki
    o'lchami mos kelmagan yozuv -1 oladi (natijaga tushmaydi) — bitta eski
    qator butun qidiruvni yiqitmasligi kerak."""
    query = np.asarray(embedding, dtype=np.float64)
    norm = np.linalg.norm(query)
    if norm > 0:
        query = query / norm
    out: list[float] = []
    for raw in stored:
        try:
            vec = np.asarray(json.loads(raw), dtype=np.float64)
        except (TypeError, ValueError):
            out.append(-1.0)
            continue
        if vec.shape != query.shape:
            out.append(-1.0)
            continue
        vnorm = np.linalg.norm(vec)
        out.append(float(np.dot(query, vec / vnorm)) if vnorm > 0 else -1.0)
    return out


@dataclass
class VisitRow:
    camera_id: str | None
    camera_name: str | None
    building: str | None
    floor: int | None
    zone: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    sightings: int
    best_similarity: float | None


@dataclass
class Stop:
    camera_id: str | None
    camera_name: str | None
    building: str | None
    floor: int | None
    zone: str | None
    started_at: datetime
    ended_at: datetime
    count: int
    best_similarity: float | None


def group_stops(visits: list[VisitRow], gap: timedelta = STOP_MERGE_GAP) -> list[Stop]:
    """Tashriflarni vaqt bo'yicha tartiblab, bir kamerada ketma-ket
    kelganlarini (oraliq <= gap) bitta to'xtashga yig'adi. Orada boshqa
    kamera bo'lsa — yangi to'xtash: odam ketib, qaytib kelgan."""
    stops: list[Stop] = []
    for visit in sorted(visits, key=lambda v: v.first_seen_at):
        last = stops[-1] if stops else None
        if last is not None and last.camera_id == visit.camera_id and visit.first_seen_at - last.ended_at <= gap:
            last.ended_at = max(last.ended_at, visit.last_seen_at)
            last.count += visit.sightings
            if visit.best_similarity is not None and (
                last.best_similarity is None or visit.best_similarity > last.best_similarity
            ):
                last.best_similarity = visit.best_similarity
            continue
        stops.append(
            Stop(
                camera_id=visit.camera_id,
                camera_name=visit.camera_name,
                building=visit.building,
                floor=visit.floor,
                zone=visit.zone,
                started_at=visit.first_seen_at,
                ended_at=visit.last_seen_at,
                count=visit.sightings,
                best_similarity=visit.best_similarity,
            )
        )
    return stops
