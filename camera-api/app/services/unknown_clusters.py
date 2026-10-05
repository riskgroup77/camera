"""Takroriy notanishlar — bir necha kun davomida qayta-qayta ko'ringan,
bazada yuzi yo'q odamlar.

MUAMMO (2026-09-24). Bazada yuzi borlar — 27% (7259 dan 1972). Kameralar
bir kunda 600 ta notanish yuzni saqladi (kunlik chegara kun o'rtasida
to'ldi), ularning yarmi 56 px dan yirik — ya'ni tanish uchun yetarlicha
sifatli. Birortasi ham odamga biriktirilmadi: ro'yxat kunlik va yuzma-yuz,
bitta odam o'nlab qator bo'lib chiqadi.

YECHIM. Kutilayotgan yuzlar (oxirgi N kun) bir odam bo'yicha guruhlanadi:
vektorlari settings.unknown_cluster_similarity dan o'xshash yuzlar bitta
guruh. Guruhlar necha KUN ko'ringani bo'yicha tartiblanadi — har kuni
keladigan odam (talaba, xodim) birinchi. Operator guruhga ism beradi:
eng yirik yuz odamning asosiy rasmi (yuzi bo'lmasa) yoki galereya
namunasi bo'ladi, qolganlari ham galereyaga qo'shiladi — ertasiga kamera
uni turli burchakdan taniydi.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import FaceGalleryEmbedding, StudentStaff, UnknownSighting
from app.services.face_matching import anchor_hash, load_candidate_matrix_cached
from app.services.unknown_sightings import ResolveError, _unit, assign_to_person, dismiss
from app.timezone import local_now
from app.timezone import business_today


@dataclass
class Cluster:
    rows: list[UnknownSighting] = field(default_factory=list)
    vectors: list[np.ndarray] = field(default_factory=list)
    centroid: np.ndarray | None = None

    def add(self, row: UnknownSighting, vector: np.ndarray) -> None:
        self.rows.append(row)
        self.vectors.append(vector)
        mean = np.mean(self.vectors, axis=0)
        norm = float(np.linalg.norm(mean))
        self.centroid = mean / norm if norm > 0 else mean

    @property
    def days(self) -> int:
        return len({row.day for row in self.rows})

    @property
    def hits(self) -> int:
        return sum(int(row.hits or 0) for row in self.rows)

    @property
    def best(self) -> UnknownSighting:
        return max(self.rows, key=lambda row: (row.face_px or 0, row.hits or 0))


def cluster_vectors(vectors: list[np.ndarray], threshold: float) -> list[list[int]]:
    """Toza funksiya (sinovlanadi): yirikdan kichikka tartibda kelgan
    vektorlarni ochko'z guruhlash — har vektor eng o'xshash guruh markaziga
    (>= threshold) qo'shiladi, aks holda yangi guruh."""
    groups: list[list[int]] = []
    centroids: list[np.ndarray] = []
    sums: list[np.ndarray] = []
    for index, vector in enumerate(vectors):
        if centroids:
            sims = np.stack(centroids) @ vector
            best = int(np.argmax(sims))
            if float(sims[best]) >= threshold:
                groups[best].append(index)
                sums[best] = sums[best] + vector
                norm = float(np.linalg.norm(sums[best]))
                centroids[best] = sums[best] / norm if norm > 0 else sums[best]
                continue
        groups.append([index])
        sums.append(vector.copy())
        centroids.append(vector.copy())
    return groups


#: Guruhlashga olinadigan eng ko'p kadr (eng katta yuzlar).
MAX_CLUSTER_ROWS = 2000


async def recurring_clusters(db: AsyncSession, *, days: int, min_days: int = 1, limit: int = 60) -> list[Cluster]:
    since = business_today() - timedelta(days=max(0, days - 1))
    rows = (
        await db.execute(
            select(UnknownSighting)
            .where(UnknownSighting.status == "kutilmoqda", UnknownSighting.day >= since)
            .where(UnknownSighting.face_px >= settings.unknown_cluster_min_px)
            .order_by(UnknownSighting.face_px.desc(), UnknownSighting.hits.desc())
            # Eng aniq (katta) yuzlar birinchi — guruhlash O(N·K) va API
            # jarayonida ishlaydi, shuning uchun hajm cheklangan.
            .limit(MAX_CLUSTER_ROWS)
        )
    ).scalars().all()

    def _vectors() -> tuple[list[UnknownSighting], list[np.ndarray], list[list[int]]]:
        kept: list[UnknownSighting] = []
        vectors: list[np.ndarray] = []
        for row in rows:
            try:
                vector = _unit(json.loads(row.embedding))
            except (ValueError, TypeError):
                continue
            if vector is None:
                continue
            kept.append(row)
            vectors.append(vector)
        return kept, vectors, cluster_vectors(vectors, settings.unknown_cluster_similarity)

    # JSON o'qish va guruhlash — alohida oqimda: API ning boshqa so'rovlari kutib qolmasin.
    kept, vectors, groups = await asyncio.to_thread(_vectors)
    clusters: list[Cluster] = []
    for group in groups:
        cluster = Cluster()
        for index in group:
            cluster.add(kept[index], vectors[index])
        if cluster.days >= min_days:
            clusters.append(cluster)
    clusters.sort(key=lambda c: (c.days, c.hits, len(c.rows)), reverse=True)
    return clusters[:limit]


