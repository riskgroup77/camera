"""Kunlik tahlil rejasi: qaysi kameraning qaysi oralig'i, necha kadr/s,
qaysi kriteriyalar uchun o'qiladi.

Butun kunni har kamerada ko'rish (107 kamera × 13 soat) na NVR'ning
playback imkoniyatiga, na CPU'ga sig'adi. Reja faqat kriteriya javob
beradigan oraliqlarni oladi:

  * kirish/chiqish kameralari — kun oynasi uzluksiz (davomat #6/#7, kelish
    va ketish payti; odam eshikdan 2-3 s da o'tadi);
  * dars xonasi — har dars uchun: boshlanish oynasi har daqiqada (#7, #8,
    #22), o'rtasi har 5 daqiqada (#19, #21), oxiri har daqiqada (#9);
  * tashqi hudud/koridor — uzunroq kliplar (chekish #15 harakatni ko'radi);
  * qolgan kameralar — siyrak kliplar (xalat #10, "binoda bo'lgan").

Reja sof funksiya: kamera va darslar ro'yxatidan vazifalar qaytaradi —
bazaga ham, NVR'ga ham murojaat qilmaydi (tests/test_batch_planner.py).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.config import settings
from app.services.camera_roles import effective_room_type, is_door_camera

# Klip maqsadlari — tahlilchi qaysi modelni ishga tushirishini shundan biladi.
P_IDENTITY = "davomat"
P_COAT = "xalat"
P_ATTENTION = "diqqat"
P_ACTIVITY = "faollik"
P_SMOKING = "chekish"

# Klip qaysi dars bosqichiga tegishli (agregatsiya qamrovni shu bo'yicha tekshiradi).
PHASE_START = "boshlanish"
PHASE_MID = "orta"
PHASE_END = "oxir"

KIND_ENTRANCE = "kirish"
KIND_LESSON = "dars"
KIND_GENERAL = "umumiy"
KIND_SMOKING = "chekish"

CLASSROOM_TYPES = frozenset({"auditoriya", "laboratoriya"})
SMOKING_TYPES = frozenset({"tashqi", "koridor"})

# Modul kodlari -> maqsadlar.
CODE_ATTENDANCE = (6, 7, 8, 9, 22)
CODE_COAT = 10
CODE_SMOKING = 15
CODE_ATTENTION = 19
CODE_ACTIVITY = 21


@dataclass(frozen=True)
class Clip:
    start: datetime
    end: datetime
    fps: float
    purposes: tuple[str, ...]
    phase: str | None = None

    @property
    def frames(self) -> int:
        return max(1, int((self.end - self.start).total_seconds() * self.fps + 0.5))

    def to_json(self) -> list:
        return [self.start.isoformat(), self.end.isoformat(), self.fps, list(self.purposes), self.phase]

    @classmethod
    def from_json(cls, raw: list) -> "Clip":
        start, end, fps, purposes = raw[0], raw[1], raw[2], raw[3]
        phase = raw[4] if len(raw) > 4 else None
        return cls(datetime.fromisoformat(start), datetime.fromisoformat(end), float(fps), tuple(purposes), phase)


@dataclass
class PlannedJob:
    camera_id: uuid.UUID
    kind: str
    clips: list[Clip]
    lesson_session_id: uuid.UUID | None = None

    @property
    def start(self) -> datetime:
        return min(clip.start for clip in self.clips)

    @property
    def end(self) -> datetime:
        return max(clip.end for clip in self.clips)

    @property
    def frames(self) -> int:
        return sum(clip.frames for clip in self.clips)


@dataclass(frozen=True)
class LessonSlot:
    id: uuid.UUID
    camera_id: uuid.UUID
    start: datetime
    end: datetime


@dataclass
class Plan:
    jobs: list[PlannedJob] = field(default_factory=list)
    skipped_cameras: dict[str, str] = field(default_factory=dict)

    @property
    def frames(self) -> int:
        return sum(job.frames for job in self.jobs)


def _purposes(active_codes: set[int], *wanted: str) -> tuple[str, ...]:
    allowed: list[str] = []
    for purpose in wanted:
        if purpose == P_IDENTITY and not any(code in active_codes for code in CODE_ATTENDANCE):
            continue
        if purpose == P_COAT and CODE_COAT not in active_codes:
            continue
        if purpose == P_SMOKING and CODE_SMOKING not in active_codes:
            continue
        if purpose == P_ATTENTION and CODE_ATTENTION not in active_codes:
            continue
        if purpose == P_ACTIVITY and CODE_ACTIVITY not in active_codes:
            continue
        allowed.append(purpose)
    return tuple(allowed)


def _excluded(camera, code: int) -> bool:
    codes = getattr(camera, "excluded_module_codes", None) or []
    return code in codes


def _camera_codes(camera, active_codes: set[int]) -> set[int]:
    return {code for code in active_codes if not _excluded(camera, code)}


def _in_windows(moment: datetime, windows: str) -> bool:
    """`moment` institut soatida "HH:MM-HH:MM,..." oraliqlaridan biridami."""
    from datetime import time as time_type

    from app.timezone import to_local

    clock = to_local(moment).time()
    for part in windows.split(","):
        if "-" not in part:
            continue
        begin, finish = (piece.strip() for piece in part.split("-", 1))
        try:
            if time_type.fromisoformat(begin) <= clock < time_type.fromisoformat(finish):
                return True
        except ValueError:
            continue
    return False


def entrance_fps(moment: datetime) -> float:
    if _in_windows(moment, settings.video_analysis_entrance_peak_windows):
        return settings.video_analysis_entrance_peak_fps
    return settings.video_analysis_entrance_fps


def _ticks(start: datetime, end: datetime, step: timedelta) -> list[datetime]:
    out: list[datetime] = []
    moment = start
    while moment < end:
        out.append(moment)
        moment += step
    return out


def _clip(start: datetime, seconds: float, fps: float, purposes: tuple[str, ...], phase: str | None, limit: datetime) -> Clip | None:
    end = min(start + timedelta(seconds=seconds), limit)
    if end <= start or not purposes:
        return None
    return Clip(start, end, fps, purposes, phase)


def lesson_clips(start: datetime, end: datetime, active_codes: set[int], window_end: datetime) -> list[Clip]:
    """Bitta darsning kliplari (boshlanish, o'rta, oxir)."""
    s = settings
    clip_len, fps = s.video_analysis_clip_seconds, s.video_analysis_clip_fps
    limit = min(end, window_end)
    clips: list[Clip] = []
    start_from = start - timedelta(minutes=s.video_analysis_lesson_start_before_minutes)
    start_to = min(start + timedelta(minutes=s.video_analysis_lesson_start_after_minutes), limit)
    end_from = max(limit - timedelta(minutes=s.video_analysis_lesson_end_minutes), start_to)

    start_purposes = _purposes(active_codes, P_IDENTITY, P_COAT)
    for tick in _ticks(start_from, start_to, timedelta(seconds=s.video_analysis_lesson_start_step_seconds)):
        clip = _clip(tick, clip_len, fps, start_purposes, PHASE_START, limit)
        if clip:
            clips.append(clip)

    mid_purposes = _purposes(active_codes, P_IDENTITY, P_ATTENTION, P_ACTIVITY, P_COAT)
    # Faollik ikki yaqin kadr orasidagi harakatni o'lchaydi — o'rta kliplarda
    # kamida 2 kadr bo'lishi kerak.
    mid_fps = max(fps, 2.0 / clip_len) if P_ACTIVITY in mid_purposes else fps
    step = timedelta(minutes=s.video_analysis_lesson_mid_step_minutes)
    for tick in _ticks(start_to + step / 2, end_from, step):
        clip = _clip(tick, clip_len, mid_fps, mid_purposes, PHASE_MID, limit)
        if clip:
            clips.append(clip)

    if end > window_end:
        # Dars tahlil boshlangandan keyin tugaydi — oxiri yozilmagan, erta
        # ketish o'lchanmaydi (agregatsiya buni "aniqlanmadi" deb biladi).
        return clips
    end_purposes = _purposes(active_codes, P_IDENTITY)
    for tick in _ticks(end_from, limit, timedelta(seconds=s.video_analysis_lesson_end_step_seconds)):
        clip = _clip(tick, clip_len, fps, end_purposes, PHASE_END, limit)
        if clip:
            clips.append(clip)
    return clips


def build_plan(
    *,
    cameras: list,
    lessons: list[LessonSlot],
    window_start: datetime,
    window_end: datetime,
    active_codes: set[int],
    everywhere: bool | None = None,
) -> Plan:
    """`cameras` — Camera obyektlari (yoki shu atributli narsalar):
    id, name, nvr_id, nvr_channel, room_type, is_entrance, is_exit,
    is_perimeter, excluded_module_codes.

    `everywhere` (standart — settings.video_analysis_everywhere): kamera
    turi belgilanmagan bo'lsa ham hamma kriteriyalar hamma kamerada."""
    s = settings
    if everywhere is None:
        everywhere = s.video_analysis_everywhere
    plan = Plan()
    lessons_by_camera: dict[uuid.UUID, list[LessonSlot]] = {}
    for lesson in lessons:
        if lesson.end <= window_start or lesson.start >= window_end:
            continue
        lessons_by_camera.setdefault(lesson.camera_id, []).append(lesson)

    for camera in cameras:
        if camera.nvr_id is None or camera.nvr_channel is None:
            plan.skipped_cameras[str(camera.id)] = "NVR kanaliga bog'lanmagan"
            continue
        codes = _camera_codes(camera, active_codes)
        room_type = effective_room_type(camera)

        if is_door_camera(camera):
            purposes = _purposes(codes, P_IDENTITY, P_COAT)
            if not purposes:
                continue
            chunk = timedelta(minutes=s.video_analysis_chunk_minutes)
            for tick in _ticks(window_start, window_end, chunk):
                end = min(tick + chunk, window_end)
                plan.jobs.append(
                    PlannedJob(
                        camera_id=camera.id,
                        kind=KIND_ENTRANCE,
                        clips=[Clip(tick, end, entrance_fps(tick), purposes)],
                    )
                )
            continue

        camera_lessons = lessons_by_camera.get(camera.id, [])
        if camera_lessons or room_type in CLASSROOM_TYPES:
            for lesson in sorted(camera_lessons, key=lambda item: item.start):
                clips = lesson_clips(lesson.start, lesson.end, codes, window_end)
                clips = [clip for clip in clips if clip.start >= window_start - timedelta(hours=1)]
                if clips:
                    plan.jobs.append(
                        PlannedJob(camera_id=camera.id, kind=KIND_LESSON, clips=clips, lesson_session_id=lesson.id)
                    )
            if not everywhere:
                if not camera_lessons:
                    plan.skipped_cameras[str(camera.id)] = "bugun bu xonada dars yo'q"
                continue

        # "Hamma joyda" rejimi: kamera turidan qat'i nazar har kamerada
        # ko'ringan har bir odam chekish, xalat va tanish bo'yicha
        # tekshiriladi (dars xonasida — darslardan tashqari ham).
        if everywhere or (room_type in SMOKING_TYPES and CODE_SMOKING in codes):
            purposes = _purposes(codes, P_SMOKING, P_IDENTITY, P_COAT)
            if not purposes:
                continue
            step = timedelta(minutes=max(1, s.video_analysis_smoking_step_minutes))
            hour = timedelta(hours=1)
            for block in _ticks(window_start, window_end, hour):
                block_end = min(block + hour, window_end)
                clips = [
                    clip
                    for tick in _ticks(block, block_end, step)
                    if (
                        clip := _clip(
                            tick, s.video_analysis_smoking_clip_seconds, s.video_analysis_smoking_fps, purposes, None, block_end
                        )
                    )
                ]
                if clips:
                    plan.jobs.append(PlannedJob(camera_id=camera.id, kind=KIND_SMOKING, clips=clips))
            continue

        if s.video_analysis_general_step_minutes <= 0:
            continue
        purposes = _purposes(codes, P_IDENTITY, P_COAT)
        if not purposes:
            continue
        step = timedelta(minutes=s.video_analysis_general_step_minutes)
        block_len = timedelta(hours=2)
        for block in _ticks(window_start, window_end, block_len):
            block_end = min(block + block_len, window_end)
            clips = [
                clip
                for tick in _ticks(block, block_end, step)
                if (
                    clip := _clip(
                        tick, s.video_analysis_clip_seconds, s.video_analysis_clip_fps, purposes, None, block_end
                    )
                )
            ]
            if clips:
                plan.jobs.append(PlannedJob(camera_id=camera.id, kind=KIND_GENERAL, clips=clips))
    return plan
