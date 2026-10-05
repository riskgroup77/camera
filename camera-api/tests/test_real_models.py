"""Haqiqiy modellar bilan: InsightFace (yuz), YOLO (odam), ffmpeg (video).

Soxta modellar mantiqni tekshiradi; bu fayl esa butun zanjir HAQIQIY
og'irliklar bilan ishlashini ko'rsatadi: ro'yxatga olingan suratdan
olingan vektor CCTV o'lchamidagi (960 px, JPEG/H.264 siqilgan) kadrdagi
yuz bilan to'g'ri odamga moslanadimi, kelish vaqti to'g'ri chiqadimi,
oq xalat haqiqiy kiyimlardan ajraladimi.

Sinov surati — InsightFace bilan keladigan t1.jpg (6 kishi). Modellar
birinchi ishga tushishda yuklanadi; ffmpeg yo'q bo'lsa test o'tkazib
yuboriladi."""

import json
import shutil
import subprocess
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest
from sqlalchemy import select

pytestmark = [
    pytest.mark.daily_mode,
    pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg yo'q"),
]

def t1_path() -> Path:
    import insightface

    return Path(insightface.__file__).parent / "data" / "images" / "t1.jpg"


async def _people():
    """t1.jpg dagi 6 yuz (chapdan o'ngga): ro'yxatga olish vektori va ramka."""
    from app.services.face_recognition import detect_faces

    faces = await detect_faces(t1_path().read_bytes(), min_face_px=0)
    faces = sorted(faces, key=lambda f: float(f.bbox[0]))
    assert len(faces) == 6
    return [(np.asarray(f.embedding, dtype=np.float64), [float(v) for v in f.bbox]) for f in faces]


def _hide(image: np.ndarray, box) -> None:
    """Odamni kadrdan "olib tashlash": yuzi va tanasi ustiga devor rangi."""
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    left, right = int(max(0, x1 - 0.9 * w)), int(min(image.shape[1], x2 + 0.9 * w))
    top = int(max(0, y1 - 0.6 * h))
    image[top:, left:right] = (90, 120, 150)


def _paint_coat(image: np.ndarray, box) -> None:
    """Odamga oq xalat: yuz ostidagi tana sohasini oqartirish (soya bilan)."""
    x1, y1, x2, y2 = (int(v) for v in box)
    w, h = x2 - x1, y2 - y1
    left, right = max(0, x1 - int(0.9 * w)), min(image.shape[1], x2 + int(0.9 * w))
    top, bottom = y2 + int(0.3 * h), min(image.shape[0], y2 + int(2.2 * h))
    noise = np.random.default_rng(0).integers(0, 25, (bottom - top, right - left, 3))
    image[top:bottom, left:right] = (235 - noise).clip(0, 255).astype(np.uint8)


