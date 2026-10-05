"""Takroriy notanishlar (app/services/unknown_clusters.py, /api/notanishlar/takroriy)."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Camera, FaceGalleryEmbedding, StudentStaff, UnknownSighting
from app.services.unknown_clusters import cluster_vectors
from app.timezone import local_now
from tests.conftest import auth_headers

pytestmark = pytest.mark.anyio


def _vec(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=512)
    return v / np.linalg.norm(v)


def _near(base: np.ndarray, seed: int, noise: float = 0.03) -> np.ndarray:
    v = base + np.random.default_rng(seed).normal(scale=noise, size=512)
    return v / np.linalg.norm(v)


def test_near_faces_group_and_strangers_stay_apart():
    a, b = _vec(1), _vec(2)
    groups = cluster_vectors([a, _near(a, 3), b, _near(a, 4), _near(b, 5)], 0.48)
    assert sorted(map(sorted, groups)) == [[0, 1, 3], [2, 4]]


async def _sightings(db_session) -> tuple[list[str], str]:
    camera = Camera(name="Koridor", ip="10.9.0.7", zone="Z", resolution="1080p", status="faol")
    db_session.add(camera)
    await db_session.commit()
    today = local_now().date()
    base, other = _vec(10), _vec(20)
    now = datetime.now(timezone.utc)

    def row(vector, day, px):
        return UnknownSighting(
            id=uuid.uuid4(), day=day, camera_id=camera.id, first_seen_at=now, last_seen_at=now, hits=3,
            embedding=json.dumps([float(x) for x in vector]), crop_key=None, face_px=px, status="kutilmoqda",
        )

    regular = [
        row(_near(base, 11), today, 90),
        row(_near(base, 12), today - timedelta(days=1), 70),
        row(_near(base, 13), today - timedelta(days=2), 60),
    ]
    once = row(other, today, 80)
    ids = [str(r.id) for r in regular], str(once.id)
    db_session.add_all([*regular, once])
    await db_session.commit()
    return ids


async def test_recurring_person_comes_first_and_is_assigned_in_one_click(client: AsyncClient, db_session, seeded):
    regular, once = await _sightings(db_session)
    person_id = uuid.uuid4()
    db_session.add(StudentStaff(id=person_id, full_name="Rasmsiz Talaba", type="talaba", group_or_position="101"))
    await db_session.commit()
    headers = await auth_headers(client, "admin", "admin123")

    listing = (await client.get("/api/notanishlar/takroriy", headers=headers)).json()
    first = listing["items"][0]
    assert first["days"] == 3
    assert sorted(first["sightingIds"]) == sorted(regular)

    res = await client.post(
        "/api/notanishlar/takroriy/biriktirish",
        headers=headers,
        json={"sightingIds": first["sightingIds"], "personId": str(person_id)},
    )
    # Yuzi yo'q odamga kadrlardan yuz kiritilmaydi (3 tomon shart) — 409, hech narsa o'zgarmaydi.
    assert res.status_code == 409, res.text
    db_session.expire_all()
    stored = await db_session.get(StudentStaff, person_id)
    assert stored.biometrics_status == "yoq" and not stored.biometric_embedding


async def test_a_group_of_different_people_is_refused(client: AsyncClient, db_session, seeded):
    regular, once = await _sightings(db_session)
    person_id = uuid.uuid4()
    db_session.add(StudentStaff(id=person_id, full_name="Boshqa Odam", type="talaba", group_or_position="102"))
    await db_session.commit()
    headers = await auth_headers(client, "admin", "admin123")
    res = await client.post(
        "/api/notanishlar/takroriy/biriktirish",
        headers=headers,
        json={"sightingIds": [regular[0], once], "personId": str(person_id)},
    )
    assert res.status_code == 409


async def test_group_can_be_dismissed(client: AsyncClient, db_session, seeded):
    regular, _once = await _sightings(db_session)
    headers = await auth_headers(client, "admin", "admin123")
    res = await client.post(
        "/api/notanishlar/takroriy/otkazish", headers=headers, json={"sightingIds": regular}
    )
    assert res.status_code == 200 and res.json()["count"] == 3


async def test_requires_review_permission(client: AsyncClient):
    assert (await client.get("/api/notanishlar/takroriy")).status_code in (401, 403)
