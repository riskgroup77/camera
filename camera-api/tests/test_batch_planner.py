"""Kunlik tahlil rejasi (app/batch/planner.py) — sof funksiya, baza yo'q."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.batch.planner import (
    KIND_ENTRANCE,
    KIND_GENERAL,
    KIND_LESSON,
    KIND_SMOKING,
    P_ACTIVITY,
    P_ATTENTION,
    P_COAT,
    P_IDENTITY,
    P_SMOKING,
    PHASE_END,
    PHASE_MID,
    PHASE_START,
    Clip,
    LessonSlot,
    build_plan,
    lesson_clips,
)
from app.config import settings

ALL = {6, 7, 8, 9, 10, 15, 19, 21, 22}
W_START = datetime(2026, 10, 5, 2, 0, tzinfo=timezone.utc)  # 07:00 Toshkent
W_END = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)  # 20:00 Toshkent


@dataclass
class Cam:
    name: str = "Kamera"
    room_type: str | None = None
    is_entrance: bool = False
    is_exit: bool = False
    is_perimeter: bool = False
    nvr_id: uuid.UUID | None = field(default_factory=uuid.uuid4)
    nvr_channel: int | None = 1
    excluded_module_codes: list | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)


def test_entrance_camera_is_covered_continuously_in_chunks():
    cam = Cam(name="Asosiy kirish", is_entrance=True)
    plan = build_plan(cameras=[cam], lessons=[], window_start=W_START, window_end=W_END, active_codes=ALL)
    jobs = [job for job in plan.jobs if job.kind == KIND_ENTRANCE]
    assert len(jobs) == 13 * 60 // settings.video_analysis_chunk_minutes
    # Bo'laklar oraliqni bo'shliqsiz, ustma-ust tushmasdan qoplaydi.
    spans = sorted((job.start, job.end) for job in jobs)
    assert spans[0][0] == W_START and spans[-1][1] == W_END
    for (_, end), (start, _) in zip(spans, spans[1:]):
        assert end == start
    clip = jobs[0].clips[0]
    # 07:00 — tig'iz soat (kelish): ko'proq kadr.
    assert clip.fps == settings.video_analysis_entrance_peak_fps
    assert set(clip.purposes) == {P_IDENTITY, P_COAT}
    by_local_hour = {job.start.astimezone(W_START.tzinfo).hour + 5: job.clips[0].fps for job in jobs}
    assert by_local_hour[12] == settings.video_analysis_entrance_fps  # tush payti — siyrakroq
    assert by_local_hour[17] == settings.video_analysis_entrance_peak_fps  # ketish payti


def test_door_detected_by_name_without_flags():
    plan = build_plan(
        cameras=[Cam(name="2-kirish")], lessons=[], window_start=W_START, window_end=W_END, active_codes=ALL
    )
    assert plan.jobs and all(job.kind == KIND_ENTRANCE for job in plan.jobs)


def test_unmapped_camera_is_skipped_with_reason():
    cam = Cam(nvr_id=None, nvr_channel=None, is_entrance=True)
    plan = build_plan(cameras=[cam], lessons=[], window_start=W_START, window_end=W_END, active_codes=ALL)
    assert plan.jobs == []
    assert "NVR" in plan.skipped_cameras[str(cam.id)]


def test_lesson_clips_cover_start_middle_and_end():
    start = datetime(2026, 10, 5, 4, 0, tzinfo=timezone.utc)  # 09:00
    end = start + timedelta(minutes=80)
    clips = lesson_clips(start, end, ALL, W_END)
    phases = {phase: [c for c in clips if c.phase == phase] for phase in (PHASE_START, PHASE_MID, PHASE_END)}
    # Boshlanish: -10..+20 daqiqa har daqiqada.
    assert len(phases[PHASE_START]) == 30
    assert phases[PHASE_START][0].start == start - timedelta(minutes=10)
    # Oxir: oxirgi 15 daqiqa har daqiqada.
    assert len(phases[PHASE_END]) == 15
    assert phases[PHASE_END][-1].start < end
    assert all(c.end <= end for c in clips)
    # O'rta: diqqat va faollik bilan, kamida 2 kadr (harakat o'lchash uchun).
    assert phases[PHASE_MID]
    for clip in phases[PHASE_MID]:
        assert {P_ATTENTION, P_ACTIVITY} <= set(clip.purposes)
        assert clip.frames >= 2
    # Boshlanish va oxir diqqatni o'lchamaydi (kirib-chiqish payti).
    assert all(P_ATTENTION not in c.purposes for c in phases[PHASE_START] + phases[PHASE_END])


def test_lesson_running_past_the_window_has_no_end_phase():
    start = W_END - timedelta(minutes=30)
    clips = lesson_clips(start, start + timedelta(minutes=80), ALL, W_END)
    assert clips
    assert not [c for c in clips if c.phase == PHASE_END]
    assert all(c.end <= W_END for c in clips)


def test_lessons_produce_one_job_each_and_respect_window():
    cam = Cam(room_type="auditoriya")
    lessons = [
        LessonSlot(uuid.uuid4(), cam.id, W_START + timedelta(hours=1), W_START + timedelta(hours=2, minutes=20)),
        LessonSlot(uuid.uuid4(), cam.id, W_START + timedelta(hours=3), W_START + timedelta(hours=4, minutes=20)),
        # Kun oynasidan tashqarida — rejaga kirmaydi.
        LessonSlot(uuid.uuid4(), cam.id, W_END + timedelta(hours=1), W_END + timedelta(hours=2)),
    ]
    plan = build_plan(cameras=[cam], lessons=lessons, window_start=W_START, window_end=W_END, active_codes=ALL)
    assert [job.kind for job in plan.jobs] == [KIND_LESSON, KIND_LESSON]
    assert {job.lesson_session_id for job in plan.jobs} == {lessons[0].id, lessons[1].id}


def test_classroom_without_lessons_is_not_read():
    cam = Cam(room_type="auditoriya")
    plan = build_plan(cameras=[cam], lessons=[], window_start=W_START, window_end=W_END, active_codes=ALL)
    assert plan.jobs == []
    assert "dars" in plan.skipped_cameras[str(cam.id)]


def test_outdoor_and_corridor_cameras_get_smoking_clips():
    cam = Cam(room_type="tashqi")
    plan = build_plan(cameras=[cam], lessons=[], window_start=W_START, window_end=W_END, active_codes=ALL)
    assert plan.jobs and all(job.kind == KIND_SMOKING for job in plan.jobs)
    clip = plan.jobs[0].clips[0]
    assert P_SMOKING in clip.purposes
    assert clip.frames == int(settings.video_analysis_smoking_clip_seconds * settings.video_analysis_smoking_fps)
    per_hour = sum(len(job.clips) for job in plan.jobs) / 13
    assert per_hour == 60 / settings.video_analysis_smoking_step_minutes


def test_smoking_off_turns_outdoor_camera_into_general_sampling():
    cam = Cam(room_type="koridor")
    plan = build_plan(
        cameras=[cam], lessons=[], window_start=W_START, window_end=W_END, active_codes=ALL - {15}
    )
    assert plan.jobs and all(job.kind == KIND_GENERAL for job in plan.jobs)
    assert all(P_SMOKING not in clip.purposes for job in plan.jobs for clip in job.clips)


def test_excluded_module_on_camera_is_respected():
    cam = Cam(room_type="ofis", excluded_module_codes=[10])
    plan = build_plan(cameras=[cam], lessons=[], window_start=W_START, window_end=W_END, active_codes=ALL)
    assert all(P_COAT not in clip.purposes for job in plan.jobs for clip in job.clips)
    assert all(P_IDENTITY in clip.purposes for job in plan.jobs for clip in job.clips)


def test_nothing_active_means_nothing_planned():
    cams = [Cam(is_entrance=True), Cam(room_type="ofis"), Cam(room_type="tashqi")]
    plan = build_plan(cameras=cams, lessons=[], window_start=W_START, window_end=W_END, active_codes=set())
    assert plan.jobs == []


def test_clip_json_round_trip():
    clip = Clip(W_START, W_START + timedelta(seconds=3), 1.0, (P_IDENTITY, P_COAT), PHASE_START)
    assert Clip.from_json(clip.to_json()) == clip
    # Eski (bosqichsiz) format ham o'qiladi.
    legacy = clip.to_json()[:4]
    assert Clip.from_json(legacy).phase is None


def test_plan_budget_is_bounded_for_a_realistic_campus():
    """107 kamera: 6 kirish, 60 auditoriya (4 dars), 10 tashqi, 31 boshqa —
    reja CPU va NVR uchun hisoblanadigan hajmda bo'lishi kerak."""
    cams = [Cam(is_entrance=True) for _ in range(6)]
    cams += [Cam(room_type="auditoriya") for _ in range(60)]
    cams += [Cam(room_type="tashqi") for _ in range(10)]
    cams += [Cam(room_type="ofis") for _ in range(31)]
    lessons = []
    for cam in cams[6:66]:
        for k in range(4):
            begin = W_START + timedelta(hours=1, minutes=90 * k)
            lessons.append(LessonSlot(uuid.uuid4(), cam.id, begin, begin + timedelta(minutes=80)))
    plan = build_plan(cameras=cams, lessons=lessons, window_start=W_START, window_end=W_END, active_codes=ALL)
    lesson_frames = sum(job.frames for job in plan.jobs if job.kind == KIND_LESSON)
    # Bir dars ~ 60-70 klip × 3-6 kadr: butun dars videosining ~5 % i.
    assert lesson_frames / 240 < 300
    assert plan.frames < 600_000


