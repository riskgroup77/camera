from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.jobs import dress_code_ai
from app.jobs.dress_code_ai import (
    COAT_MODULE_CODE,
    HEAD_COVERING_MODULE_CODE,
    _load_staff_ids,
    _recently_flagged,
    process_camera_frame_pair_for_dress_code,
    run_dress_code_ai_sweep_once,
)
from app.models import AIModuleConfig, Building, Camera, Event, StudentStaff
from tests.conftest import TestSessionLocal


async def _set_module_active(db_session, code: int, active: bool) -> None:
    module = (
        await db_session.execute(select(AIModuleConfig).where(AIModuleConfig.code == code))
    ).scalar_one()
    module.active = active
    await db_session.commit()


def _blank_frame() -> bytes:
    import io

    from PIL import Image

    blank = Image.frombytes("RGB", (100, 100), bytes([255] * 100 * 100 * 3))
    buf = io.BytesIO()
    blank.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Laboratoriya kamerasi", ip="10.0.9.40", building_id=building.id,
        zone="Laboratoriya", resolution="1080p", status="faol",
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera, attribute_names=["building"])
    return camera


@pytest.fixture
async def a_staff_member(db_session, seeded) -> StudentStaff:
    staff = StudentStaff(
        full_name="Dilnoza Rasulova", type="xodim", group_or_position="Hamshira", biometrics_status="yoq"
    )
    student = StudentStaff(
        full_name="Sardor Yusupov", type="talaba", group_or_position="IT-21", biometrics_status="yoq"
    )
    db_session.add_all([staff, student])
    await db_session.commit()
    return staff


@pytest.mark.usefixtures("seeded")
class TestLoadStaffIds:
    async def test_only_staff_type_is_returned(self, db_session, a_staff_member):
        staff_ids = await _load_staff_ids(db_session)
        assert str(a_staff_member.id) in staff_ids
        assert len(staff_ids) == 1  # the 'talaba' fixture row is excluded


@pytest.mark.usefixtures("seeded")
class TestRecentlyFlagged:
    async def test_no_prior_events_is_not_flagged(self, db_session, a_camera):
        assert await _recently_flagged(db_session, a_camera.id, COAT_MODULE_CODE) is False

    async def test_recent_event_at_same_camera_and_module_is_flagged(self, db_session, a_camera):
        db_session.add(Event(
            camera_id=a_camera.id, camera_name=a_camera.name, building="Bino",
            module_code=COAT_MODULE_CODE, module_name="Oq xalat", group="C",
            confidence=40, severity="past", status="yangi",
        ))
        await db_session.commit()
        assert await _recently_flagged(db_session, a_camera.id, COAT_MODULE_CODE) is True
        # A different module code (head covering) at the same camera is unaffected.
        assert await _recently_flagged(db_session, a_camera.id, HEAD_COVERING_MODULE_CODE) is False


@pytest.mark.usefixtures("seeded")
class TestProcessCameraFramePairForDressCode:
    async def test_no_staff_missing_anything_raises_nothing(self, db_session, a_camera, monkeypatch):
        async def fake_missing(frame_bytes, candidates, staff_ids):
            return False, False

        monkeypatch.setattr(dress_code_ai, "_staff_missing_compliance", fake_missing)
        frame = _blank_frame()
        coat_raised, head_raised = await process_camera_frame_pair_for_dress_code(frame, frame, db_session, a_camera)
        assert (coat_raised, head_raised) == (False, False)

    async def test_missing_only_in_second_frame_is_not_confirmed(self, db_session, a_camera, monkeypatch):
        call_count = {"n": 0}

        async def fake_missing(frame_bytes, candidates, staff_ids):
            call_count["n"] += 1
            return (True, False) if call_count["n"] == 1 else (False, False)  # frame_b then frame_a

        monkeypatch.setattr(dress_code_ai, "_staff_missing_compliance", fake_missing)
        frame = _blank_frame()
        coat_raised, head_raised = await process_camera_frame_pair_for_dress_code(frame, frame, db_session, a_camera)
        assert (coat_raised, head_raised) == (False, False)

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 0

    async def test_coat_missing_in_both_frames_raises_only_coat_event(self, db_session, a_camera, monkeypatch):
        async def fake_missing(frame_bytes, candidates, staff_ids):
            return True, False

        monkeypatch.setattr(dress_code_ai, "_staff_missing_compliance", fake_missing)
        frame = _blank_frame()
        coat_raised, head_raised = await process_camera_frame_pair_for_dress_code(frame, frame, db_session, a_camera)
        assert (coat_raised, head_raised) == (True, False)

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1
        assert events[0].module_code == COAT_MODULE_CODE
        assert events[0].severity == "past"

    async def test_both_missing_in_both_frames_raises_both_events(self, db_session, a_camera, monkeypatch):
        async def fake_missing(frame_bytes, candidates, staff_ids):
            return True, True

        monkeypatch.setattr(dress_code_ai, "_staff_missing_compliance", fake_missing)
        frame = _blank_frame()
        coat_raised, head_raised = await process_camera_frame_pair_for_dress_code(frame, frame, db_session, a_camera)
        assert (coat_raised, head_raised) == (True, True)

        events = (await db_session.execute(select(Event))).scalars().all()
        assert {e.module_code for e in events} == {COAT_MODULE_CODE, HEAD_COVERING_MODULE_CODE}

    async def test_same_camera_within_dedup_window_is_not_reraised(self, db_session, a_camera, monkeypatch):
        async def fake_missing(frame_bytes, candidates, staff_ids):
            return True, False

        monkeypatch.setattr(dress_code_ai, "_staff_missing_compliance", fake_missing)
        frame = _blank_frame()
        first = await process_camera_frame_pair_for_dress_code(frame, frame, db_session, a_camera)
        second = await process_camera_frame_pair_for_dress_code(frame, frame, db_session, a_camera)
        assert first == (True, False)
        assert second == (False, False)

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1


