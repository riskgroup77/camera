"""Vazifa tahlilchisi (app/batch/analyzer.py) — soxta modellar va soxta
yozuv manbai bilan. Rasmlar haqiqiy JPEG (xalat rangi tekshiriladi)."""

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import cv2
import numpy as np

from app.batch.analyzer import Analyzer, JobContext, phone_near
from app.batch.planner import P_ACTIVITY, P_ATTENTION, P_COAT, P_IDENTITY, P_SMOKING, Clip
from app.services.face_matching import CandidateMatrix
from app.services.nvr.sources import Frame, PlaybackSource, VideoReadError
from app.services.nvr.isapi import RecordingSpan
from app.services.object_detection import DetectedObject
from app.services.pose_detection import (
    LEFT_ELBOW,
    LEFT_SHOULDER,
    LEFT_WRIST,
    NOSE,
    RIGHT_ELBOW,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
    PoseLandmarks,
)

T0 = datetime(2026, 10, 5, 4, 0, tzinfo=timezone.utc)
RNG = np.random.default_rng(11)


def unit(v):
    return v / np.linalg.norm(v)


A, B, TEACHER = (unit(RNG.normal(size=512)) for _ in range(3))
CANDIDATES = CandidateMatrix(ids=["A", "B", "T"], matrix=np.stack([A, B, TEACHER]))


def noisy(identity, noise, seed):
    rng = np.random.default_rng(seed)
    return unit(identity + noise * unit(rng.normal(size=512)))


def jpeg(torso=(240, 240, 240), seed=0, size=(720, 1280)) -> bytes:
    rng = np.random.default_rng(seed)
    image = np.full((size[0], size[1], 3), 90, np.float32)
    cv2.rectangle(image, (560, 280), (700, 520), torso, -1)
    cv2.rectangle(image, (600, 200), (660, 270), (120, 150, 200), -1)
    image += rng.normal(0, 4, image.shape)
    ok, buffer = cv2.imencode(".jpg", np.clip(image, 0, 255).astype(np.uint8))
    return buffer.tobytes()


def face(emb, box=(600, 200, 660, 270), yaw=0.05, det=0.85):
    return SimpleNamespace(embedding=emb, landmarks_68=None, bbox=np.array(box, float), det_score=det, yaw=yaw)


class FakeSource(PlaybackSource):
    def __init__(self, frames: dict[int, list[bytes]], spans=None, fail: set[int] | None = None):
        self.frames, self.spans, self.fail = frames, spans, fail or set()
        self.calls = []

    async def available(self, start, end):
        return self.spans

    async def clip(self, start, end, fps, *, max_side, timeout, should_stop=None):
        index = len(self.calls)
        self.calls.append((start, end, fps))
        if index in self.fail:
            raise VideoReadError("uzildi")
        for i, data in enumerate(self.frames.get(index, [])):
            if should_stop is not None and should_stop():
                return
            yield Frame(at=start + timedelta(seconds=i / fps), jpeg=data)


class FakeAnalyzer(Analyzer):
    def __init__(self, faces=None, objects=None, poses=None):
        self.face_map = faces or {}
        self.object_map = objects or {}
        self.pose_map = poses or {}
        self.face_calls = 0
        self.uploads = []

    async def faces(self, data):
        self.face_calls += 1
        return self.face_map.get(data, [])

    async def objects(self, data, class_ids):
        return [o for o in self.object_map.get(data, []) if o.class_id in class_ids]

    async def poses(self, data):
        if data in self.pose_map:
            return self.pose_map[data]
        # Kesim (o'qituvchi atrofi) — navbatdagi tayyor poza.
        queue = self.pose_map.get("navbat", [])
        return [queue.pop(0)] if queue else []

    async def cigarettes(self, data):
        return []

    async def upload(self, data, name):
        self.uploads.append(name)
        return f"key-{len(self.uploads)}"


def context(clips, teacher=None, registry=None):
    return JobContext(
        job_id=uuid.uuid4(), day=date(2026, 10, 5), camera_id=uuid.uuid4(), camera_name="kamera",
        clips=clips, candidates=CANDIDATES, teacher_id=teacher, evidence_registry=registry,
    )


def clip(seconds=3, fps=1.0, purposes=(P_IDENTITY,), offset=0, phase=None):
    start = T0 + timedelta(seconds=offset)
    return Clip(start, start + timedelta(seconds=seconds), fps, tuple(purposes), phase)


