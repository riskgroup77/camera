"""Ish vaqti qoidasi saqlanganda qaysi yozuvlar qayta hisoblanadi.

Productionda topilgan (2026-09-20): so'rovda `source IN ('kamera',
'turniket')` sharti bor edi, bazada esa 1005 ta yozuvning manbasi NULL
(eski yozuvlar) va atigi 5 tasiniki 'kamera'. Ya'ni "Ish vaqti" sahifasi
saqlanganda "qayta hisoblandi" deb javob berardi-yu, amalda deyarli hech
nimani o'zgartirmasdi. Qo'lda tuzatilgan yozuv (source='qolda') esa
aksincha — hech qachon qayta hisoblanmasligi kerak.
"""

from datetime import date as date_type, time, timedelta

import pytest
from sqlalchemy import select

from app.models import AttendanceRecord, Faculty, StudentStaff
from app.services import attendance_policy as policy_mod
from app.services.attendance_policy import Policy, set_cached
from app.timezone import local_now
from tests.conftest import auth_headers

PAYLOAD = {
    "staffStart": "08:00",
    "studentStart": "08:00",
    "graceMinutes": 10,
    "workEnd": "17:00",
    "workDays": [1, 2, 3, 4, 5, 6],
    "trackLastSeen": True,
}


@pytest.fixture(autouse=True)
def _clean_policy_cache():
    yield
    set_cached(Policy())
    policy_mod._loaded_at = 0.0


def _recent_monday() -> date_type:
    """RECOMPUTE_DAYS ichidagi ish kuni (yakshanba kechikish hisoblanmaydi)."""
    today = local_now().date()
    return today - timedelta(days=today.isoweekday() - 1 + 7)


async def _person(db_session, name: str) -> StudentStaff:
    faculty = (await db_session.execute(select(Faculty))).scalars().first()
    person = StudentStaff(full_name=name, type="xodim", faculty_id=faculty.id, group_or_position="Dotsent")
    db_session.add(person)
    await db_session.commit()
    return person


class TestPolicyRecomputeCoversLegacyRows:
    async def test_null_source_rows_are_recomputed_and_manual_rows_are_not(
        self, client, db_session, seeded
    ):
        day = _recent_monday()
        legacy = await _person(db_session, "Eski Yozuv")      # source NULL
        camera = await _person(db_session, "Kamera Yozuvi")   # source 'kamera'
        manual = await _person(db_session, "Qolda Yozuv")     # source 'qolda'
        for person, source in ((legacy, None), (camera, "kamera"), (manual, "qolda")):
            db_session.add(
                AttendanceRecord(
                    student_staff_id=person.id, date=day, status="keldi",
                    check_in=time(9, 30), source=source,
                )
            )
        await db_session.commit()

        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.put("/api/attendance-policy", headers=headers, json=PAYLOAD)
        assert resp.status_code == 200

        rows = {
            pid: status
            for pid, status in (
                await db_session.execute(
                    select(AttendanceRecord.student_staff_id, AttendanceRecord.status)
                    .where(AttendanceRecord.date == day)
                )
            ).all()
        }
        assert rows[legacy.id] == "kech_keldi", (
            "manbasi yozilmagan eski yozuv ham qayta hisoblanishi kerak — "
            "productionda yozuvlarning deyarli hammasi shunday"
        )
        assert rows[camera.id] == "kech_keldi"
        assert rows[manual.id] == "keldi", "qo'lda kiritilgan yozuvga tegilmaydi"
        assert resp.json()["recomputed"] == 2