@pytest.mark.usefixtures("seeded")
class TestSweepConcurrency:
    async def test_no_staff_enrolled_skips_the_sweep_entirely(self, db_session, seeded):
        # No StudentStaff with type='xodim' exists in the seeded fixture ->
        # nothing to evaluate, and the sweep should short-circuit rather
        # than grab frames from every camera for nothing.
        assert await run_dress_code_ai_sweep_once(session_factory=TestSessionLocal) == 0

    async def test_one_camera_failing_does_not_stop_the_others(self, db_session, a_staff_member, monkeypatch):
        building = (await db_session.execute(select(Building))).scalars().first()
        cameras = []
        for i in range(2):
            camera = Camera(
                name=f"Kamera {i}", ip=f"10.0.9.{i + 60}", stream_url=f"rtsp://fake/{i}",
                building_id=building.id, zone="Z", resolution="1080p", status="faol",
                last_seen_at=datetime.now(timezone.utc),
            )
            db_session.add(camera)
            cameras.append(camera)
        await db_session.commit()

        calls = {"n": 0}

        async def flaky_grab_frame_pair(stream_url, gap_seconds=1.0):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated grab failure")
            frame = _blank_frame()
            return frame, frame

        async def fake_missing(frame_bytes, candidates, staff_ids):
            return False, False

        monkeypatch.setattr(dress_code_ai, "grab_frame_pair", flaky_grab_frame_pair)
        monkeypatch.setattr(dress_code_ai, "_staff_missing_compliance", fake_missing)

        await run_dress_code_ai_sweep_once(session_factory=TestSessionLocal)
        assert calls["n"] == 2  # both cameras were attempted despite the first one failing

    async def test_both_modules_disabled_skips_the_sweep_entirely(
        self, db_session, a_staff_member, monkeypatch
    ):
        await _set_module_active(db_session, COAT_MODULE_CODE, False)
        await _set_module_active(db_session, HEAD_COVERING_MODULE_CODE, False)

        building = (await db_session.execute(select(Building))).scalars().first()
        db_session.add(Camera(
            name="Kamera", ip="10.0.9.70", stream_url="rtsp://fake/x",
            building_id=building.id, zone="Z", resolution="1080p", status="faol",
            last_seen_at=datetime.now(timezone.utc),
        ))
        await db_session.commit()

        calls = {"n": 0}

        async def counting_grab_frame_pair(stream_url, gap_seconds=1.0):
            calls["n"] += 1
            frame = _blank_frame()
            return frame, frame

        monkeypatch.setattr(dress_code_ai, "grab_frame_pair", counting_grab_frame_pair)

        count = await run_dress_code_ai_sweep_once(session_factory=TestSessionLocal)
        assert count == 0
        assert calls["n"] == 0

    async def test_only_one_of_coat_head_covering_disabled_still_runs(
        self, db_session, a_staff_member, monkeypatch
    ):
        await _set_module_active(db_session, COAT_MODULE_CODE, False)  # head covering (#11) stays on

        building = (await db_session.execute(select(Building))).scalars().first()
        db_session.add(Camera(
            name="Kamera", ip="10.0.9.71", stream_url="rtsp://fake/y",
            building_id=building.id, zone="Z", resolution="1080p", status="faol",
            last_seen_at=datetime.now(timezone.utc),
        ))
        await db_session.commit()

        calls = {"n": 0}

        async def counting_grab_frame_pair(stream_url, gap_seconds=1.0):
            calls["n"] += 1
            frame = _blank_frame()
            return frame, frame

        async def fake_missing(frame_bytes, candidates, staff_ids):
            return False, False

        monkeypatch.setattr(dress_code_ai, "grab_frame_pair", counting_grab_frame_pair)
        monkeypatch.setattr(dress_code_ai, "_staff_missing_compliance", fake_missing)

        await run_dress_code_ai_sweep_once(session_factory=TestSessionLocal)
        assert calls["n"] == 1  # module #11 alone was enough to keep the sweep running