async def test_track_fusion_recognizes_noisy_small_faces():
    frames = [jpeg(seed=i) for i in range(4)]
    # Kichik CCTV yuzi: umumiy siljish (yorug'lik, burchak — kadrlar uchun bir
    # xil) + har kadrning o'z shovqini. Har kadr alohida chegara (0,50)
    # ostida, birlashtirilgani — ustida.
    shared = unit(np.random.default_rng(5).normal(size=512))
    embeddings = [
        unit(A + shared + 1.5 * unit(np.random.default_rng(300 + i).normal(size=512))) for i in range(4)
    ]
    singles = [float(np.dot(e, A)) for e in embeddings]
    analyzer = FakeAnalyzer(faces={f: [face(e)] for f, e in zip(frames, embeddings)})
    outcome = await analyzer.run(context([clip(4)]), FakeSource({0: frames}))
    assert max(singles) < 0.5
    assert len(outcome.observations) == 1
    obs = outcome.observations[0]
    assert obs.person_id == "A" and obs.frames == 4 and obs.similarity >= 0.5
    assert outcome.covered == [[0, 4, 4]]


async def test_unknown_face_is_not_stored():
    frames = [jpeg(seed=1)]
    stranger = unit(RNG.normal(size=512))
    outcome = await FakeAnalyzer(faces={frames[0]: [face(stranger)]}).run(context([clip(1)]), FakeSource({0: frames}))
    assert outcome.observations == [] and outcome.faces == 1


async def test_one_person_cannot_be_in_two_places_at_once():
    frames = [jpeg(seed=i) for i in range(2)]
    faces = {
        f: [face(noisy(A, 0.3, 10 + i), box=(100, 100, 160, 170)), face(noisy(A, 0.9, 20 + i), box=(900, 100, 960, 170))]
        for i, f in enumerate(frames)
    }
    outcome = await FakeAnalyzer(faces=faces).run(context([clip(2)]), FakeSource({0: frames}))
    assert [o.person_id for o in outcome.observations] == ["A"]


async def test_attention_signals_phone_and_frontal():
    frames = [jpeg(seed=i) for i in range(3)]
    phone = DetectedObject(67, "cell phone", 0.8, (620, 330, 650, 380))  # yuz ostida, qo'lda
    faces = {
        frames[0]: [face(noisy(A, 0.2, 1), yaw=0.05)],
        frames[1]: [face(noisy(A, 0.2, 2), yaw=0.45)],
        frames[2]: [face(noisy(A, 0.2, 3), yaw=0.05)],
    }
    analyzer = FakeAnalyzer(faces=faces, objects={frames[2]: [phone]})
    outcome = await analyzer.run(context([clip(3, purposes=(P_IDENTITY, P_ATTENTION))]), FakeSource({0: frames}))
    obs = outcome.observations[0]
    assert obs.frames == 3
    assert obs.phone_frames == 1
    assert obs.frontal_frames == 1  # 1-kadr; 3-kadr qaragan, lekin telefon bilan


def test_phone_near_is_per_student():
    face_box = (600, 200, 660, 270)
    assert phone_near(face_box, [SimpleNamespace(bbox=(620, 330, 650, 380))])
    assert not phone_near(face_box, [SimpleNamespace(bbox=(1100, 300, 1130, 350))])  # boshqa partada
    assert not phone_near(face_box, [])


async def test_coat_samples_and_single_evidence_per_person_per_day():
    white = [jpeg(seed=i) for i in range(2)]
    dark = [jpeg(torso=(60, 40, 30), seed=10 + i) for i in range(2)]
    person = DetectedObject(0, "person", 0.9, (550, 180, 710, 540))
    faces = {f: [face(noisy(A, 0.2, i))] for i, f in enumerate(white)}
    faces.update({f: [face(noisy(B, 0.2, 50 + i))] for i, f in enumerate(dark)})
    objects = {f: [person] for f in white + dark}
    registry: set = set()
    analyzer = FakeAnalyzer(faces=faces, objects=objects)
    clips = [clip(2, purposes=(P_IDENTITY, P_COAT)), clip(2, purposes=(P_IDENTITY, P_COAT), offset=60)]
    outcome = await analyzer.run(context(clips, registry=registry), FakeSource({0: white, 1: dark}))
    by_person = {o.person_id: o for o in outcome.observations}
    assert by_person["A"].coat_frames == 2 and by_person["A"].coat_white_frames == 2
    assert by_person["B"].coat_frames == 2 and by_person["B"].coat_white_frames == 0
    assert by_person["B"].evidence_key is not None and by_person["A"].evidence_key is None
    assert registry == {(date(2026, 10, 5), "B")}
    # Ikkinchi vazifa: B uchun dalil qayta saqlanmaydi.
    again = await FakeAnalyzer(faces=faces, objects=objects).run(
        context([clips[1]], registry=registry), FakeSource({0: dark})
    )
    assert again.observations[0].evidence_key is None


