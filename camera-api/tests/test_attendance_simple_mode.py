"""Faqat davomat rejimi (2026-09-19): hamma kamera, faqat "keldi + soat"."""

import importlib.util
from datetime import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import settings
from app.jobs.attendance_ai import first_sighting_status
from app.services.camera_roles import role_allows, role_allows_clause
from app.services.frame_grabber import ai_prefers_substream


def _camera(**flags):
    base = dict(
        id="c1", is_entrance=False, is_exit=False, is_perimeter=False, room_type=None, face_direction=None
    )
    base.update(flags)
    return SimpleNamespace(**base)


class TestArrivalOnly:
    def test_first_sighting_on_any_camera_uses_work_hours(self, monkeypatch):
        """08:00 + 10 daqiqa: 08:10 gacha keldi, keyin kech keldi — kamera turi ahamiyatsiz."""
        monkeypatch.setattr(settings, "attendance_arrival_only", True)
        room = _camera(room_type="auditoriya")
        assert first_sighting_status(time(8, 10), room) == ("keldi", time(8, 10))
        assert first_sighting_status(time(8, 11), room) == ("kech_keldi", time(8, 11))
        assert first_sighting_status(time(17, 55), _camera(is_entrance=True)) == ("kech_keldi", time(17, 55))

    @pytest.mark.default_policy
    def test_weekend_is_never_late(self, monkeypatch):
        from datetime import date

        monkeypatch.setattr(settings, "attendance_arrival_only", True)
        assert first_sighting_status(time(11, 0), _camera(), "xodim", date(2026, 9, 20))[0] == "keldi"

    def test_off_keeps_the_late_rule(self, monkeypatch):
        monkeypatch.setattr(settings, "attendance_arrival_only", False)
        assert first_sighting_status(time(10, 0), _camera(is_entrance=True))[0] == "kech_keldi"


class TestAllCameras:
    @pytest.mark.parametrize("room_type", [None, "auditoriya", "koridor", "laboratoriya"])
    def test_every_camera_allows_daily_attendance(self, monkeypatch, room_type):
        monkeypatch.setattr(settings, "attendance_all_cameras", True)
        assert role_allows(_camera(room_type=room_type), 6)
        assert role_allows(_camera(room_type=room_type), 7)

    def test_other_modules_keep_their_rooms(self, monkeypatch):
        monkeypatch.setattr(settings, "attendance_all_cameras", True)
        assert not role_allows(_camera(room_type="koridor"), 20)

    def test_sql_clause_matches(self, monkeypatch):
        monkeypatch.setattr(settings, "attendance_all_cameras", True)
        assert str(role_allows_clause(6)) == "true"

    def test_room_cameras_stay_on_the_substream_by_default(self, monkeypatch):
        """Tarmoq 107 ta 4K oqimni ko'tarmaydi — asosiy oqim kirish eshigiga."""
        monkeypatch.setattr(settings, "attendance_all_cameras", True)
        monkeypatch.setattr(settings, "ai_entrance_use_main_stream", True)
        monkeypatch.setattr(settings, "ai_room_cameras_main_stream", False)
        assert ai_prefers_substream(_camera(room_type="auditoriya")) is True
        assert ai_prefers_substream(_camera(id="door", is_entrance=True)) is False

    def test_room_cameras_can_be_given_the_main_stream(self, monkeypatch):
        monkeypatch.setattr(settings, "attendance_all_cameras", True)
        monkeypatch.setattr(settings, "ai_entrance_use_main_stream", True)
        monkeypatch.setattr(settings, "ai_room_cameras_main_stream", True)
        assert ai_prefers_substream(_camera(room_type="auditoriya")) is False

    def test_off_restores_entrance_only(self, monkeypatch):
        monkeypatch.setattr(settings, "attendance_all_cameras", False)
        assert not role_allows(_camera(room_type="auditoriya"), 6)


