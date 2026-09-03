from pathlib import Path
from types import SimpleNamespace

import insightface
import pytest
from sqlalchemy import select

from app.config import settings
from app.jobs import unauthorized_person_ai
from app.jobs.unauthorized_person_ai import (
    UNAUTHORIZED_MODULE_CODE,
    _filter_faces_by_size,
    _recently_flagged,
    process_camera_frame_pair_for_unauthorized,
    run_unauthorized_person_ai_sweep_once,
)
from app.models import Building, Camera, Event
from tests.conftest import TestSessionLocal

FACE_IMAGE_PATH = Path(insightface.__file__).parent / "data" / "images" / "t1.jpg"


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Kirish kamerasi", ip="10.0.9.3", building_id=building.id,
        zone="Kirish", resolution="1080p", status="faol",
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera, attribute_names=["building"])
    return camera


@pytest.mark.usefixtures("seeded")
class TestRecentlyFlagged:
    async def test_no_prior_events_is_not_flagged(self, db_session, a_camera):
        assert await _recently_flagged(db_session, a_camera.id) is False

    async def test_recent_event_at_same_camera_is_flagged(self, db_session, a_camera):
        db_session.add(Event(
            camera_id=a_camera.id, camera_name=a_camera.name, building="Bino",
            module_code=UNAUTHORIZED_MODULE_CODE, module_name="Notanish shaxs",
            group="A", confidence=70, severity="yuqori", status="yangi",
        ))
        await db_session.commit()
        assert await _recently_flagged(db_session, a_camera.id) is True


class TestFilterFacesBySize:
    def test_face_below_min_fraction_is_dropped(self, monkeypatch):
        monkeypatch.setattr(unauthorized_person_ai, "_frame_height", lambda image_bytes: 1000)
        monkeypatch.setattr(settings, "unauthorized_min_face_height_fraction", 0.1)
        small_face = SimpleNamespace(bbox=[0, 0, 50, 50])  # 50px height on a 1000px frame = 5% < 10%
        assert _filter_faces_by_size([small_face], b"fake") == []

    def test_face_at_or_above_min_fraction_is_kept(self, monkeypatch):
        monkeypatch.setattr(unauthorized_person_ai, "_frame_height", lambda image_bytes: 1000)
        monkeypatch.setattr(settings, "unauthorized_min_face_height_fraction", 0.1)
        large_face = SimpleNamespace(bbox=[0, 0, 50, 150])  # 150px height = 15% >= 10%
        assert _filter_faces_by_size([large_face], b"fake") == [large_face]

    def test_undecodable_frame_fails_open_rather_than_drop_real_faces(self, monkeypatch):
        monkeypatch.setattr(unauthorized_person_ai, "_frame_height", lambda image_bytes: 0)
        tiny_face = SimpleNamespace(bbox=[0, 0, 1, 1])
        assert _filter_faces_by_size([tiny_face], b"fake") == [tiny_face]

    def test_empty_faces_list_returns_as_is(self):
        assert _filter_faces_by_size([], b"fake") == []


@pytest.mark.usefixtures("seeded")
class TestProcessCameraFramePairForUnauthorized:
    @pytest.fixture(autouse=True)
    def _roster_guard_off(self, monkeypatch):
        """These tests exercise the MATCHING logic — face size filtering,
        two-frame confirmation, dedup. The separate roster-size guard
        (settings.unauthorized_min_enrolled) would stop every one of them
        before they reach that logic, since a test database has almost
        nobody enrolled. The guard has its own tests below."""
        monkeypatch.setattr(settings, "unauthorized_min_enrolled", 0)

    async def test_small_face_like_a_wall_photo_does_not_raise(self, db_session, a_camera, monkeypatch):
        # Simulates the real-world false positive this filter targets: a
        # printed photo on a wall (a noticeboard, a poster) reads as a
        # face to InsightFace but is a small fraction of the frame — see
        # app/config.py's unauthorized_min_face_height_fraction docstring.
        monkeypatch.setattr(unauthorized_person_ai, "_filter_faces_by_size", lambda faces, image_bytes: [])

        frame = FACE_IMAGE_PATH.read_bytes()
        raised = await process_camera_frame_pair_for_unauthorized(frame, frame, db_session, a_camera)
        assert raised is False

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 0


    async def test_no_face_in_frame_raises_no_event(self, db_session, a_camera):
        import io

        from PIL import Image

        blank = Image.frombytes("RGB", (100, 100), bytes([255] * 100 * 100 * 3))
        buf = io.BytesIO()
        blank.save(buf, format="JPEG")

        raised = await process_camera_frame_pair_for_unauthorized(buf.getvalue(), buf.getvalue(), db_session, a_camera)
        assert raised is False

    async def test_no_enrolled_people_flags_every_face(self, db_session, a_camera):
        frame = FACE_IMAGE_PATH.read_bytes()
        raised = await process_camera_frame_pair_for_unauthorized(frame, frame, db_session, a_camera)
        assert raised is True

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1
        assert events[0].module_code == UNAUTHORIZED_MODULE_CODE
        assert events[0].camera_name == a_camera.name
        assert events[0].severity == "yuqori"

    async def test_unmatched_only_in_second_frame_is_not_confirmed(self, db_session, a_camera, monkeypatch):
        # The whole point of requiring two frames: a face that reads
        # unmatched in frame_b but matched fine in frame_a (a one-off bad
        # angle/lighting glitch — see the module docstring) must NOT
        # raise. process_camera_frame_pair_for_unauthorized() checks
        # frame_b FIRST, then frame_a, so patch _has_unmatched_face
        # itself (candidates.is_empty short-circuits before
        # CandidateMatrix.best_matches is ever called here, since nobody
        # is enrolled in this test — patching at that lower level
        # wouldn't actually be exercised).
        call_count = {"n": 0}

        def fake_has_unmatched_face(faces, candidates):
            call_count["n"] += 1
            return call_count["n"] == 1  # frame_b: unmatched; frame_a: everyone matched

        monkeypatch.setattr(unauthorized_person_ai, "_has_unmatched_face", fake_has_unmatched_face)

        frame = FACE_IMAGE_PATH.read_bytes()
        raised = await process_camera_frame_pair_for_unauthorized(frame, frame, db_session, a_camera)
        assert raised is False

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 0

    async def test_same_camera_within_dedup_window_is_not_reraised(self, db_session, a_camera):
        frame = FACE_IMAGE_PATH.read_bytes()
        first = await process_camera_frame_pair_for_unauthorized(frame, frame, db_session, a_camera)
        second = await process_camera_frame_pair_for_unauthorized(frame, frame, db_session, a_camera)
        assert first is True
        assert second is False

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1