async def test_missing_recording_and_read_errors_are_not_coverage():
    frames = [jpeg(seed=1)]
    faces = {frames[0]: [face(noisy(A, 0.2, 1))]}
    clips = [clip(1, offset=0), clip(1, offset=600), clip(1, offset=1200)]
    spans = [RecordingSpan(T0 - timedelta(minutes=1), T0 + timedelta(minutes=5)),
             RecordingSpan(T0 + timedelta(minutes=19), T0 + timedelta(minutes=30))]
    source = FakeSource({0: frames, 1: frames}, spans=spans, fail={1})
    outcome = await FakeAnalyzer(faces=faces).run(context(clips), source)
    # 2-klip (10-daqiqa) yozuvsiz — o'qilmaydi ham; 3-klip o'qishda uzildi.
    assert len(source.calls) == 2
    assert [c[0] for c in outcome.covered] == [0]
    assert outcome.errors == ["uzildi"]


async def test_long_clip_skips_static_frames():
    empty = jpeg(seed=0)
    frames = [empty] * 40  # 20 s harakatsiz bo'sh kadr, 2 kadr/s
    analyzer = FakeAnalyzer()
    clip_long = Clip(T0, T0 + timedelta(seconds=200), 0.2, (P_IDENTITY,))  # >120 s — uzun klip
    await analyzer.run(context([clip_long]), FakeSource({0: frames}))
    # Har MOTION_FORCE_SECONDS (10 s) da bittadan: 40 kadr × 5 s = 200 s -> ~20.
    assert analyzer.face_calls <= 21
    assert analyzer.face_calls < len(frames)


def pose_at(cx, hand_up=False, shift=0.0):
    points = np.zeros((33, 4))
    x = cx + shift
    points[NOSE] = (x, 0.32, 0, 0.9)
    points[LEFT_SHOULDER] = (x - 0.05, 0.45, 0, 0.9)
    points[RIGHT_SHOULDER] = (x + 0.05, 0.45, 0, 0.9)
    points[LEFT_ELBOW] = (x - 0.07, 0.57, 0, 0.9)
    points[RIGHT_ELBOW] = (x + 0.06, 0.53, 0, 0.9)
    points[LEFT_WRIST] = (x - 0.08, 0.70, 0, 0.9)
    mouth_y = (0.32 * 720 + 0.18 * 0.10 * 1280) / 720
    points[RIGHT_WRIST] = (x + 0.01, mouth_y, 0, 0.9) if hand_up else (x + 0.08, 0.70, 0, 0.9)
    return PoseLandmarks(points=points)


def crop_pose(shift=0.0):
    """O'qituvchi kesimidagi poza: yuz (610,200,670,260) atrofidagi kesim
    460..820 × 140..680 (360×540) — burun (0,5; 0,167), yelkalar ±0,1."""
    points = np.zeros((33, 4))
    x = 0.5 + shift
    points[NOSE] = (x, 0.167, 0, 0.9)
    points[LEFT_SHOULDER] = (x - 0.1, 0.30, 0, 0.9)
    points[RIGHT_SHOULDER] = (x + 0.1, 0.30, 0, 0.9)
    points[LEFT_WRIST] = (x - 0.15, 0.6, 0, 0.9)
    points[RIGHT_WRIST] = (x + 0.15, 0.6, 0, 0.9)
    return PoseLandmarks(points=points)


async def test_teacher_activity_measured_from_pose_movement():
    frames = [jpeg(seed=i) for i in range(2)]
    face_box = (610, 200, 670, 260)
    faces = {f: [face(noisy(TEACHER, 0.2, i), box=face_box)] for i, f in enumerate(frames)}
    # Yarim yelka kengligi siljish (0,05 × 360 = 18 px; yelka 72 px) -> 50.
    analyzer = FakeAnalyzer(faces=faces, poses={"navbat": [crop_pose(), crop_pose(shift=0.05)]})
    clips = [clip(2, fps=1.0, purposes=(P_IDENTITY, P_ACTIVITY, P_ATTENTION))]
    outcome = await analyzer.run(context(clips, teacher="T"), FakeSource({0: frames}))
    teacher = next(o for o in outcome.observations if o.person_id == "T")
    assert teacher.movement is not None and 40 <= teacher.movement <= 60