@pytest.fixture
def script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "davomat_rejimi.py"
    spec = importlib.util.spec_from_file_location("davomat_rejimi", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestModeScript:
    def test_everything_but_staff_attendance_goes_inactive(self, script):
        active = {1: True, 3: True, 6: False, 7: False, 20: True, 23: False}
        assert script.plan_attendance_only(active, students=False) == {1: False, 3: False, 6: True, 20: False}

    def test_students_only_on_request(self, script):
        assert script.plan_attendance_only({6: True, 7: False}, students=True) == {7: True}

    def test_camera_exclusions_drop_only_attendance(self, script):
        assert script.without_attendance([6, 20, 7]) == [20]
        assert script.without_attendance([6]) is None
        assert script.without_attendance(None) is None

    def test_codes_parse(self, script):
        assert script.parse_codes("1, 3,20") == {1, 3, 20}


@pytest.mark.usefixtures("seeded")
class TestArrivalOnlyRecords:
    async def test_first_sighting_on_room_camera_is_arrival_and_last_sighting_is_departure(self, db_session, monkeypatch):
        from datetime import datetime, timedelta

        from sqlalchemy import select

        from app.jobs.attendance_ai import _entrance_cameras, upsert_attendance_from_recognition
        from app.models import Building, Camera, Faculty, StudentStaff
        from app.timezone import INSTITUTE_TZ

        monkeypatch.setattr(settings, "attendance_arrival_only", True)
        monkeypatch.setattr(settings, "attendance_all_cameras", True)
        building = (await db_session.execute(select(Building))).scalars().first()
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        door = Camera(name="Eshik", ip="10.7.0.1", building_id=building.id, zone="Z", resolution="1080p",
                      status="faol", is_entrance=True, is_exit=True, stream_url="rtsp://x/1",
                      last_seen_at=datetime.now(INSTITUTE_TZ))
        room = Camera(name="211-xona", ip="10.7.0.2", building_id=building.id, zone="Z", resolution="1080p",
                      status="faol", room_type="auditoriya", stream_url="rtsp://x/2",
                      last_seen_at=datetime.now(INSTITUTE_TZ))
        person = StudentStaff(full_name="Aziz Xodim", type="xodim", faculty_id=faculty.id, group_or_position="O'qituvchi")
        db_session.add_all([door, room, person])
        await db_session.commit()

        names = {c.name for c in await _entrance_cameras(db_session)}
        assert {"Eshik", "211-xona"} <= names  # xona kamerasi ham davomat qiladi

        # Dushanba, 10:37 — 08:10 dan keyin, birinchi ko'rinish xona kamerasida.
        late = datetime(2026, 9, 21, 10, 37, tzinfo=INSTITUTE_TZ)
        first = await upsert_attendance_from_recognition(db_session, str(person.id), late, room)
        assert first.status == "kech_keldi"
        assert first.check_in.strftime("%H:%M") == "10:37"

        evening = await upsert_attendance_from_recognition(db_session, str(person.id), late + timedelta(hours=7), door)
        assert evening.check_out.strftime("%H:%M") == "17:37"  # oxirgi ko'rinish — ketdi
        assert evening.check_in.strftime("%H:%M") == "10:37"
        assert evening.status == "kech_keldi"


class TestBandwidthPriority:
    """107 ta 4K oqim tarmoqqa sig'maydi: kirish eshigi birinchi va tez qayta urinadi."""

    def test_room_camera_waits_longer_before_retrying_the_main_stream(self, monkeypatch):
        import time as time_module

        from app.services import frame_grabber

        frame_grabber.reset_main_stream_fallbacks_for_tests()
        monkeypatch.setattr(settings, "ai_entrance_main_stream_retry_seconds", 100.0)
        monkeypatch.setattr(settings, "ai_room_main_stream_retry_seconds", 10_000.0)
        door = _camera(id="door", is_entrance=True)
        room = _camera(id="room", room_type="auditoriya")
        frame_grabber._note_main_stream_result(door, ok=False)
        frame_grabber._note_main_stream_result(room, ok=False)
        now = time_module.monotonic()
        assert frame_grabber._main_stream_failed_until["door"] - now <= 121
        assert frame_grabber._main_stream_failed_until["room"] - now >= 7_900
        frame_grabber.reset_main_stream_fallbacks_for_tests()

    async def test_room_watcher_starts_after_the_doors(self, monkeypatch):
        import asyncio

        from app.jobs import attendance_ai

        monkeypatch.setattr(settings, "room_watcher_start_delay_seconds", 0.3)
        monkeypatch.setattr(settings, "room_watcher_start_spread_seconds", 0.0)
        monkeypatch.setattr(attendance_ai, "_entrance_context", None)
        started = asyncio.get_running_loop().time()
        grabbed: list[float] = []

        async def fake_grab(camera, **_):
            grabbed.append(asyncio.get_running_loop().time() - started)
            raise asyncio.CancelledError

        monkeypatch.setattr(attendance_ai, "_entrance_context", object())
        monkeypatch.setattr(attendance_ai, "grab_newer_frame", fake_grab)
        watcher = attendance_ai._EntranceWatcher(signature=())
        room = _camera(room_type="auditoriya")
        with pytest.raises(asyncio.CancelledError):
            await attendance_ai._watch_entrance_camera(room, watcher)
        assert grabbed and grabbed[0] >= 0.29
