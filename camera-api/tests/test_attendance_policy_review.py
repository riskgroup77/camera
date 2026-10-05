"""Adversarial checks on the 2026-09-19/20 attendance-policy rewiring.

Question these answer: do the camera path and the turnstile path agree
about the same day for the same person, and does an out-of-order or
post-absence sighting land correctly?
"""

from datetime import date as date_type, datetime, time

import pytest
from sqlalchemy import select

from app.config import settings
from app.jobs.attendance_ai import upsert_attendance_from_recognition
from app.models import AttendanceRecord, Building, Camera, Faculty, StudentStaff
from app.services import attendance_policy as policy_mod
from app.services.attendance_policy import Policy, set_cached
from app.services.integrations.access_control import _attendance_changes
from app.timezone import INSTITUTE_TZ


def _local(hour: int, minute: int) -> datetime:
    """A moment today, institute-local. Forced onto a Monday-ish workday
    is not possible here, so tests that care about weekends set the day
    explicitly instead."""
    return datetime.now(INSTITUTE_TZ).replace(hour=hour, minute=minute, second=0, microsecond=0)


@pytest.fixture(autouse=True)
def _arrival_only(monkeypatch):
    monkeypatch.setattr(settings, "attendance_arrival_only", True)
    set_cached(Policy())
    yield
    # set_cached also stamps _loaded_at, which makes load_policy() skip the
    # DB for the next 30 s — that would leak this module's default policy
    # into any later test that writes its own attendance_policy row.
    set_cached(Policy())
    policy_mod._loaded_at = 0.0


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Koridor", ip="10.0.9.77", building_id=building.id, zone="Koridor",
        resolution="1080p", status="faol",
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera, attribute_names=["building"])
    return camera


@pytest.fixture
async def a_person(db_session, seeded):
    faculty = (await db_session.execute(select(Faculty))).scalars().first()
    person = StudentStaff(
        full_name="Tekshiruv Odami", type="xodim", faculty_id=faculty.id,
        group_or_position="Dotsent", biometrics_status="tasdiqlangan",
    )
    db_session.add(person)
    await db_session.commit()
    return person


async def _row(db_session, person) -> AttendanceRecord:
    return (
        await db_session.execute(
            select(AttendanceRecord).where(AttendanceRecord.student_staff_id == person.id)
        )
    ).scalar_one()


class TestCameraVsTurnstileAgree:
    async def test_camera_rescues_a_kelmadi_row(self, db_session, a_person, a_camera):
        """Absence marker (or an operator) wrote 'kelmadi'; the person is
        then actually seen by a camera. The turnstile path rewrites the
        row to an arrival — the camera path must not leave them absent."""
        db_session.add(
            AttendanceRecord(
                student_staff_id=a_person.id, date=_local(9, 0).date(),
                status="kelmadi", source="tizim",
            )
        )
        await db_session.commit()

        await upsert_attendance_from_recognition(
            db_session, str(a_person.id), _local(9, 30), camera=a_camera,
            off_hours_module_active=False,
        )
        record = await _row(db_session, a_person)
        assert record.status in ("keldi", "kech_keldi"), (
            "camera sighting left the person marked absent; the turnstile "
            "path (_attendance_changes) would have fixed the same row"
        )
        assert record.check_in == time(9, 30)

    def test_turnstile_does_rescue_a_kelmadi_row(self):
        """Control for the test above: the turnstile branch really does."""
        existing = AttendanceRecord(status="kelmadi", check_in=None, check_out=None)
        changes = _attendance_changes(existing, time(9, 30), "kirish", True)
        assert changes["status"] == "kech_keldi"
        assert changes["check_in"] == time(9, 30)

    async def test_camera_accepts_an_earlier_sighting(self, db_session, a_person, a_camera):
        """A turnstile event polled late creates the row at 09:00; a
        camera frame from 07:55 is processed afterwards. The true arrival
        is 07:55 and the person is not late."""
        db_session.add(
            AttendanceRecord(
                student_staff_id=a_person.id, date=_local(9, 0).date(),
                status="kech_keldi", check_in=time(9, 0), source="turniket",
            )
        )
        await db_session.commit()

        await upsert_attendance_from_recognition(
            db_session, str(a_person.id), _local(7, 55), camera=a_camera,
            off_hours_module_active=False,
        )
        record = await _row(db_session, a_person)
        assert record.check_in == time(7, 55), "earlier camera sighting was dropped"
        assert record.status == "keldi"

    async def test_camera_does_not_overwrite_a_manual_correction(self, db_session, a_person, a_camera):
        """Operator tuzatgan yozuv (source='qolda') kamera ko'rinishidan
        ustun — aks holda tuzatish keyingi kadrda yo'qolardi."""
        db_session.add(
            AttendanceRecord(
                student_staff_id=a_person.id, date=_local(9, 0).date(),
                status="kelmadi", check_in=None, source="qolda",
            )
        )
        await db_session.commit()

        await upsert_attendance_from_recognition(
            db_session, str(a_person.id), _local(9, 30), camera=a_camera,
            off_hours_module_active=False,
        )
        record = await _row(db_session, a_person)
        assert record.status == "kelmadi"
        assert record.source == "qolda"

    def test_turnstile_accepts_an_earlier_sighting(self):
        """Control: the turnstile branch handles moment < check_in."""
        existing = AttendanceRecord(status="kech_keldi", check_in=time(9, 0), check_out=None)
        changes = _attendance_changes(existing, time(7, 55), "kirish", True)
        assert changes["check_in"] == time(7, 55)
        assert changes["status"] == "keldi"


