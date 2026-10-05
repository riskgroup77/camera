"""app/services/motion_gate.py — bo'sh eshik kadri tahlilga bormaydi."""

import cv2
import numpy as np
import pytest

from app.config import settings
from app.services import motion_gate
from app.services.motion_gate import MotionGate


def _jpeg(person_at: int | None = None) -> bytes:
    image = np.full((720, 1280, 3), 90, dtype=np.uint8)
    if person_at is not None:
        cv2.rectangle(image, (person_at, 200), (person_at + 160, 600), (230, 230, 230), -1)
    ok, data = cv2.imencode(".jpg", image)
    assert ok
    return data.tobytes()


@pytest.fixture(autouse=True)
def _gate_on(monkeypatch):
    monkeypatch.setattr(settings, "motion_gate_enabled", True)
    monkeypatch.setattr(settings, "motion_gate_max_skip_seconds", 30.0)


def test_first_frame_is_always_analysed_and_a_still_scene_is_not():
    gate = MotionGate()
    empty = _jpeg()
    assert gate.should_analyse(empty) is True
    assert gate.should_analyse(empty) is False
    assert gate.skipped == 1


def test_a_person_walking_in_triggers_analysis():
    gate = MotionGate()
    gate.should_analyse(_jpeg())
    assert gate.should_analyse(_jpeg(person_at=500)) is True


def test_motion_outside_the_door_area_is_ignored():
    gate = MotionGate()
    door = (0.0, 0.0, 0.3, 1.0)  # chap uchdan bir
    gate.should_analyse(_jpeg(), door)
    assert gate.should_analyse(_jpeg(person_at=900), door) is False


def test_a_skipped_camera_is_still_checked_now_and_then(monkeypatch):
    gate = MotionGate()
    empty = _jpeg()
    gate.should_analyse(empty)
    clock = [1000.0]
    monkeypatch.setattr(motion_gate, "monotonic", lambda: clock[0])
    gate.last_analysed = 1000.0
    assert gate.should_analyse(empty) is False
    clock[0] += 31
    assert gate.should_analyse(empty) is True


def test_disabled_gate_analyses_everything(monkeypatch):
    monkeypatch.setattr(settings, "motion_gate_enabled", False)
    gate = MotionGate()
    empty = _jpeg()
    assert gate.should_analyse(empty) and gate.should_analyse(empty)


def test_motion_region_covers_the_person_not_the_whole_frame(monkeypatch):
    """Harakat hududi: detektor faqat odam atrofini ko'radi (tezroq)."""
    monkeypatch.setattr(settings, "motion_roi_enabled", True)
    gate = MotionGate()
    gate.should_analyse(_jpeg())
    assert gate.should_analyse(_jpeg(person_at=500)) is True
    x1, y1, x2, y2 = gate.region
    assert x1 < 500 / 1280 and x2 > 660 / 1280  # odam ichida
    assert y1 < 200 / 720 and y2 > 600 / 720
    assert (x2 - x1) * (y2 - y1) < 0.6


def test_forced_and_first_analyses_use_the_whole_frame():
    gate = MotionGate()
    gate.should_analyse(_jpeg())
    assert gate.region is None


def test_huge_motion_falls_back_to_the_whole_frame(monkeypatch):
    monkeypatch.setattr(settings, "motion_roi_max_area", 0.05)
    gate = MotionGate()
    gate.should_analyse(_jpeg())
    gate.should_analyse(_jpeg(person_at=500))
    assert gate.region is None


def test_region_is_composed_inside_the_door_area():
    from app.services.motion_gate import compose_roi

    assert compose_roi((0.5, 0.0, 1.0, 1.0), (0.0, 0.5, 0.5, 1.0)) == (0.5, 0.5, 0.75, 1.0)
    assert compose_roi(None, (0.1, 0.1, 0.2, 0.2)) == (0.1, 0.1, 0.2, 0.2)
    assert compose_roi((0.1, 0.1, 0.2, 0.2), None) == (0.1, 0.1, 0.2, 0.2)


def test_idle_peek_sees_a_person_arrive_without_touching_the_gate():
    gate = MotionGate()
    gate.should_analyse(_jpeg())
    assert gate.moved_since_peek(_jpeg()) is False  # birinchi tekshiruv — tayanch
    assert gate.moved_since_peek(_jpeg()) is False
    assert gate.moved_since_peek(_jpeg(person_at=500)) is True
    assert gate.skipped == 0
