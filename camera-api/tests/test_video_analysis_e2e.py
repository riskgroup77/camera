"""Uchidan-uchiga: haqiqiy video fayllar (ffmpeg bilan yaratilgan "NVR
eksporti") -> FolderSource -> haqiqiy Analyzer (izlar, harakat darvozasi,
vaqt belgilari) -> baza -> agregatsiya.

Yuz modeli o'rniga kadrdagi rangli belgi o'qiladi: qizil kvadrat — odam
P1 kadrda, ko'k — P2. Shunday qilib kadr vaqti va tahlil zanjirining
to'g'riligi haqiqiy dekodlash bilan tekshiriladi."""

import json
import shutil
import subprocess
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from sqlalchemy import select

from app.batch.analyzer import Analyzer
from app.jobs import video_analysis as va
from app.models import AttendanceRecord, Camera, DailyPersonCriteria, NvrDevice, StudentStaff, VideoAnalysisJob
from app.timezone import INSTITUTE_TZ, business_today
from tests.conftest import TestSessionLocal

pytestmark = [
    pytest.mark.daily_mode,
    pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg yo'q"),
]

RNG = np.random.default_rng(3)


def unit(v):
    return v / np.linalg.norm(v)


P1, P2 = unit(RNG.normal(size=512)), unit(RNG.normal(size=512))


def past_work_day():
    day = business_today() - timedelta(days=1)
    while day.isoweekday() == 7:
        day -= timedelta(days=1)
    return day


DAY = past_work_day()


def make_clip(path: Path, seconds: int, marks: list[tuple[float, float, str]]) -> None:
    """Kulrang fon, belgilangan oraliqlarda rangli kvadrat (odam)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    filters = "format=yuv420p"
    for begin, end, color in marks:
        filters += f",drawbox=x=40:y=40:w=80:h=80:color={color}:t=fill:enable='between(t,{begin},{end})'"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"color=c=gray:size=640x360:rate=10:duration={seconds}", "-vf", filters,
         "-c:v", "libx264", "-preset", "ultrafast", "-g", "10", str(path)],
        check=True,
    )


class MarkerAnalyzer(Analyzer):
    """Yuz modeli o'rniga kadrdagi belgi rangi."""

    def __init__(self):
        self.calls = 0

    async def faces(self, data):
        self.calls += 1
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        b, g, r = (int(v) for v in image[80, 80])
        rng = np.random.default_rng(self.calls)
        if r > 180 and g < 90 and b < 90:
            identity = P1
        elif b > 180 and r < 90 and g < 90:
            identity = P2
        else:
            return []
        emb = unit(identity + 0.3 * unit(rng.normal(size=512)))
        return [SimpleNamespace(embedding=emb, landmarks_68=None, bbox=np.array([40.0, 40.0, 120.0, 120.0]),
                                det_score=0.9, yaw=0.0)]

    async def objects(self, data, class_ids):
        return []

    async def upload(self, data, name):
        return None


def stamp(hh, mm, ss=0) -> str:
    return datetime.combine(DAY, time(hh, mm, ss)).strftime("%Y%m%d_%H%M%S")


async def test_end_to_end_from_video_files(tmp_path, db_session, seeded):
    door = tmp_path / "1"
    # 07:59:50 dan 60 s: P1 08:00:00-08:00:04 da o'tadi, P2 08:20:00 da.
    make_clip(door / f"{stamp(7, 59, 50)}.mp4", 60, [(10, 14, "red")])
    make_clip(door / f"{stamp(8, 19, 55)}.mp4", 20, [(5, 8, "blue")])
    # Kechqurun: P1 17:30:00 da chiqadi.
    make_clip(door / f"{stamp(17, 29, 50)}.mp4", 30, [(10, 13, "red")])

    nvr = NvrDevice(name="Eksport", kind="fayl", base_path=str(tmp_path), max_streams=2)
    db_session.add(nvr)
    await db_session.flush()
    db_session.add(Camera(name="Asosiy kirish", ip="10.0.0.1", zone="A", resolution="HD", status="faol",
                          is_entrance=True, nvr_id=nvr.id, nvr_channel=1))
    before = datetime.combine(DAY - timedelta(days=10), time(9), tzinfo=timezone.utc)
    p1 = StudentStaff(full_name="Birinchi Xodim", type="xodim", group_or_position="Kafedra",
                      biometrics_status="tasdiqlangan", biometric_embedding=json.dumps(P1.tolist()),
                      biometrics_confirmed_at=before)
    p2 = StudentStaff(full_name="Ikkinchi Xodim", type="xodim", group_or_position="Kafedra",
                      biometrics_status="tasdiqlangan", biometric_embedding=json.dumps(P2.tolist()),
                      biometrics_confirmed_at=before)
    db_session.add_all([p1, p2])
    await db_session.commit()

    async with TestSessionLocal() as db:
        run = await va.create_run(db, DAY, now=datetime.combine(DAY + timedelta(days=1), time(9), tzinfo=timezone.utc))
    analyzer = MarkerAnalyzer()
    executor = va.RunExecutor(run.id, TestSessionLocal, analyzer=analyzer)
    result = await executor.execute()
    assert result.status == "tugadi", result.error

    jobs = (await db_session.execute(select(VideoAnalysisJob).where(VideoAnalysisJob.run_id == run.id))).scalars().all()
    covered = [job for job in jobs if job.status == "tugadi"]
    no_video = [job for job in jobs if job.status == "yozuv_yoq"]
    # Faqat yozuv bor yarim soatliklar o'qildi: 07:30, 08:00, 17:00, 17:30 bo'laklari.
    assert len(covered) == 4 and len(no_video) == len(jobs) - 4
    # Harakat darvozasi: kulrang bo'sh kadrlarning ko'pi tahlil qilinmadi.
    frames = sum(job.frames for job in jobs)
    assert analyzer.calls < frames * 0.6

    records = {
        r.student_staff_id: r
        for r in (await db_session.execute(select(AttendanceRecord).where(AttendanceRecord.date == DAY))).scalars()
    }
    first = records[p1.id]
    assert first.status == "keldi"
    # Kelish 08:00:00 ±1 s (kalit kadr va fps bo'yicha), ketish 17:30 atrofida.
    arrival = datetime.combine(DAY, first.check_in)
    assert abs((arrival - datetime.combine(DAY, time(8, 0))).total_seconds()) <= 1.0
    leave = datetime.combine(DAY, first.check_out)
    assert abs((leave - datetime.combine(DAY, time(17, 30, 3))).total_seconds()) <= 2.0
    second = records[p2.id]
    assert second.status == "kech_keldi"
    assert abs((datetime.combine(DAY, second.check_in) - datetime.combine(DAY, time(8, 20))).total_seconds()) <= 1.0

    daily = {
        r.student_staff_id: r
        for r in (await db_session.execute(select(DailyPersonCriteria).where(DailyPersonCriteria.day == DAY))).scalars()
    }
    assert daily[p2.id].late_minutes == 20
    assert daily[p1.id].early_leave == "vaqtida"
