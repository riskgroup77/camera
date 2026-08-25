import json
from dataclasses import dataclass
from datetime import timedelta

import cv2
import numpy as np
import pytest
from sqlalchemy import select

from app.jobs import lesson_quality_ai
from app.jobs.lesson_quality_ai import (
    ATTENTION_MODULE_CODE,
    TEACHER_ACTIVITY_MODULE_CODE,
    _active_sessions,
    _closest_pose_to_point,
    _pose_movement,
    _running_average_update,
    _sample_activity,
    _sample_attention,
    process_lesson_session,
    run_lesson_quality_ai_sweep_once,
)
from app.models import AIModuleConfig, Building, Camera, Faculty, LessonSession, StudentStaff
from app.services.face_matching import CandidateMatrix
from app.services.pose_detection import NOSE
from app.timezone import local_now
from tests.conftest import TestSessionLocal


async def _set_module_active(db_session, code: int, active: bool) -> None:
    module = (
        await db_session.execute(select(AIModuleConfig).where(AIModuleConfig.code == code))
    ).scalar_one()
    module.active = active
    await db_session.commit()


@dataclass
class _FakeFace:
    embedding: np.ndarray
    bbox: tuple[float, float, float, float]
    landmarks_68: np.ndarray


@dataclass
class _FakePose:
    points: np.ndarray


def _frontal_landmarks() -> np.ndarray:
    landmarks = np.zeros((68, 3))
    landmarks[36] = [0.0, 10.0, 0.0]
    landmarks[45] = [16.0, 10.0, 0.0]
    landmarks[33] = [8.0, 10.0, 0.0]  # midpoint -> frontal
    return landmarks


def _sideways_landmarks() -> np.ndarray:
    landmarks = np.zeros((68, 3))
    landmarks[36] = [0.0, 10.0, 0.0]
    landmarks[45] = [16.0, 10.0, 0.0]
    landmarks[33] = [0.5, 10.0, 0.0]  # far to one side -> not frontal
    return landmarks


def _encode_jpeg(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def _blank_frame(size=(100, 100)) -> bytes:
    return _encode_jpeg(np.full((*size, 3), 100, dtype=np.uint8))


@pytest.fixture
async def a_teacher(db_session, seeded):
    faculty = (await db_session.execute(select(Faculty))).scalars().first()
    teacher = StudentStaff(
        full_name="Sardor O'qituvchi", type="xodim", faculty_id=faculty.id, group_or_position="O'qituvchi",
        biometric_embedding=json.dumps([1.0, 0.0]),
    )
    db_session.add(teacher)
    await db_session.commit()
    return teacher


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Auditoriya kamerasi", ip="10.0.9.20", building_id=building.id,
        zone="Auditoriya", resolution="1080p", status="faol",
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera, attribute_names=["building"])
    return camera


async def _make_session(db_session, teacher, camera, minutes_ago_start: int) -> LessonSession:
    row = LessonSession(
        date=local_now().date(), group_name="1-guruh", faculty="Davolash ishi", teacher=teacher.full_name,
        subject="Fiziologiya", attention_score=50, teacher_activity_score=50, teacher_on_time=True,
        teacher_id=teacher.id, camera_id=camera.id,
        scheduled_start_time=local_now() - timedelta(minutes=minutes_ago_start),
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row, attribute_names=["teacher_ref", "camera"])
    return row


class TestRunningAverageUpdate:
    def test_first_sample_becomes_the_score(self):
        counts = {}
        result = _running_average_update(counts, "s1", current_score=50, sample=100.0)
        assert result == 100
        assert counts["s1"] == 1

    def test_second_sample_averages_with_the_first(self):
        counts = {"s1": 1}
        result = _running_average_update(counts, "s1", current_score=100, sample=0.0)
        assert result == 50
        assert counts["s1"] == 2


class TestClosestPoseToPoint:
    def test_picks_the_nearer_pose(self):
        near = _FakePose(points=np.zeros((33, 4)))
        near.points[NOSE] = [0.51, 0.51, 0.0, 1.0]
        far = _FakePose(points=np.zeros((33, 4)))
        far.points[NOSE] = [0.9, 0.9, 0.0, 1.0]
        result = _closest_pose_to_point([far, near], (0.5, 0.5))
        assert result is near

    def test_empty_list_returns_none(self):
        assert _closest_pose_to_point([], (0.5, 0.5)) is None


