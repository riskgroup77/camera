from pathlib import Path

import ultralytics

from app.services.object_detection import detect_objects

# Ultralytics' own bundled demo photo — a real bus + 3 people, verified by
# direct inspection before writing these tests (not assumed): bus (class
# 5, ~0.87 confidence), person (class 0) x3, nothing else above ~0.4
# confidence.
BUS_IMAGE_PATH = Path(ultralytics.__file__).parent / "assets" / "bus.jpg"


class TestDetectObjects:
    async def test_detects_the_real_bus_in_the_photo(self):
        detections = await detect_objects(BUS_IMAGE_PATH.read_bytes(), class_ids=[5], confidence=0.4)
        assert len(detections) >= 1
        assert detections[0].class_name == "bus"
        assert detections[0].confidence > 0.4

    async def test_detects_the_real_people_in_the_photo(self):
        detections = await detect_objects(BUS_IMAGE_PATH.read_bytes(), class_ids=[0], confidence=0.4)
        assert len(detections) == 3
        assert all(d.class_name == "person" for d in detections)

    async def test_class_filter_excludes_classes_not_asked_for(self):
        # The photo has no cell phone in it -- filtering to that class
        # alone should return nothing, even though the image has real,
        # detectable objects (bus, people) at high confidence.
        detections = await detect_objects(BUS_IMAGE_PATH.read_bytes(), class_ids=[67], confidence=0.3)
        assert detections == []

    async def test_corrupt_image_bytes_returns_empty_list(self):
        detections = await detect_objects(b"not a real image", class_ids=[0], confidence=0.4)
        assert detections == []

    async def test_bbox_is_a_real_four_value_box(self):
        detections = await detect_objects(BUS_IMAGE_PATH.read_bytes(), class_ids=[5], confidence=0.4)
        x1, y1, x2, y2 = detections[0].bbox
        assert x2 > x1
        assert y2 > y1
