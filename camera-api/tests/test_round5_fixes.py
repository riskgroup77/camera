"""Beshinchi audit tuzatishlari: yarim tundan keyingi vaqtlar, tuzilma
daraxtidagi "kutilmoqda", faqat davomat oladigan WebSocket ulanishi."""

from datetime import date, datetime, time

import pytest

from app.routers.situation import _bucket
from app.services.attendance_policy import EARLY_NO, Policy, early_leave_verdict
from app.timezone import INSTITUTE_TZ
from app.ws import ConnectionManager

MONDAY = date(2026, 9, 21)


pytestmark = pytest.mark.six_am_day


class TestAfterMidnight:
    def test_arrival_after_midnight_is_late_not_on_time(self):
        policy = Policy()
        # 01:00 — ish kunining oxiri (06:00 dan boshlanadi), "erta tong" emas.
        assert policy.late_minutes(time(1, 0), "xodim", MONDAY) > 0
        assert policy.late_minutes(time(7, 50), "xodim", MONDAY) == 0

    def test_checkout_after_midnight_is_not_early_leave(self):
        verdict = early_leave_verdict(
            status="keldi",
            day=MONDAY,
            check_in=time(8, 0),
            check_out=time(1, 30),
            sightings=10,
            last_seen=time(1, 30),
            policy=Policy(),
            now=datetime.combine(date(2026, 9, 23), time(12, 0), tzinfo=INSTITUTE_TZ),
        )
        assert verdict == EARLY_NO


class TestOrgTreeBucket:
    def test_not_yet_is_not_absent(self):
        assert _bucket(None, True, True) == "not_yet"
        assert _bucket("kelmadi", True, True) == "absent"
        assert _bucket(None, True, False) == "no_data"
        assert _bucket("keldi", True, True) == "present"


class _Socket:
    pass


class TestAttendanceOnlySocket:
    def test_attendance_only_socket_gets_no_events(self):
        manager = ConnectionManager()
        ws = _Socket()
        manager._attendance_only.add(ws)
        assert manager._allowed(ws, {"kind": "attendance_recorded", "fullName": "A"}) is True
        assert manager._allowed(ws, {"kind": "event_created", "cameraId": "x"}) is False
        assert manager._allowed(ws, {"kind": "events_reviewed"}) is False

    def test_reviewer_socket_gets_everything(self):
        manager = ConnectionManager()
        ws = _Socket()
        assert manager._allowed(ws, {"kind": "event_created", "cameraId": "x"}) is True
        assert manager._allowed(ws, {"kind": "attendance_recorded"}) is True


@pytest.mark.anyio
async def test_attendance_viewer_may_open_the_socket(client, seeded):
    """manageAttendance/viewReports egasi ham ulanadi (jonli davomat);
    kamera mas'uli — yo'q (test_operator_permissions)."""
    from app.routers.events import authorize_events_socket
    from tests.conftest import TestSessionLocal, login

    token = await login(client, "operator", "operator123")
    assert await authorize_events_socket(token, TestSessionLocal) is None


class TestRound6Rules:
    def test_night_sighting_does_not_overturn_yesterdays_absence(self):
        from types import SimpleNamespace

        from app.jobs.attendance_ai import _is_earlier_arrival

        absent = SimpleNamespace(status="kelmadi", source=None, check_in=None)
        assert _is_earlier_arrival(absent, time(21, 0)) is True  # kechki dars — tuzatiladi
        assert _is_earlier_arrival(absent, time(5, 45)) is False  # ertangi kunga erta kelgan

    def test_off_hours_cooldown_per_person(self):
        from app.jobs import attendance_ai

        attendance_ai._off_hours_raised.clear()
        assert attendance_ai._off_hours_cooldown_ok("p1") is True
        assert attendance_ai._off_hours_cooldown_ok("p1") is False
        assert attendance_ai._off_hours_cooldown_ok("p2") is True
        attendance_ai._off_hours_raised.clear()

    def test_stalled_reader_is_detected(self):
        import time as _time

        from app.services.stream_cache import STREAM_STALL_SECONDS, _StreamReader

        reader = _StreamReader("rtsp://example/1")
        assert reader._is_stalled() is False  # hali kadr bermagan — "buzilgan" yo'li alohida
        reader._frames_decoded = 5
        reader._latest_frame_at = _time.monotonic() - STREAM_STALL_SECONDS - 1
        assert reader._is_stalled() is True
        reader._latest_frame_at = _time.monotonic()
        assert reader._is_stalled() is False

    def test_capture_moment_ignores_bogus_clock(self):
        import time as _time

        from app.jobs.attendance_ai import _capture_moment

        assert _capture_moment(None) is None
        assert _capture_moment(_time.time() + 60) is None
        assert _capture_moment(_time.time() - 3600) is None
        assert _capture_moment(_time.time() - 5) is not None

    def test_hemis_completeness_guard(self):
        from app.services.integrations.hemis import _looks_complete

        assert _looks_complete(10, 5) is True  # kichik baza — tekshirilmaydi
        assert _looks_complete(900, 1000) is True
        assert _looks_complete(200, 1000) is False  # birinchi sahifagina keldi


@pytest.mark.anyio
async def test_excluded_camera_records_no_arrival(db_session, seeded):
    """Admin 6 va 7-modulni o'chirgan kamera yagona tekshiruvda ham kelish yozmaydi."""
    from app.jobs.unified_face_sweep import record_arrivals
    from app.models import Camera
    from app.services.face_matching import CandidateMatrix

    import numpy as np

    camera = Camera(name="Yo'lak", ip="10.8.0.1", zone="Z", resolution="1080p", status="faol",
                    excluded_module_codes=[6, 7])
    db_session.add(camera)
    await db_session.commit()
    candidates = CandidateMatrix(ids=["x"], matrix=np.array([[1.0, 0.0]]))
    assert await record_arrivals(db_session, camera, [object()], candidates, {}) == 0