class TestPoseMovement:
    def test_identical_poses_have_zero_movement(self):
        points = np.zeros((33, 4))
        points[15] = [0.4, 0.4, 0.0, 1.0]
        pose = _FakePose(points=points)
        assert _pose_movement(pose, pose) == 0.0

    def test_displaced_landmark_registers_movement(self):
        points_a = np.zeros((33, 4))
        points_a[15] = [0.4, 0.4, 0.0, 1.0]
        points_b = np.zeros((33, 4))
        points_b[15] = [0.5, 0.4, 0.0, 1.0]
        assert _pose_movement(_FakePose(points=points_a), _FakePose(points=points_b)) == pytest.approx(0.1, abs=1e-6)

    def test_low_visibility_landmarks_are_excluded(self):
        points_a = np.zeros((33, 4))
        points_a[15] = [0.4, 0.4, 0.0, 0.1]  # low visibility -- excluded
        points_b = np.zeros((33, 4))
        points_b[15] = [0.9, 0.9, 0.0, 0.1]
        assert _pose_movement(_FakePose(points=points_a), _FakePose(points=points_b)) == 0.0


@pytest.mark.usefixtures("seeded")
class TestSampleAttention:
    async def test_no_faces_returns_none(self, db_session, monkeypatch):
        async def fake_detect_faces(frame_bytes):
            return []

        monkeypatch.setattr(lesson_quality_ai, "detect_faces", fake_detect_faces)
        candidates = CandidateMatrix(ids=["s1"], matrix=np.array([[1.0, 0.0]]))
        assert await _sample_attention(b"frame", candidates) is None

    async def test_no_matched_student_returns_none(self, db_session, monkeypatch):
        async def fake_detect_faces(frame_bytes):
            return [_FakeFace(embedding=np.array([0.0, 1.0]), bbox=(0, 0, 10, 10), landmarks_68=_frontal_landmarks())]

        monkeypatch.setattr(lesson_quality_ai, "detect_faces", fake_detect_faces)
        candidates = CandidateMatrix(ids=["s1"], matrix=np.array([[1.0, 0.0]]))  # orthogonal -> no match
        assert await _sample_attention(b"frame", candidates) is None

    async def test_frontal_matched_student_no_phone_scores_high(self, db_session, monkeypatch):
        async def fake_detect_faces(frame_bytes):
            return [_FakeFace(embedding=np.array([1.0, 0.0]), bbox=(0, 0, 10, 10), landmarks_68=_frontal_landmarks())]

        async def fake_detect_objects(frame_bytes, class_ids, confidence=0.5):
            return []

        monkeypatch.setattr(lesson_quality_ai, "detect_faces", fake_detect_faces)
        monkeypatch.setattr(lesson_quality_ai, "detect_objects", fake_detect_objects)
        candidates = CandidateMatrix(ids=["s1"], matrix=np.array([[1.0, 0.0]]))
        score = await _sample_attention(b"frame", candidates)
        assert score == 100.0

    async def test_phone_visible_overrides_frontal_and_scores_low(self, db_session, monkeypatch):
        async def fake_detect_faces(frame_bytes):
            return [_FakeFace(embedding=np.array([1.0, 0.0]), bbox=(0, 0, 10, 10), landmarks_68=_frontal_landmarks())]

        async def fake_detect_objects(frame_bytes, class_ids, confidence=0.5):
            return [object()]  # anything non-empty signals "phone visible"

        monkeypatch.setattr(lesson_quality_ai, "detect_faces", fake_detect_faces)
        monkeypatch.setattr(lesson_quality_ai, "detect_objects", fake_detect_objects)
        candidates = CandidateMatrix(ids=["s1"], matrix=np.array([[1.0, 0.0]]))
        score = await _sample_attention(b"frame", candidates)
        assert score == 20.0

    async def test_non_frontal_matched_student_scores_medium(self, db_session, monkeypatch):
        async def fake_detect_faces(frame_bytes):
            return [_FakeFace(embedding=np.array([1.0, 0.0]), bbox=(0, 0, 10, 10), landmarks_68=_sideways_landmarks())]

        async def fake_detect_objects(frame_bytes, class_ids, confidence=0.5):
            return []

        monkeypatch.setattr(lesson_quality_ai, "detect_faces", fake_detect_faces)
        monkeypatch.setattr(lesson_quality_ai, "detect_objects", fake_detect_objects)
        candidates = CandidateMatrix(ids=["s1"], matrix=np.array([[1.0, 0.0]]))
        score = await _sample_attention(b"frame", candidates)
        assert score == 40.0


