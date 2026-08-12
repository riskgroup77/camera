import json
import uuid
from pathlib import Path

import insightface
import pytest
from sqlalchemy import select

from app.jobs import vision_ai
from app.jobs.vision_ai import SLEEP_MODULE_CODE, _recently_flagged, process_camera_frame_for_sleep
from app.models import Building, Camera, Event, Faculty, StudentStaff
from app.services.face_recognition import extract_embedding

FACE_IMAGE_PATH = Path(insightface.__file__).parent / "data" / "images" / "t1.jpg"


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Sinfxona kamerasi", ip="10.0.9.2", building_id=building.id,
        zone="1-xona", resolution="1080p", status="faol",
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera, attribute_names=["building"])
    return camera


def _a_sleep_event(camera: Camera, person_name: str | None) -> Event:
    return Event(
        camera_id=camera.id, camera_name=camera.name, building="Bino",
        module_code=SLEEP_MODULE_CODE, module_name="Talabaning uxlab qolishi",
        group="E", confidence=70, severity="past", person_name=person_name, status="yangi",
    )


@pytest.mark.usefixtures("seeded")
class TestRecentlyFlagged:
    async def test_no_prior_events_is_not_flagged(self, db_session, a_camera):
        assert await _recently_flagged(db_session, a_camera.id, "Ism Familya") is False

    async def test_same_person_within_dedup_window_is_flagged(self, db_session, a_camera):
        db_session.add(_a_sleep_event(a_camera, "Ism Familya"))
        await db_session.commit()
        assert await _recently_flagged(db_session, a_camera.id, "Ism Familya") is True

    async def test_different_person_is_not_flagged(self, db_session, a_camera):
        db_session.add(_a_sleep_event(a_camera, "Boshqa Odam"))
        await db_session.commit()
        assert await _recently_flagged(db_session, a_camera.id, "Ism Familya") is False

    async def test_unidentified_sleeper_dedupes_by_camera(self, db_session, a_camera):
        db_session.add(_a_sleep_event(a_camera, None))
        await db_session.commit()
        assert await _recently_flagged(db_session, a_camera.id, None) is True

    async def test_unidentified_sleeper_at_a_different_camera_is_not_flagged(self, db_session, a_camera):
        db_session.add(_a_sleep_event(a_camera, None))
        await db_session.commit()
        assert await _recently_flagged(db_session, uuid.uuid4(), None) is False


@pytest.mark.usefixtures("seeded")
class TestProcessCameraFrameForSleep:
    async def test_no_face_in_frame_raises_no_event(self, db_session, a_camera):
        import io

        from PIL import Image

        blank = Image.frombytes("RGB", (100, 100), bytes([255] * 100 * 100 * 3))
        buf = io.BytesIO()
        blank.save(buf, format="JPEG")

        raised = await process_camera_frame_for_sleep(buf.getvalue(), buf.getvalue(), db_session, a_camera)
        assert raised == 0

    async def test_awake_face_raises_no_event(self, db_session, a_camera):
        # t1.jpg is a real open-eyed photo — exercises the real EAR pipeline
        # end to end (not just the dedup logic above), no patching needed.
        frame = FACE_IMAGE_PATH.read_bytes()
        raised = await process_camera_frame_for_sleep(frame, frame, db_session, a_camera)
        assert raised == 0
        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 0

    async def test_asleep_in_both_frames_raises_an_event(self, db_session, a_camera, monkeypatch):
        # No real closed-eye fixture photo is available, so this forces the
        # EAR check itself (already unit-tested in test_sleep_detection.py)
        # to report "asleep", to exercise everything downstream: matching,
        # dedup, Event creation.
        monkeypatch.setattr(vision_ai, "is_asleep", lambda landmarks: True)

        frame = FACE_IMAGE_PATH.read_bytes()
        raised = await process_camera_frame_for_sleep(frame, frame, db_session, a_camera)
        assert raised == 1

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1
        assert events[0].module_code == SLEEP_MODULE_CODE
        assert events[0].camera_name == a_camera.name
        assert events[0].severity == "past"
        assert events[0].confidence == 80

    async def test_asleep_only_in_second_frame_is_not_confirmed(self, db_session, a_camera, monkeypatch):
        # The whole point of requiring two frames: a face that reads asleep
        # in frame_b but was awake in frame_a (a blink, or a one-off
        # bad-angle glitch — see the module docstring) must NOT raise.
        # t1.jpg has 6 detectable faces, so is_asleep() is called 6 times
        # while building frame_a's confirmed set, then again per-face while
        # walking frame_b — flip the mock's answer after those first 6 to
        # simulate "asleep now, wasn't a moment ago".
        call_count = {"n": 0}

        def fake_is_asleep(landmarks):
            call_count["n"] += 1
            return call_count["n"] > 6

        monkeypatch.setattr(vision_ai, "is_asleep", fake_is_asleep)

        frame = FACE_IMAGE_PATH.read_bytes()
        raised = await process_camera_frame_for_sleep(frame, frame, db_session, a_camera)
        assert raised == 0

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 0

    async def test_asleep_face_matched_to_an_enrolled_person_is_named(self, db_session, a_camera, monkeypatch):
        # t1.jpg has 6 detectable faces (unlike extract_embedding(), which
        # only ever looks at the largest one). The enrolled embedding is
        # extracted the same way attendance enrollment does — from the
        # largest face — so exactly one of the 6 should match it; the rest
        # are unmatched strangers, of which only the first raises an event
        # (the other 4 get deduped against that first "unidentified sleeper
        # at this camera" slot — see TestRecentlyFlagged above).
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        embedding = await extract_embedding(FACE_IMAGE_PATH.read_bytes())
        student = StudentStaff(
            full_name="Uxlab Qolgan Talaba", type="talaba", faculty_id=faculty.id, group_or_position="1",
            biometric_embedding=json.dumps(embedding),
        )
        db_session.add(student)
        await db_session.commit()

        monkeypatch.setattr(vision_ai, "is_asleep", lambda landmarks: True)
        frame = FACE_IMAGE_PATH.read_bytes()
        raised = await process_camera_frame_for_sleep(frame, frame, db_session, a_camera)
        assert raised == 2

        events = (await db_session.execute(select(Event))).scalars().all()
        names = {e.person_name for e in events}
        assert "Uxlab Qolgan Talaba" in names
        assert None in names

    async def test_same_person_within_dedup_window_is_not_reraised(self, db_session, a_camera, monkeypatch):
        monkeypatch.setattr(vision_ai, "is_asleep", lambda landmarks: True)

        frame = FACE_IMAGE_PATH.read_bytes()
        first = await process_camera_frame_for_sleep(frame, frame, db_session, a_camera)
        second = await process_camera_frame_for_sleep(frame, frame, db_session, a_camera)
        assert first == 1
        assert second == 0

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1