async def lookalikes(db: AsyncSession, centroid: np.ndarray, *, limit: int = 3) -> list[tuple[StudentStaff, float]]:
    """Guruhga eng yaqin tasdiqlangan odamlar (o'xshashlik unknown_hint_similarity
    dan yuqori) — "bu X emasmi?" degan ishora. Qat'iy moslik emas: ular
    tanish chegarasidan past bo'lgani uchun notanish qolgan. Davomat
    ishlatadigan keshlangan matritsadan (asl rasm + galereya) — bitta
    matritsa ko'paytmasi."""
    candidates = await load_candidate_matrix_cached(db)
    if candidates.is_empty:
        return []
    sims = candidates.matrix @ centroid
    best: dict[str, float] = {}
    for index in np.argsort(-sims)[: limit * 8]:
        sim = float(sims[int(index)])
        if sim < settings.unknown_hint_similarity:
            break
        person_id = candidates.ids[int(index)]
        best[person_id] = max(best.get(person_id, -1.0), sim)
    top = sorted(best.items(), key=lambda item: item[1], reverse=True)[:limit]
    if not top:
        return []
    people = {
        str(person.id): person
        for person in (
            await db.execute(select(StudentStaff).where(StudentStaff.id.in_([uuid.UUID(pid) for pid, _ in top])))
        ).scalars()
    }
    return [(people[pid], sim) for pid, sim in top if pid in people]


async def _load_group(db: AsyncSession, sighting_ids: list[str]) -> list[UnknownSighting]:
    ids = []
    for raw in sighting_ids:
        try:
            ids.append(uuid.UUID(raw))
        except ValueError:
            raise ResolveError("Yozuv identifikatori noto'g'ri") from None
    rows = (await db.execute(select(UnknownSighting).where(UnknownSighting.id.in_(ids)))).scalars().all()
    if len(rows) != len(set(ids)):
        raise ResolveError("Ba'zi yozuvlar topilmadi")
    if any(row.status != "kutilmoqda" for row in rows):
        raise ResolveError("Ba'zi yozuvlar allaqachon ko'rib chiqilgan — ro'yxatni yangilang")
    return list(rows)


async def assign_group(
    db: AsyncSession,
    sighting_ids: list[str],
    person: StudentStaff,
    user_id: uuid.UUID | None,
    *,
    can_enroll: bool = False,
) -> tuple[str, int]:
    """Guruhni odamga biriktiradi. Qaytaradi: (asosiy|galereya, galereyaga
    qo'shilgan qo'shimcha namunalar soni). Commit — chaqiruvchida.

    Himoya: guruhdagi har yuz eng yirik yuzga settings.unknown_cluster_similarity
    dan kam o'xshamasligi kerak — so'rov qo'lda tuzilgan bo'lsa ham boshqa
    odamning yuzi birga qo'shilib ketmaydi."""
    rows = await _load_group(db, sighting_ids)
    if not rows:
        raise ResolveError("Guruh bo'sh")
    best = max(rows, key=lambda row: (row.face_px or 0, row.hits or 0))
    vectors = {}
    for row in rows:
        vector = _unit(json.loads(row.embedding))
        if vector is None:
            raise ResolveError("Yuz ma'lumoti buzilgan")
        vectors[row.id] = vector
    # Har yuz QOLGANLARI markaziga o'xshashi kerak (o'zi hisobga kirmaydi):
    # aks holda ikki xil odamning juftligi ham o'z o'rtachasiga "o'xshab" qolardi.
    total = np.sum(list(vectors.values()), axis=0)
    floor = settings.unknown_cluster_similarity - 0.08
    for vector in vectors.values():
        rest = total - vector
        norm = float(np.linalg.norm(rest))
        if len(vectors) > 1 and (norm <= 1e-9 or float(vector @ rest) / norm < floor):
            raise ResolveError("Guruhdagi yuzlar bir odamniki emasga o'xshaydi — ularni alohida ko'rib chiqing")
    others = [(row, vectors[row.id]) for row in rows if row is not best]

    kind = await assign_to_person(db, best, person, user_id, can_enroll=can_enroll)
    anchor_raw = person.biometric_embedding
    anchor = _unit(json.loads(anchor_raw)) if anchor_raw else None
    added = 0
    budget = settings.unknown_cluster_gallery_samples
    for row, vector in sorted(others, key=lambda item: item[0].face_px or 0, reverse=True):
        if added < budget and anchor is not None and float(anchor @ vector) >= settings.unknown_assign_min_similarity:
            db.add(
                FaceGalleryEmbedding(
                    student_staff_id=person.id,
                    embedding=row.embedding,
                    anchor_hash=anchor_hash(anchor_raw),
                    similarity=float(anchor @ vector),
                    face_px=row.face_px,
                    camera_id=row.camera_id,
                )
            )
            added += 1
        row.status = "talaba"
        row.person_id = person.id
        row.resolved_by = best.resolved_by
        row.resolved_at = best.resolved_at
    return kind, added


async def dismiss_group(db: AsyncSession, sighting_ids: list[str], user_id: uuid.UUID | None) -> int:
    rows = await _load_group(db, sighting_ids)
    for row in rows:
        dismiss(row, user_id)
    return len(rows)