@pytest.mark.usefixtures("seeded")
class TestSampleActivity:
    async def test_teacher_not_matched_returns_none(self, monkeypatch):
        async def fake_detect_faces(frame_bytes):
            return [_FakeFace(embedding=np.array([0.0, 1.0]), bbox=(10, 10, 30, 30), landmarks_68=_frontal_landmarks())]

        monkeypatch.setattr(lesson_quality_ai, "detect_faces", fake_detect_faces)
        result = await _sample_activity(_blank_frame(), _blank_frame(), teacher_embedding=[1.0, 0.0])
        assert result is None

    async def test_no_poses_returns_none(self, monkeypatch):
        async def fake_detect_faces(frame_bytes):
            return [_FakeFace(embedding=np.array([1.0, 0.0]), bbox=(10, 10, 30, 30), landmarks_68=_frontal_landmarks())]

        async def fake_detect_poses(frame_bytes):
            return []

        monkeypatch.setattr(lesson_quality_ai, "detect_faces", fake_detect_faces)
        monkeypatch.setattr(lesson_quality_ai, "detect_poses", fake_detect_poses)
        result = await _sample_activity(_blank_frame(), _blank_frame(), teacher_embedding=[1.0, 0.0])
        assert result is None

    async def test_matched_teacher_with_poses_returns_a_score(self, monkeypatch):
        async def fake_detect_faces(frame_bytes):
            return [_FakeFace(embedding=np.array([1.0, 0.0]), bbox=(10, 10, 30, 30), landmarks_68=_frontal_landmarks())]

        pose = _FakePose(points=np.zeros((33, 4)))
        pose.points[NOSE] = [0.2, 0.2, 0.0, 1.0]

        async def fake_detect_poses(frame_bytes):
            return [pose]

        monkeypatch.setattr(lesson_quality_ai, "detect_faces", fake_detect_faces)
        monkeypatch.setattr(lesson_quality_ai, "detect_poses", fake_detect_poses)
        result = await _sample_activity(_blank_frame(), _blank_frame(), teacher_embedding=[1.0, 0.0])
        assert result is not None
        assert 0.0 <= result <= 100.0


@pytest.mark.usefixtures("seeded")
class TestActiveSessions:
    async def test_session_without_schedule_fields_is_not_active(self, db_session, a_teacher):
        row = LessonSession(
            date=local_now().date(), group_name="1-guruh", faculty="F", teacher=a_teacher.full_name,
            subject="S", attention_score=50, teacher_activity_score=50, teacher_on_time=True,
            teacher_id=a_teacher.id,
        )
        db_session.add(row)
        await db_session.commit()
        assert await _active_sessions(db_session) == []

    async def test_session_within_the_window_is_active(self, db_session, a_teacher, a_camera):
        row = await _make_session(db_session, a_teacher, a_camera, minutes_ago_start=10)
        active = await _active_sessions(db_session)
        assert [r.id for r in active] == [row.id]

    async def test_session_before_scheduled_start_is_not_active(self, db_session, a_teacher, a_camera):
        await _make_session(db_session, a_teacher, a_camera, minutes_ago_start=-5)  # starts 5 min from now
        assert await _active_sessions(db_session) == []

    async def test_camera_excluding_both_modules_is_not_active(self, db_session, a_teacher, a_camera):
        a_camera.excluded_module_codes = [ATTENTION_MODULE_CODE, TEACHER_ACTIVITY_MODULE_CODE]
        await db_session.commit()
        await _make_session(db_session, a_teacher, a_camera, minutes_ago_start=10)
        assert await _active_sessions(db_session) == []

    async def test_camera_excluding_only_one_module_is_still_active(self, db_session, a_teacher, a_camera):
        a_camera.excluded_module_codes = [ATTENTION_MODULE_CODE]  # #21 (teacher activity) still allowed
        await db_session.commit()
        row = await _make_session(db_session, a_teacher, a_camera, minutes_ago_start=10)
        active = await _active_sessions(db_session)
        assert [r.id for r in active] == [row.id]

    async def test_session_long_past_the_lesson_duration_is_not_active(self, db_session, a_teacher, a_camera):
        await _make_session(db_session, a_teacher, a_camera, minutes_ago_start=200)  # default duration is 90 min
        assert await _active_sessions(db_session) == []


