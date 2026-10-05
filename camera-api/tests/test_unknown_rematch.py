"""Noma'lum yuzlarni yangi baza bilan qayta solishtirish (app/jobs/unknown_rematch.py)."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy import select

from app.jobs import unknown_rematch
from app.models import AttendanceRecord, Camera, PresenceVisit, StudentStaff, UnknownSighting
from app.services.face_matching import invalidate_candidate_matrix_cache
from app.timezone import local_now
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.anyio


def _vec(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=512)
    return v / np.linalg.norm(v)


def _near(base: np.ndarray, seed: int, noise: float) -> np.ndarray:
    v = base + np.random.default_rng(seed).normal(scale=noise, size=512)
    return v / np.linalg.norm(v)


def _json(v: np.ndarray) -> str:
    return json.dumps([float(x) for x in v])


async def test_sightings_of_newly_enrolled_people_are_resolved(db_session, monkeypatch):
    monkeypatch.setattr(unknown_rematch, "SessionLocal", TestSessionLocal)
    door = Camera(name="Asosiy kirish", ip="10.1.0.1", zone="Z", resolution="1080p", status="faol")
    hall = Camera(name="Koridor", ip="10.1.0.2", zone="Z", resolution="1080p", status="faol")
    known, other, stranger = _vec(1), _vec(2), _vec(3)
    enrolled = StudentStaff(id=uuid.uuid4(), full_name="Yangi Talaba", type="talaba", group_or_position="101",
                            biometrics_status="tasdiqlangan", biometric_embedding=_json(known))
    second = StudentStaff(id=uuid.uuid4(), full_name="Boshqa Talaba", type="talaba", group_or_position="101",
                          biometrics_status="tasdiqlangan", biometric_embedding=_json(other))
    db_session.add_all([door, hall, enrolled, second])
    await db_session.commit()
    ids = {"door": door.id, "hall": hall.id, "person": enrolled.id}
    today = local_now().date()
    seen = datetime.now(timezone.utc) - timedelta(hours=1)

    def row(vector, camera_id, px, day=today):
        return UnknownSighting(id=uuid.uuid4(), day=day, camera_id=camera_id, first_seen_at=seen, last_seen_at=seen,
                               hits=2, embedding=_json(vector), face_px=px, status="kutilmoqda")

    at_door = row(_near(known, 10, 0.02), ids["door"], 80)
    in_hall = row(_near(known, 11, 0.02), ids["hall"], 60)
    tiny = row(_near(known, 12, 0.02), ids["door"], 20)
    unknown = row(stranger, ids["door"], 90)
    old = row(_near(known, 13, 0.02), ids["door"], 80, day=today - timedelta(days=5))
    rows = [at_door, in_hall, tiny, unknown, old]
    row_ids = [r.id for r in rows]
    db_session.add_all(rows)
    await db_session.commit()
    invalidate_candidate_matrix_cache()

    stats = await unknown_rematch.run_unknown_rematch_once()
    assert stats == {"tekshirildi": 3, "tanildi": 2, "davomat": 1}

    db_session.expire_all()
    status = {r.id: (r.status, r.person_id) for r in (await db_session.execute(select(UnknownSighting))).scalars()}
    assert status[row_ids[0]] == ("talaba", ids["person"]) and status[row_ids[1]] == ("talaba", ids["person"])
    assert [status[i][0] for i in row_ids[2:]] == ["kutilmoqda"] * 3
    attendance = (await db_session.execute(select(AttendanceRecord).where(AttendanceRecord.student_staff_id == ids["person"]))).scalars().all()
    assert len(attendance) == 1
    visits = (await db_session.execute(select(PresenceVisit).where(PresenceVisit.student_staff_id == ids["person"]))).scalars().all()
    assert {v.camera_id for v in visits} == {ids["door"], ids["hall"]}

    # Ikkinchi marta — hech narsa o'zgarmaydi.
    assert (await unknown_rematch.run_unknown_rematch_once())["tanildi"] == 0


async def test_ambiguous_match_is_left_for_the_operator(db_session, monkeypatch):
    monkeypatch.setattr(unknown_rematch, "SessionLocal", TestSessionLocal)
    base = _vec(5)
    twin_a, twin_b = _near(base, 6, 0.01), _near(base, 7, 0.01)
    db_session.add_all([
        StudentStaff(id=uuid.uuid4(), full_name="Egizak A", type="talaba", group_or_position="1",
                     biometrics_status="tasdiqlangan", biometric_embedding=_json(twin_a)),
        StudentStaff(id=uuid.uuid4(), full_name="Egizak B", type="talaba", group_or_position="1",
                     biometrics_status="tasdiqlangan", biometric_embedding=_json(twin_b)),
    ])
    seen = datetime.now(timezone.utc)
    db_session.add(UnknownSighting(id=uuid.uuid4(), day=local_now().date(), camera_id=None, first_seen_at=seen,
                                   last_seen_at=seen, hits=1, embedding=_json(base), face_px=80, status="kutilmoqda"))
    await db_session.commit()
    invalidate_candidate_matrix_cache()
    assert (await unknown_rematch.run_unknown_rematch_once())["tanildi"] == 0
