from dataclasses import dataclass

import cv2
import numpy as np
import pytest
from sqlalchemy import select

from app.jobs import abandoned_object_ai
from app.jobs.abandoned_object_ai import (
    ABANDONED_MODULE_CODE,
    _bbox_distance,
    _centroid,
    _face_overlaps_bbox,
    _largest_static_candidate,
    _recently_flagged,
    _update_tracking,
    process_camera_frame_for_abandoned_object,
    run_abandoned_object_ai_sweep_once,
)
from app.models import Building, Camera, Event
from tests.conftest import TestSessionLocal


@dataclass
class _FakeFace:
    bbox: tuple[float, float, float, float]


def _mask_with_rect(x: int, y: int, w: int, h: int, size=(200, 200)) -> np.ndarray:
    mask = np.zeros(size, dtype=np.uint8)
    mask[y : y + h, x : x + w] = 255
    return mask


def _encode_jpeg(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def _background_frame(size=(200, 200)) -> np.ndarray:
    return np.full((*size, 3), 100, dtype=np.uint8)


def _frame_with_object(x=50, y=50, w=30, h=30, size=(200, 200)) -> np.ndarray:
    img = _background_frame(size)
    img[y : y + h, x : x + w] = 255
    return img


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Dahliz kamerasi", ip="10.0.9.7", building_id=building.id,
        zone="Dahliz", resolution="1080p", status="faol",
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera, attribute_names=["building"])
    return camera


class TestGeometryHelpers:
    def test_centroid_of_a_known_box(self):
        assert _centroid((10, 20, 30, 40)) == (25.0, 40.0)

    def test_distance_between_same_box_is_zero(self):
        assert _bbox_distance((10, 10, 20, 20), (10, 10, 20, 20)) == 0.0

    def test_distance_between_far_boxes_is_large(self):
        assert _bbox_distance((0, 0, 10, 10), (100, 100, 10, 10)) > 100

    def test_face_far_from_bbox_does_not_overlap(self):
        faces = [_FakeFace(bbox=(500.0, 500.0, 540.0, 540.0))]
        assert _face_overlaps_bbox(faces, (50, 50, 30, 30)) is False

    def test_face_inside_bbox_overlaps(self):
        faces = [_FakeFace(bbox=(55.0, 55.0, 65.0, 65.0))]
        assert _face_overlaps_bbox(faces, (50, 50, 30, 30)) is True

    def test_no_faces_never_overlaps(self):
        assert _face_overlaps_bbox([], (50, 50, 30, 30)) is False


class TestLargestStaticCandidate:
    def test_empty_mask_has_no_candidate(self):
        mask = np.zeros((200, 200), dtype=np.uint8)
        assert _largest_static_candidate(mask) is None

    def test_too_small_blob_is_ignored(self):
        mask = _mask_with_rect(50, 50, 3, 3)  # 9px area, well under abandoned_object_min_area (800)
        assert _largest_static_candidate(mask) is None

    def test_qualifying_blob_is_found(self):
        mask = _mask_with_rect(50, 50, 30, 30)  # 900px area
        candidate = _largest_static_candidate(mask)
        assert candidate is not None
        x, y, w, h = candidate
        assert (x, y) == (50, 50)
        assert w >= 28 and h >= 28  # contour bbox may be off by a pixel or two

    def test_picks_the_larger_of_two_blobs(self):
        mask = _mask_with_rect(10, 10, 30, 30)
        mask[100:160, 100:160] = 255  # a much bigger second blob
        x, y, w, h = _largest_static_candidate(mask)
        assert (x, y) == (100, 100)