def test_everywhere_mode_checks_every_camera_for_every_person():
    """Kamera turi belgilanmagan (yoki dars xonasi, dars yo'q) kamera ham
    butun oyna davomida chekish/xalat/tanish kliplari bilan ko'riladi."""
    untyped = Cam(name="IPC (192.168.0.12)")
    room = Cam(name="5-xona", room_type="auditoriya")
    busy = Cam(name="7-xona", room_type="auditoriya")
    lesson = LessonSlot(id=uuid.uuid4(), camera_id=busy.id, start=W_START + timedelta(hours=2),
                        end=W_START + timedelta(hours=3, minutes=20))
    off = build_plan(cameras=[untyped, room, busy], lessons=[lesson], window_start=W_START, window_end=W_END,
                     active_codes=ALL, everywhere=False)
    assert {job.camera_id for job in off.jobs if job.kind == KIND_SMOKING} == set()
    assert str(room.id) in off.skipped_cameras

    on = build_plan(cameras=[untyped, room, busy], lessons=[lesson], window_start=W_START, window_end=W_END,
                    active_codes=ALL, everywhere=True)
    everywhere = {job.camera_id for job in on.jobs if job.kind == KIND_SMOKING}
    assert everywhere == {untyped.id, room.id, busy.id}
    assert any(job.kind == KIND_LESSON and job.camera_id == busy.id for job in on.jobs)  # dars o'z kliplari bilan
    assert not on.skipped_cameras
    clips = [clip for job in on.jobs if job.camera_id == untyped.id for clip in job.clips]
    assert set(clips[0].purposes) == {P_SMOKING, P_IDENTITY, P_COAT}
    assert min(c.start for c in clips) == W_START and max(c.end for c in clips) <= W_END


def test_everywhere_mode_keeps_identity_when_smoking_is_off():
    cam = Cam(name="Koridor")
    plan = build_plan(cameras=[cam], lessons=[], window_start=W_START, window_end=W_END,
                      active_codes={6, 7, 10}, everywhere=True)
    assert plan.jobs and all(set(clip.purposes) == {P_IDENTITY, P_COAT} for job in plan.jobs for clip in job.clips)
