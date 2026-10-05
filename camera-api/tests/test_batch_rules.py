"""Kriteriyalar qoidalari (app/batch/rules.py) — sof funksiyalar.

Har kriteriya uchun: odatdagi holat, chegara holatlari va eng muhimi —
dalil yetmaganda ayblov chiqarilmasligi."""

from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.batch.planner import PHASE_END, PHASE_MID, PHASE_START, Clip, lesson_clips
from app.batch.rules import (
    JobInfo,
    LessonInfo,
    Obs,
    attention_score,
    coat_votes,
    day_attendance,
    is_strong,
    is_weak,
    lesson_result,
    presence_visits,
    reliable,
    smoking_incidents,
)
from app.services.attendance_policy import EARLY_NO, EARLY_UNKNOWN, EARLY_YES, Policy
from app.timezone import INSTITUTE_TZ

DAY = date(2026, 10, 5)  # dushanba
POLICY = Policy(staff_start=time(8, 0), student_start=time(8, 30), grace_minutes=10, work_end=time(17, 0))
NOW = datetime(2026, 10, 5, 20, 30, tzinfo=INSTITUTE_TZ)
ALL = {6, 7, 8, 9, 10, 15, 19, 21, 22}


def at(hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(2026, 10, 5, hh, mm, ss, tzinfo=INSTITUTE_TZ).astimezone(timezone.utc)


def obs(person="p1", camera="door", hh=8, mm=0, ss=0, sim=0.62, margin=0.2, job="j", clip=0, **extra) -> Obs:
    start = at(hh, mm, ss)
    return Obs(
        person_id=person,
        camera_id=camera,
        job_id=job,
        clip_index=clip,
        seen_at=start,
        last_seen_at=extra.pop("last", start + timedelta(seconds=2)),
        similarity=sim,
        margin=margin,
        **extra,
    )


# ─────────────────────────────────────── ishonchlilik


def test_strict_and_relaxed_grades():
    assert is_strong(obs(sim=0.55, margin=0.10))
    assert not is_strong(obs(sim=0.55, margin=0.01))  # ikki nomzod deyarli teng
    assert is_weak(obs(sim=0.45, margin=0.10))
    assert not is_weak(obs(sim=0.45, margin=0.05))
    assert not is_weak(obs(sim=0.40, margin=0.30))


def test_lone_relaxed_match_is_not_trusted():
    assert reliable([obs(sim=0.45, margin=0.1)]) == []


def test_relaxed_match_confirmed_by_another_camera():
    a = obs(camera="door", sim=0.45, margin=0.1, hh=8, mm=0)
    b = obs(camera="hall", sim=0.46, margin=0.1, hh=8, mm=2)
    assert reliable([a, b]) == [a, b]


def test_relaxed_match_same_camera_needs_time_gap():
    a = obs(camera="door", sim=0.45, margin=0.1, hh=8, mm=0, ss=0)
    too_close = obs(camera="door", sim=0.45, margin=0.1, hh=8, mm=0, ss=3)
    assert reliable([a, too_close]) == []
    later = obs(camera="door", sim=0.45, margin=0.1, hh=8, mm=0, ss=30)
    assert reliable([a, later]) == [a, later]


def test_relaxed_matches_far_apart_do_not_confirm_each_other():
    a = obs(camera="door", sim=0.45, margin=0.1, hh=8, mm=0)
    b = obs(camera="hall", sim=0.45, margin=0.1, hh=11, mm=0)
    assert reliable([a, b]) == []


# ─────────────────────────────────────── kunlik davomat (#6, #7, #9)


def test_staff_arrival_on_time_and_departure_at_door():
    items = [obs(hh=7, mm=55), obs(camera="hall", hh=12, mm=0), obs(hh=17, mm=20)]
    result = day_attendance(items, person_type="xodim", day=DAY, policy=POLICY, door_cameras={"door"}, now=NOW)
    assert result.status == "keldi"
    assert result.check_in == time(7, 55)
    assert result.check_out == time(17, 20, 2)
    assert result.late_minutes == 0
    assert result.early_leave == EARLY_NO
    assert result.cameras == 2 and result.sightings == 3


def test_staff_late_by_minutes_counted_from_start():
    items = [obs(hh=8, mm=25), obs(hh=17, mm=5)]
    result = day_attendance(items, person_type="xodim", day=DAY, policy=POLICY, door_cameras={"door"}, now=NOW)
    assert result.status == "kech_keldi"
    assert result.late_minutes == 25


def test_grace_period_is_not_late_and_student_start_differs():
    staff = day_attendance([obs(hh=8, mm=10), obs(hh=17, mm=1)], person_type="xodim", day=DAY, policy=POLICY,
                           door_cameras={"door"}, now=NOW)
    assert staff.status == "keldi"
    student = day_attendance([obs(hh=8, mm=35), obs(hh=17, mm=1)], person_type="talaba", day=DAY, policy=POLICY,
                             door_cameras={"door"}, now=NOW)
    assert student.status == "keldi"  # talaba 08:30 + 10


def test_first_seen_in_classroom_after_cutoff_is_not_called_late():
    """Eshik kamerasida ko'rinmagan, birinchi marta 10:00 da xonada —
    boshqa (kamerasiz) eshikdan vaqtida kirgan bo'lishi mumkin."""
    items = [obs(camera="room", hh=10, mm=0), obs(camera="room", hh=11, mm=0)]
    result = day_attendance(items, person_type="xodim", day=DAY, policy=POLICY, door_cameras={"door"}, now=NOW)
    assert result.status == "keldi"
    assert result.check_in is None and not result.arrival_known
    assert result.late_minutes == 0
    assert result.early_leave == EARLY_UNKNOWN


def test_early_leave_needs_evidence():
    # Ertalab keldi, 13:00 da eshikdan chiqdi, keyin hech qayerda ko'rinmadi.
    left = day_attendance(
        [obs(hh=7, mm=50), obs(camera="hall", hh=11, mm=0), obs(hh=13, mm=0)],
        person_type="xodim", day=DAY, policy=POLICY, door_cameras={"door"}, now=NOW,
    )
    assert left.early_leave == EARLY_YES
    # Bir marta ko'rindi — "erta ketdi" emas, "aniqlanmadi".
    once = day_attendance([obs(hh=7, mm=50)], person_type="xodim", day=DAY, policy=POLICY,
                          door_cameras={"door"}, now=NOW)
    assert once.early_leave == EARLY_UNKNOWN


def test_seen_after_exit_means_did_not_leave():
    items = [obs(hh=7, mm=50), obs(hh=13, mm=0), obs(camera="hall", hh=16, mm=30)]
    result = day_attendance(items, person_type="xodim", day=DAY, policy=POLICY, door_cameras={"door"}, now=NOW)
    assert result.early_leave == EARLY_NO


def test_day_off_has_no_lateness():
    sunday = date(2026, 10, 4)
    items = [Obs("p", "door", "j", 0, datetime(2026, 10, 4, 6, 0, tzinfo=timezone.utc),
                 datetime(2026, 10, 4, 6, 0, 5, tzinfo=timezone.utc), 0.6, 0.2)]
    result = day_attendance(items, person_type="xodim", day=sunday, policy=POLICY, door_cameras={"door"},
                            now=NOW)
    assert result.status == "keldi" and result.late_minutes == 0


def test_presence_visits_merge_by_gap_and_camera():
    items = [
        obs(camera="a", hh=8, mm=0), obs(camera="a", hh=8, mm=5), obs(camera="a", hh=8, mm=30),
        obs(camera="b", hh=8, mm=6), obs(camera=None, hh=9, mm=0),
    ]
    visits = presence_visits(items, gap_minutes=10)
    by_cam = sorted((v["camera_id"], v["sightings"]) for v in visits)
    assert by_cam == [("a", 1), ("a", 2), ("b", 1)]


# ─────────────────────────────────────── dars (#7, #8, #9, #19, #21, #22)

L_START = at(9, 0)
L_END = at(10, 20)
LESSON = LessonInfo("L1", "DI-101", "t1", "room", L_START, L_END)
W_END = at(20, 0)


def lesson_job(covered: set[int] | None = None) -> JobInfo:
    clips = lesson_clips(L_START, L_END, ALL, W_END)
    return JobInfo(
        id="j", camera_id="room", kind="dars", clips=clips,
        covered=set(range(len(clips))) if covered is None else covered, lesson_id="L1",
    )


def idx(job: JobInfo, phase: str, n: int = 0) -> int:
    return [i for i, c in enumerate(job.clips) if c.phase == phase][n]


def clip_obs(job: JobInfo, index: int, person: str, **extra) -> Obs:
    clip = job.clips[index]
    return Obs(person, "room", "j", index, clip.start, clip.end, extra.pop("sim", 0.6), extra.pop("margin", 0.2), **extra)


def test_student_present_on_time_late_and_absent():
    job = lesson_job()
    s, m = PHASE_START, PHASE_MID
    items = [
        clip_obs(job, idx(job, s, 5), "on_time"),  # 08:55
        clip_obs(job, idx(job, m, 0), "on_time"),
        clip_obs(job, idx(job, s, 25), "late"),  # 09:15
        clip_obs(job, idx(job, m, 1), "late"),
    ]
    result = lesson_result(LESSON, job, items, ["on_time", "late", "absent"], set(), window_end=W_END)
    assert result.measured
    assert result.students["on_time"].status == "keldi"
    assert result.students["late"].status == "kech_keldi"
    assert result.students["absent"].status == "kelmadi"


def test_single_sighting_is_not_presence():
    job = lesson_job()
    items = [clip_obs(job, idx(job, PHASE_MID, 0), "ghost"), clip_obs(job, idx(job, PHASE_MID, 0), "anchor"),
             clip_obs(job, idx(job, PHASE_MID, 1), "anchor")]
    result = lesson_result(LESSON, job, items, ["ghost", "anchor"], set(), window_end=W_END)
    assert result.students["ghost"].status == "kelmadi"
    # Darsga faqat o'rtasida ko'rindi — keldi, lekin kechikib.
    assert result.students["anchor"].status == "kech_keldi"


def test_strong_multi_frame_track_counts_as_presence():
    job = lesson_job()
    items = [clip_obs(job, idx(job, PHASE_START, 8), "a", frames=3, sim=0.62)]
    result = lesson_result(LESSON, job, items, ["a"], set(), window_end=W_END)
    assert result.students["a"].status == "keldi"


def test_no_coverage_means_unmeasured_not_absent():
    job = lesson_job(covered=set())
    result = lesson_result(LESSON, job, [], ["a", "b"], set(), window_end=W_END)
    assert not result.measured
    assert result.students["a"].status is None and result.students["b"].status is None


def test_camera_working_but_nobody_recognized_is_unmeasured():
    """Kamera ishladi, lekin hech kim tanilmadi (yuzlar juda kichik) —
    butun guruh "kelmadi" emas."""
    job = lesson_job()
    result = lesson_result(LESSON, job, [], ["a", "b"], set(), window_end=W_END)
    assert not result.measured
    assert result.students["a"].status is None


def test_late_requires_camera_to_have_seen_the_empty_moment():
    """Boshlanish oynasi yozilmagan (NVR'da bo'shliq) — talaba o'rtada
    ko'rindi: kechikkanini isbotlab bo'lmaydi."""
    job = lesson_job()
    start_indices = {i for i, c in enumerate(job.clips) if c.phase == PHASE_START}
    job.covered -= {i for i in start_indices if job.clips[i].start >= L_START}
    items = [clip_obs(job, idx(job, PHASE_MID, 0), "a"), clip_obs(job, idx(job, PHASE_MID, 1), "a"),
             clip_obs(job, idx(job, PHASE_MID, 0), "b"), clip_obs(job, idx(job, PHASE_MID, 1), "b")]
    result = lesson_result(LESSON, job, items, ["a", "b"], set(), window_end=W_END)
    assert result.students["a"].status == "keldi"


def test_left_early_only_with_end_coverage():
    job = lesson_job()
    leaver = [clip_obs(job, idx(job, PHASE_START, 9), "x"), clip_obs(job, idx(job, PHASE_MID, 0), "x")]
    stayer = [clip_obs(job, idx(job, PHASE_START, 9), "y"), clip_obs(job, idx(job, PHASE_END, 10), "y")]
    result = lesson_result(LESSON, job, leaver + stayer, ["x", "y"], set(), window_end=W_END)
    assert result.students["x"].left_early is True
    assert result.students["y"].left_early is False
    # Oxirgi daqiqalar yozilmagan — erta ketish o'lchanmaydi.
    job2 = lesson_job()
    job2.covered -= {i for i, c in enumerate(job2.clips) if c.phase == PHASE_END}
    result2 = lesson_result(LESSON, job2, leaver + stayer, ["x", "y"], set(), window_end=W_END)
    assert result2.students["x"].left_early is None


def test_attention_score_per_student_and_lesson():
    assert attention_score(4, 4, 0) == 100
    assert attention_score(4, 0, 4) == 20
    assert attention_score(4, 0, 0) == 40
    assert attention_score(4, 2, 1) == pytest.approx((2 * 100 + 1 * 20 + 1 * 40) / 4)
    assert attention_score(0, 0, 0) is None
    job = lesson_job()
    m0, m1 = idx(job, PHASE_MID, 0), idx(job, PHASE_MID, 1)
    items = [
        clip_obs(job, m0, "focused", frames=2, frontal_frames=2),
        clip_obs(job, m1, "focused", frames=2, frontal_frames=2),
        clip_obs(job, m0, "phone", frames=2, phone_frames=2),
        clip_obs(job, m1, "phone", frames=2, phone_frames=2),
    ]
    result = lesson_result(LESSON, job, items, ["focused", "phone"], set(), window_end=W_END)
    assert result.students["focused"].attention == 100
    assert result.students["phone"].attention == 20
    assert result.attention == 60
    assert result.attention_samples == 8


def test_teacher_on_time_late_absent_and_activity():
    job = lesson_job()
    s = PHASE_START
    student = [clip_obs(job, idx(job, s, 9), "st"), clip_obs(job, idx(job, PHASE_MID, 0), "st")]
    on_time = [clip_obs(job, idx(job, s, 12), "t1"), clip_obs(job, idx(job, PHASE_MID, 0), "t1", movement=50.0),
               clip_obs(job, idx(job, PHASE_MID, 1), "t1", movement=30.0)]
    result = lesson_result(LESSON, job, student + on_time, ["st"], {"t1"}, window_end=W_END)
    assert result.teacher.status == "vaqtida" and result.teacher.on_time is True
    mids = [i for i, c in enumerate(job.clips) if c.phase == PHASE_MID]
    assert result.teacher.presence_pct == round(100 * 2 / len(mids))
    assert result.teacher.activity == round(0.4 * result.teacher.presence_pct + 0.6 * 40)

    late = [clip_obs(job, idx(job, s, 25), "t1"), clip_obs(job, idx(job, PHASE_MID, 2), "t1")]  # 09:15
    result = lesson_result(LESSON, job, student + late, ["st"], {"t1"}, window_end=W_END)
    assert result.teacher.status == "kechikdi" and result.teacher.on_time is False

    substitute = [clip_obs(job, idx(job, s, 12), "other_staff"), clip_obs(job, idx(job, PHASE_MID, 0), "other_staff")]
    result = lesson_result(LESSON, job, student + substitute, ["st"], {"t1", "other_staff"}, window_end=W_END)
    assert result.teacher.status == "kelmadi"
    assert result.teacher.others == ["other_staff"]


def test_teacher_not_judged_when_camera_saw_nobody():
    job = lesson_job(covered=set())
    result = lesson_result(LESSON, job, [], [], set(), window_end=W_END)
    assert result.teacher.status == "aniqlanmadi" and result.teacher.on_time is None


# ─────────────────────────────────────── xalat (#10)


def test_coat_votes_per_observation_majority():
    items = [
        obs(coat_frames=3, coat_white_frames=3),
        obs(coat_frames=3, coat_white_frames=0),
        obs(coat_frames=2, coat_white_frames=1),  # teng — ovoz yo'q
        obs(coat_frames=0, coat_white_frames=0),
    ]
    assert coat_votes(items) == [True, False]


# ─────────────────────────────────────── chekish (#15)


def test_smoking_candidates_merge_into_incidents():
    def job(camera, items):
        return JobInfo(id=camera, camera_id=camera, kind="chekish", clips=[], covered=set(), result={"smoking": items})

    t0 = at(12, 0)
    jobs = [
        job("yard", [
            {"at": t0.isoformat(), "person_id": None, "confidence": 50, "episodes": 2, "snapshot_key": "a"},
            {"at": (t0 + timedelta(minutes=5)).isoformat(), "person_id": "p1", "confidence": 60, "episodes": 3,
             "snapshot_key": "b"},
            {"at": (t0 + timedelta(hours=2)).isoformat(), "person_id": None, "confidence": 45, "episodes": 2},
        ]),
        job("corridor", [{"at": t0.isoformat(), "person_id": "p2", "confidence": 70, "episodes": 2}]),
        job("broken", [{"at": "not-a-date"}, {}]),
    ]
    incidents = smoking_incidents(jobs)
    assert len(incidents) == 3
    merged = next(i for i in incidents if i.camera_id == "yard" and i.clips == 2)
    assert merged.person_id == "p1"
    assert merged.snapshot_key == "b"
    assert merged.confidence == 70  # 60 + takror klip uchun 10
    assert merged.episodes == 5


def test_smoking_daily_cap_keeps_most_confident(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "smoking_max_events_per_camera_day", 2)
    t0 = at(9, 0)
    items = [
        {"at": (t0 + timedelta(hours=k)).isoformat(), "person_id": None, "confidence": 40 + k, "episodes": 2}
        for k in range(5)
    ]
    jobs = [JobInfo(id="y", camera_id="yard", kind="chekish", clips=[], covered=set(), result={"smoking": items})]
    incidents = smoking_incidents(jobs)
    assert sorted(i.confidence for i in incidents) == [43, 44]


def test_mid_phase_clips_exist_for_typical_lesson():
    job = lesson_job()
    phases = {c.phase for c in job.clips}
    assert phases == {PHASE_START, PHASE_MID, PHASE_END}
    assert all(isinstance(c, Clip) for c in job.clips)


# ─────────────────────────────────────────── kelish oynasi qamrovi ("kelmadi" sharti)


def _door_job(start_hh: int, end_hh: int, covered: bool, kind: str = "kirish") -> JobInfo:
    clip = Clip(at(start_hh, 0), at(end_hh, 0), 1.0, ("davomat",))
    return JobInfo(id=f"d{start_hh}", camera_id="door", kind=kind, clips=[clip], covered={0} if covered else set())


def test_arrival_coverage_counts_only_morning_door_video():
    from app.batch.rules import arrival_coverage

    until = at(12, 0)
    jobs = [_door_job(7, 8, True), _door_job(8, 9, True), _door_job(9, 10, False), _door_job(10, 11, True),
            _door_job(14, 15, False)]  # tushdan keyingisi hisobga kirmaydi
    assert arrival_coverage(jobs, until) == 0.75
    # Dars xonasi qamrovi kirish eshigi bo'lsa aralashmaydi.
    assert arrival_coverage(jobs + [lesson_job(covered=set())], until) == 0.75


def test_arrival_coverage_without_door_cameras_uses_every_job():
    from app.batch.rules import arrival_coverage

    jobs = [_door_job(7, 8, True, kind="chekish"), _door_job(8, 9, False, kind="umumiy")]
    assert arrival_coverage(jobs, at(12, 0)) == 0.5
    assert arrival_coverage([], at(12, 0)) is None
    assert arrival_coverage([_door_job(14, 15, True)], at(12, 0)) is None  # oynada klip yo'q