def _make_video(path: Path, frames: list[np.ndarray]) -> None:
    """1 kadr/s rasmlar -> 10 kadr/s H.264 video (NVR eksporti kabi)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    work = path.parent / "_frames"
    work.mkdir(exist_ok=True)
    for i, frame in enumerate(frames):
        cv2.imwrite(str(work / f"f{i:03d}.png"), frame)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", "1", "-i", str(work / "f%03d.png"),
         "-vf", "fps=10,format=yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", str(path)],
        check=True,
    )
    shutil.rmtree(work)


def _scene(people, *, hidden: set[int], coat: int | None) -> np.ndarray:
    image = cv2.imread(str(t1_path()))
    if coat is not None:
        _paint_coat(image, people[coat][1])
    for index in hidden:
        _hide(image, people[index][1])
    # CCTV o'lchami: 960 px (yuzlar ~50 px).
    return cv2.resize(image, (960, int(image.shape[0] * 960 / image.shape[1])), interpolation=cv2.INTER_AREA)


async def test_real_pipeline_recognizes_people_and_arrival_times(tmp_path):
    from app.batch.analyzer import Analyzer, JobContext
    from app.batch.coat import observation_vote
    from app.batch.planner import P_ATTENTION, P_COAT, P_IDENTITY, Clip
    from app.services.face_matching import CandidateMatrix
    from app.services.nvr.sources import FolderSource
    from app.timezone import INSTITUTE_TZ

    people = await _people()
    # Ro'yxatda 6 kishi + 300 boshqa (tasodifiy) odam — moslik "eng yaqini"
    # bo'lgani uchun emas, haqiqatan o'xshagani uchun chiqishi kerak.
    rng = np.random.default_rng(1)
    distractors = rng.normal(size=(300, 512))
    matrix = np.vstack([np.stack([e for e, _ in people]), distractors])
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    ids = [f"P{i}" for i in range(6)] + [f"X{i}" for i in range(300)]
    candidates = CandidateMatrix(ids=ids, matrix=matrix)

    # 0-4 s: o'ngdagi uch kishi hali yo'q; 5-9 s: hamma bor. P2 — oq xalatda.
    frames = [_scene(people, hidden={3, 4, 5}, coat=2)] * 5 + [_scene(people, hidden=set(), coat=2)] * 5
    _make_video(tmp_path / "1" / "20261005_080000.mp4", frames)

    start = datetime(2026, 10, 5, 8, 0, tzinfo=INSTITUTE_TZ)
    clip = Clip(start, start + timedelta(seconds=10), 1.0, (P_IDENTITY, P_COAT, P_ATTENTION))
    context = JobContext(job_id=None, day=start.date(), camera_id=None, camera_name="kirish", clips=[clip],
                         candidates=candidates, evidence_registry=set())

    class NoUpload(Analyzer):
        async def upload(self, data, name):
            return "dalil.jpg"

    outcome = await NoUpload().run(context, FolderSource(str(tmp_path), 1))
    assert outcome.covered and outcome.covered[0][1] == 10

    first_seen: dict[str, datetime] = {}
    best: dict[str, float] = {}
    votes: dict[str, list] = {}
    for obs in outcome.observations:
        assert not obs.person_id.startswith("X"), f"boshqa odamga moslandi: {obs.person_id}"
        first_seen[obs.person_id] = min(first_seen.get(obs.person_id, obs.seen_at), obs.seen_at)
        best[obs.person_id] = max(best.get(obs.person_id, 0.0), obs.similarity)
        votes.setdefault(obs.person_id, []).append(observation_vote(obs.coat_white_frames, obs.coat_frames))
    assert set(first_seen) == {f"P{i}" for i in range(6)}
    assert all(sim >= 0.5 for sim in best.values()), best
    for i in range(3):
        assert first_seen[f"P{i}"] == start
    for i in range(3, 6):
        assert first_seen[f"P{i}"] == start + timedelta(seconds=5)
    # Oq xalat: bo'yalgan odam — oq, haqiqiy kiyimlar (qora, qizil, kulrang) — oq emas.
    assert True in votes["P2"] and False not in votes["P2"]
    for person in ("P0", "P3", "P4", "P5"):
        assert True not in votes[person], (person, votes[person])


async def test_real_models_full_day_into_database(tmp_path, db_session, seeded):
    """NVR eksport papkasi -> haqiqiy tahlil -> agregatsiya -> davomat."""
    from app.jobs import video_analysis as va
    from app.models import AttendanceRecord, Camera, DailyPersonCriteria, NvrDevice, StudentStaff
    from app.timezone import INSTITUTE_TZ, business_today
    from tests.conftest import TestSessionLocal

    day = business_today() - timedelta(days=1)
    while day.isoweekday() == 7:
        day -= timedelta(days=1)
    people = await _people()
    stamp = datetime.combine(day, time(7, 58, 0)).strftime("%Y%m%d_%H%M%S")
    # 07:58:00 dan: 0-4 s — chapdagi uchtasi, 5-9 s — hammasi (o'ngdagilar
    # 07:58:05 da kirdi).
    _make_video(tmp_path / "1" / f"{stamp}.mp4",
                [_scene(people, hidden={3, 4, 5}, coat=None)] * 5 + [_scene(people, hidden=set(), coat=None)] * 5)

    nvr = NvrDevice(name="Eksport", kind="fayl", base_path=str(tmp_path), max_streams=1)
    db_session.add(nvr)
    await db_session.flush()
    db_session.add(Camera(name="Asosiy kirish", ip="10.0.0.1", zone="A", resolution="HD", status="faol",
                          is_entrance=True, nvr_id=nvr.id, nvr_channel=1))
    before = datetime.combine(day - timedelta(days=10), time(9), tzinfo=timezone.utc)
    rows = []
    for i, (embedding, _box) in enumerate(people):
        row = StudentStaff(full_name=f"Xodim {i}", type="xodim", group_or_position="Kafedra",
                           biometrics_status="tasdiqlangan", biometric_embedding=json.dumps(embedding.tolist()),
                           biometrics_confirmed_at=before)
        rows.append(row)
    db_session.add_all(rows)
    await db_session.commit()

    async with TestSessionLocal() as db:
        run = await va.create_run(db, day, now=datetime.combine(day + timedelta(days=1), time(9), tzinfo=timezone.utc))
    result = await va.RunExecutor(run.id, TestSessionLocal).execute()
    assert result.status == "tugadi", result.error

    records = {
        r.student_staff_id: r
        for r in (await db_session.execute(select(AttendanceRecord).where(AttendanceRecord.date == day))).scalars()
    }
    assert set(records) == {row.id for row in rows}
    for i, row in enumerate(rows):
        record = records[row.id]
        expected = time(7, 58, 0) if i < 3 else time(7, 58, 5)
        assert record.status == "keldi" and record.check_in == expected, (i, record.check_in)
    daily = (await db_session.execute(select(DailyPersonCriteria).where(DailyPersonCriteria.day == day))).scalars().all()
    assert len(daily) == 6 and all(d.sightings >= 1 for d in daily)