class TestManualSource:
    async def test_manual_record_is_marked_qolda(self, client, db_session, seeded):
        from tests.conftest import auth_headers

        headers = await auth_headers(client, "admin", "admin123")
        person = (await client.post(
            "/api/students-staff", headers=headers,
            json={"fullName": "Qolda Yozilgan", "type": "talaba", "faculty": "Davolash ishi",
                  "groupOrPosition": "1"},
        )).json()
        resp = await client.post(
            "/api/attendance", headers=headers,
            json={"studentStaffId": person["id"], "date": "2026-08-03", "status": "keldi", "checkIn": "08:55"},
        )
        assert resp.status_code == 201
        source = (await db_session.execute(
            select(AttendanceRecord.source).where(AttendanceRecord.date == date_type(2026, 8, 3))
        )).scalar_one()
        assert source == "qolda", (
            "manual edits used to leave source NULL, so a policy change "
            "recomputed them and a camera sighting overwrote them"
        )


class TestLastSeen:
    async def test_last_seen_advances_on_any_camera(self, db_session, a_person, a_camera):
        await upsert_attendance_from_recognition(
            db_session, str(a_person.id), _local(8, 5), camera=a_camera,
            off_hours_module_active=False,
        )
        await upsert_attendance_from_recognition(
            db_session, str(a_person.id), _local(16, 40), camera=a_camera,
            off_hours_module_active=False,
        )
        record = await _row(db_session, a_person)
        assert record.check_in == time(8, 5)
        assert record.check_out == time(16, 40)

    async def test_last_seen_does_not_move_backwards(self, db_session, a_person, a_camera):
        await upsert_attendance_from_recognition(
            db_session, str(a_person.id), _local(8, 5), camera=a_camera,
            off_hours_module_active=False,
        )
        await upsert_attendance_from_recognition(
            db_session, str(a_person.id), _local(16, 40), camera=a_camera,
            off_hours_module_active=False,
        )
        await upsert_attendance_from_recognition(
            db_session, str(a_person.id), _local(12, 0), camera=a_camera,
            off_hours_module_active=False,
        )
        record = await _row(db_session, a_person)
        assert record.check_out == time(16, 40), "a later frame from earlier in the day rewound check_out"


class TestPolicyArithmetic:
    def test_late_minutes_counted_from_start_not_from_grace(self):
        p = Policy()
        assert p.late_minutes(time(8, 10), "xodim") == 0
        assert p.late_minutes(time(8, 11), "xodim") == 11

    def test_arrival_before_start_is_not_late(self):
        assert Policy().late_minutes(time(6, 30), "xodim") == 0

    def test_weekend_is_never_late(self):
        from datetime import date

        # 2026-09-20 is a Sunday; default work_days is 1..6.
        assert Policy().late_minutes(time(11, 0), "xodim", date(2026, 9, 20)) == 0

    def test_seconds_are_ignored_but_do_not_flip_the_boundary(self):
        p = Policy()
        assert p.late_minutes(time(8, 10, 59), "xodim") == 0