class TestUpdateTracking:
    def test_single_tick_never_returns(self):
        mask = _mask_with_rect(50, 50, 30, 30)
        assert _update_tracking("cam-track-1", mask, []) is None

    def test_reaches_threshold_after_enough_consecutive_ticks(self):
        mask = _mask_with_rect(50, 50, 30, 30)
        results = [_update_tracking("cam-track-2", mask, []) for _ in range(4)]
        assert results[:3] == [None, None, None]
        assert results[3] is not None

    def test_a_moving_blob_never_accumulates(self):
        results = []
        for i in range(5):
            mask = _mask_with_rect(10 + i * 60, 10, 30, 30)  # jumps far each tick
            results.append(_update_tracking("cam-track-3", mask, []))
        assert all(r is None for r in results)

    def test_face_over_the_region_resets_tracking(self):
        mask = _mask_with_rect(50, 50, 30, 30)
        _update_tracking("cam-track-4", mask, [])
        _update_tracking("cam-track-4", mask, [])
        face_there = [_FakeFace(bbox=(60.0, 60.0, 70.0, 70.0))]
        assert _update_tracking("cam-track-4", mask, face_there) is None
        # tracking reset -- takes the full count again from here, not resumed
        results = [_update_tracking("cam-track-4", mask, []) for _ in range(4)]
        assert results[3] is not None


@pytest.mark.usefixtures("seeded")
class TestProcessCameraFrameForAbandonedObject:
    async def test_recently_flagged_dedup(self, db_session, a_camera):
        assert await _recently_flagged(db_session, a_camera.id) is False
        db_session.add(Event(
            camera_id=a_camera.id, camera_name=a_camera.name, building="Bino",
            module_code=ABANDONED_MODULE_CODE, module_name="Buyum", group="A",
            confidence=55, severity="o'rta", status="yangi",
        ))
        await db_session.commit()
        assert await _recently_flagged(db_session, a_camera.id) is True

    async def test_static_object_across_several_frames_raises_an_event(self, db_session, a_camera, monkeypatch):
        monkeypatch.setattr(abandoned_object_ai, "detect_faces", lambda frame_bytes: _no_faces())

        background = _encode_jpeg(_background_frame())
        with_object = _encode_jpeg(_frame_with_object())

        # A couple of background-only frames to let MOG2 learn the scene,
        # then the object appears and stays for several ticks in a row.
        raised = [await process_camera_frame_for_abandoned_object(background, db_session, a_camera) for _ in range(2)]
        raised += [
            await process_camera_frame_for_abandoned_object(with_object, db_session, a_camera) for _ in range(5)
        ]
        assert any(raised), f"expected an event somewhere in {raised}"

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 1
        assert events[0].module_code == ABANDONED_MODULE_CODE
        assert events[0].camera_name == a_camera.name

    async def test_a_person_standing_at_the_static_region_does_not_raise(self, db_session, a_camera, monkeypatch):
        # Same object location as above, but a face is "detected" right
        # there on every tick -- must never accumulate into an Event.
        face_at_object = [_FakeFace(bbox=(60.0, 60.0, 70.0, 70.0))]
        monkeypatch.setattr(abandoned_object_ai, "detect_faces", lambda frame_bytes: _with_faces(face_at_object))

        background = _encode_jpeg(_background_frame())
        with_object = _encode_jpeg(_frame_with_object())

        raised = [await process_camera_frame_for_abandoned_object(background, db_session, a_camera) for _ in range(2)]
        raised += [
            await process_camera_frame_for_abandoned_object(with_object, db_session, a_camera) for _ in range(6)
        ]
        assert not any(raised)

        events = (await db_session.execute(select(Event))).scalars().all()
        assert len(events) == 0


async def _no_faces():
    return []


async def _with_faces(faces):
    return faces


@pytest.mark.usefixtures("seeded")
class TestSweepConcurrency:
    async def test_one_camera_failing_does_not_stop_the_others(self, db_session, seeded, monkeypatch):
        building = (await db_session.execute(select(Building))).scalars().first()
        cameras = []
        for i in range(2):
            from datetime import datetime, timezone

            camera = Camera(
                name=f"Kamera {i}", ip=f"10.0.9.{i + 30}", stream_url=f"rtsp://fake/{i}",
                building_id=building.id, zone="Z", resolution="1080p", status="faol",
                last_seen_at=datetime.now(timezone.utc),
            )
            db_session.add(camera)
            cameras.append(camera)
        await db_session.commit()

        calls = {"n": 0}

        async def flaky_grab_frame(stream_url):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated grab failure")
            return _encode_jpeg(_background_frame())

        monkeypatch.setattr(abandoned_object_ai, "grab_frame_for_camera", flaky_grab_frame)

        await run_abandoned_object_ai_sweep_once(session_factory=TestSessionLocal)
        assert calls["n"] == 2  # both cameras were attempted despite the first one failing