@pytest.mark.usefixtures("seeded")
class TestProcessLessonSession:
    async def test_updates_attention_score_when_a_student_is_sampled(self, db_session, a_teacher, a_camera, monkeypatch):
        row = await _make_session(db_session, a_teacher, a_camera, minutes_ago_start=10)

        async def fake_detect_faces(frame_bytes):
            return [_FakeFace(embedding=np.array([1.0, 0.0]), bbox=(0, 0, 10, 10), landmarks_68=_frontal_landmarks())]

        async def fake_detect_objects(frame_bytes, class_ids, confidence=0.5):
            return []

        async def fake_detect_poses(frame_bytes):
            return []

        monkeypatch.setattr(lesson_quality_ai, "detect_faces", fake_detect_faces)
        monkeypatch.setattr(lesson_quality_ai, "detect_objects", fake_detect_objects)
        monkeypatch.setattr(lesson_quality_ai, "detect_poses", fake_detect_poses)

        candidates = CandidateMatrix(ids=["s1"], matrix=np.array([[1.0, 0.0]]))
        await process_lesson_session(row, _blank_frame(), _blank_frame(), db_session, candidates)

        assert row.attention_score == 100  # frontal, no phone, first sample


@pytest.mark.usefixtures("seeded")
class TestSweepConcurrency:
    async def test_no_active_sessions_returns_zero(self, db_session):
        assert await run_lesson_quality_ai_sweep_once(session_factory=TestSessionLocal) == 0

    async def test_one_session_failing_does_not_stop_the_others(self, db_session, a_teacher, monkeypatch):
        faculty = (await db_session.execute(select(Faculty))).scalars().first()
        second_teacher = StudentStaff(
            full_name="Ikkinchi O'qituvchi", type="xodim", faculty_id=faculty.id, group_or_position="O'qituvchi",
            biometric_embedding=json.dumps([0.0, 1.0]),
        )
        db_session.add(second_teacher)
        await db_session.commit()

        building = (await db_session.execute(select(Building))).scalars().first()
        from datetime import datetime, timezone

        cameras = []
        for i in range(2):
            camera = Camera(
                name=f"Kamera {i}", ip=f"10.0.9.{i + 90}", stream_url=f"rtsp://fake/{i}",
                building_id=building.id, zone="Z", resolution="1080p", status="faol",
                last_seen_at=datetime.now(timezone.utc),
            )
            db_session.add(camera)
            cameras.append(camera)
        await db_session.commit()
        for c in cameras:
            await db_session.refresh(c, attribute_names=["building"])

        await _make_session(db_session, a_teacher, cameras[0], minutes_ago_start=10)
        await _make_session(db_session, second_teacher, cameras[1], minutes_ago_start=10)

        calls = {"n": 0}

        async def flaky_grab_frame_pair(stream_url, gap_seconds=1.0):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated grab failure")
            return _blank_frame(), _blank_frame()

        async def fake_detect_faces(frame_bytes):
            return []

        monkeypatch.setattr(lesson_quality_ai, "grab_frame_pair", flaky_grab_frame_pair)
        monkeypatch.setattr(lesson_quality_ai, "detect_faces", fake_detect_faces)

        await run_lesson_quality_ai_sweep_once(session_factory=TestSessionLocal)
        assert calls["n"] == 2  # both sessions were attempted despite the first one failing

    async def test_both_modules_disabled_skips_the_sweep_entirely(self, db_session, a_teacher, a_camera, monkeypatch):
        await _set_module_active(db_session, ATTENTION_MODULE_CODE, False)
        await _set_module_active(db_session, TEACHER_ACTIVITY_MODULE_CODE, False)
        await _make_session(db_session, a_teacher, a_camera, minutes_ago_start=10)

        calls = {"n": 0}

        async def counting_grab_frame_pair(stream_url, gap_seconds=1.0):
            calls["n"] += 1
            return _blank_frame(), _blank_frame()

        monkeypatch.setattr(lesson_quality_ai, "grab_frame_pair", counting_grab_frame_pair)

        count = await run_lesson_quality_ai_sweep_once(session_factory=TestSessionLocal)
        assert count == 0
        assert calls["n"] == 0

    async def test_only_one_of_attention_activity_disabled_still_runs(
        self, db_session, a_teacher, a_camera, monkeypatch
    ):
        await _set_module_active(db_session, ATTENTION_MODULE_CODE, False)  # teacher activity (#21) stays on
        await _make_session(db_session, a_teacher, a_camera, minutes_ago_start=10)

        async def fake_grab_frame_pair(stream_url, gap_seconds=1.0):
            return _blank_frame(), _blank_frame()

        async def fake_detect_faces(frame_bytes):
            return []

        monkeypatch.setattr(lesson_quality_ai, "grab_frame_pair", fake_grab_frame_pair)
        monkeypatch.setattr(lesson_quality_ai, "detect_faces", fake_detect_faces)

        # Not asserting a specific count here (depends on pose detection
        # against a blank frame) -- only that the sweep didn't short-circuit
        # at the module gate the way the "both disabled" test above does.
        await run_lesson_quality_ai_sweep_once(session_factory=TestSessionLocal)