@pytest.mark.usefixtures("seeded")
class TestSweepConcurrency:
    async def test_one_camera_failing_does_not_stop_the_others(self, db_session, seeded, monkeypatch):
        building = (await db_session.execute(select(Building))).scalars().first()
        cameras = []
        for i in range(2):
            from datetime import datetime, timezone

            camera = Camera(
                name=f"Kamera {i}", ip=f"10.0.9.{i + 10}", stream_url=f"rtsp://fake/{i}",
                building_id=building.id, zone="Z", resolution="1080p", status="faol",
                last_seen_at=datetime.now(timezone.utc), is_entrance=True,
            )
            db_session.add(camera)
            cameras.append(camera)
        await db_session.commit()

        calls = {"n": 0}

        async def flaky_grab_frame_pair(stream_url, gap_seconds=1.0):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated grab failure")
            frame = FACE_IMAGE_PATH.read_bytes()
            return frame, frame

        monkeypatch.setattr(unauthorized_person_ai, "grab_frame_pair_for_camera", flaky_grab_frame_pair)
        # This test is about error isolation, not about the roster guard —
        # switch the guard off so an empty test roster doesn't end the
        # sweep before any camera is touched (see settings.unauthorized_min_enrolled).
        monkeypatch.setattr(settings, "unauthorized_min_enrolled", 0)

        await run_unauthorized_person_ai_sweep_once(session_factory=TestSessionLocal)
        assert calls["n"] == 2  # both cameras were attempted despite the first one failing

    async def test_the_guard_lives_in_the_shared_decision_function(
        self, db_session, seeded, monkeypatch
    ):
        """unified_face_sweep.py calls process_camera_frame_pair_for_unauthorized
        directly, so a guard placed only in this module's own sweep is not a
        guard at all. That is not hypothetical: it shipped that way, and the
        same corridor camera kept raising alerts after the deploy.
        """
        building = (await db_session.execute(select(Building))).scalars().first()
        from datetime import datetime, timezone

        camera = Camera(
            name="Kamera", ip="10.0.9.55", stream_url="rtsp://fake/y",
            building_id=building.id, zone="Z", resolution="1080p", status="faol",
            last_seen_at=datetime.now(timezone.utc),
        )
        db_session.add(camera)
        await db_session.commit()
        await db_session.refresh(camera, ["building"])

        detected = {"n": 0}

        async def counting_detect(frame):
            detected["n"] += 1
            return []

        monkeypatch.setattr(unauthorized_person_ai, "detect_faces", counting_detect)
        monkeypatch.setattr(settings, "unauthorized_min_enrolled", 10)

        frame = FACE_IMAGE_PATH.read_bytes()
        raised = await unauthorized_person_ai.process_camera_frame_pair_for_unauthorized(
            frame, frame, db_session, camera
        )

        assert raised is False
        # The guard sits before detect_faces, the most expensive call here.
        assert detected["n"] == 0

    async def test_sweep_stops_when_almost_nobody_is_enrolled(self, db_session, seeded, monkeypatch):
        """"Not in the database" says nothing when the database is empty.

        Production audit: 3 enrolled faces and 134 unauthorized-person
        alerts, 45% of them from a single corridor camera and 37 raised
        overnight in an empty building. The module was not wrong — with
        that roster, everyone genuinely is unknown — it was just useless,
        and it buried the alerts that mattered."""
        building = (await db_session.execute(select(Building))).scalars().first()
        from datetime import datetime, timezone

        db_session.add(
            Camera(
                name="Kamera", ip="10.0.9.99", stream_url="rtsp://fake/x",
                building_id=building.id, zone="Z", resolution="1080p", status="faol",
                last_seen_at=datetime.now(timezone.utc), is_entrance=True,
            )
        )
        await db_session.commit()

        grabbed = {"n": 0}

        async def counting_grab(stream_url, gap_seconds=1.0):
            grabbed["n"] += 1
            frame = FACE_IMAGE_PATH.read_bytes()
            return frame, frame

        monkeypatch.setattr(unauthorized_person_ai, "grab_frame_pair_for_camera", counting_grab)
        monkeypatch.setattr(settings, "unauthorized_min_enrolled", 10)

        raised = await run_unauthorized_person_ai_sweep_once(session_factory=TestSessionLocal)

        assert raised == 0
        assert grabbed["n"] == 0  # not even a frame was pulled — no camera work, no CPU burnt