async def test_teacher_pose_found_even_in_a_crowded_room():
    """Kadrda poza modeli o'qituvchini qaytarmasa ham (ko'p talaba), kesimda topiladi."""
    frames = [jpeg(seed=i) for i in range(2)]
    face_box = (610, 200, 670, 260)
    faces = {f: [face(noisy(TEACHER, 0.2, i), box=face_box)] for i, f in enumerate(frames)}
    # Butun kadr uchun — faqat boshqa odamlarning pozalari.
    others = {f: [pose_at(0.1), pose_at(0.9)] for f in frames}
    analyzer = FakeAnalyzer(faces=faces, poses={**others, "navbat": [crop_pose(), crop_pose(shift=0.02)]})
    clips = [clip(2, fps=1.0, purposes=(P_IDENTITY, P_ACTIVITY))]
    outcome = await analyzer.run(context(clips, teacher="T"), FakeSource({0: frames}))
    assert next(o for o in outcome.observations if o.person_id == "T").movement == 20.0


async def test_smoking_candidate_attributed_to_recognized_person():
    n = 40
    frames = [jpeg(seed=100 + i) for i in range(n)]
    up = {4, 5, 6, 16, 17, 18, 30, 31}
    poses = {f: [pose_at(0.5, hand_up=i in up)] for i, f in enumerate(frames)}
    face_box = (610, 200, 670, 260)
    faces = {f: [face(noisy(B, 0.2, i), box=face_box)] for i, f in enumerate(frames)}
    person = DetectedObject(0, "person", 0.9, (500, 150, 780, 700))
    objects = {f: [person] for f in frames}
    analyzer = FakeAnalyzer(faces=faces, objects=objects, poses=poses)
    clips = [clip(20, fps=2.0, purposes=(P_SMOKING, P_IDENTITY))]
    outcome = await analyzer.run(context(clips), FakeSource({0: frames}))
    assert len(outcome.smoking) == 1
    item = outcome.smoking[0]
    assert item["person_id"] == "B" and item["episodes"] == 3 and item["snapshot_key"]
    # Yuz faqat har 4-kadrda aniqlanadi.
    assert analyzer.face_calls == n // 4


async def test_smoking_skipped_when_nobody_in_frame():
    frames = [jpeg(seed=200 + i) for i in range(10)]
    analyzer = FakeAnalyzer(poses={f: [pose_at(0.5, hand_up=True)] for f in frames})
    outcome = await analyzer.run(context([clip(5, fps=2.0, purposes=(P_SMOKING,))]), FakeSource({0: frames}))
    assert outcome.smoking == []


async def test_should_stop_interrupts_job():
    frames = [jpeg(seed=i) for i in range(5)]
    analyzer = FakeAnalyzer(faces={f: [face(noisy(A, 0.2, i))] for i, f in enumerate(frames)})
    outcome = await analyzer.run(context([clip(5), clip(5, offset=60)]), FakeSource({0: frames, 1: frames}),
                                 should_stop=lambda: True)
    assert outcome.frames == 0 and outcome.observations == []


def test_mixed_track_of_two_people_is_rejected():
    """Iz ikki odamni aralashtirgan bo'lsa (birlashtirilgan vektor ikkalasiga
    ham o'xshamaydi), u hech kimga moslanmaydi — noto'g'ri odamga davomat yozilmaydi."""
    from app.batch.analyzer import JobOutcome
    from app.batch.tracking import FaceSample, Track

    def sample(i, emb):
        return FaceSample(at=T0 + timedelta(seconds=i), frame_index=i, bbox=(0, 0, 60, 70), embedding=emb,
                          quality=0.8, face_px=70)

    mixed = Track(samples=[sample(0, A), sample(1, B), sample(2, A), sample(3, B)])
    clean = Track(samples=[sample(0, noisy(A, 0.2, 1)), sample(1, noisy(A, 0.2, 2))])
    outcome = JobOutcome()
    kept = FakeAnalyzer()._finalize(context([clip(4)]), 0, [mixed, clean], outcome)
    assert [obs.person_id for _t, obs in kept] == ["A"]
    assert len(outcome.observations) == 1 and outcome.observations[0].frames == 2
