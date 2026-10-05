"""Kriteriyalar qoidalari — sof funksiyalar (baza yo'q, vaqt tashqaridan).

Kirish: kun kuzatuvlari (videoda tanilgan yuzlar), vazifalar qamrovi
(qaysi kliplar haqiqatan o'qildi), dars jadvali va ish vaqti qoidasi.
Chiqish: har odam va har dars bo'yicha qarorlar. Bazaga yozish —
app/batch/aggregate.py.

ASOSIY TAMOYIL — ayblov faqat dalil bilan. "Kelmadi", "kechikdi", "erta
ketdi" faqat kamera o'sha oraliqni haqiqatan ko'rgan bo'lsa chiqariladi;
aks holda natija NULL / "aniqlanmadi". Yolg'on ayblovdan ko'ra
"o'lchanmadi" halolroq (app/services/attendance_policy.py bilan bir ruh).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date as date_type, datetime, timedelta
from datetime import time as time_type

from app.batch import coat as coat_rules
from app.batch.planner import KIND_ENTRANCE, PHASE_END, PHASE_MID, PHASE_START, Clip
from app.config import settings
from app.services.attendance_policy import EARLY_NA, Policy, early_leave_verdict
from app.timezone import to_local

# Xona bosqichi qamrovi shundan kam bo'lsa — o'sha bosqich bo'yicha qaror yo'q.
MIN_PHASE_COVERAGE = 0.5


@dataclass(frozen=True)
class Obs:
    """Bitta kuzatuv (VideoObservation qatorining kerakli qismi)."""

    person_id: str
    camera_id: str | None
    job_id: str
    clip_index: int
    seen_at: datetime
    last_seen_at: datetime
    similarity: float
    margin: float
    frames: int = 1
    frontal_frames: int = 0
    phone_frames: int = 0
    coat_frames: int = 0
    coat_white_frames: int = 0
    movement: float | None = None
    evidence_key: str | None = None


@dataclass
class JobInfo:
    id: str
    camera_id: str | None
    kind: str
    clips: list[Clip]
    covered: set[int]
    lesson_id: str | None = None
    faces: int = 0
    result: dict | None = None


@dataclass(frozen=True)
class LessonInfo:
    id: str
    group_name: str
    teacher_id: str | None
    camera_id: str | None
    start: datetime
    end: datetime


# ─────────────────────────────────────────────── ishonchli kuzatuvlar


def is_strong(obs: Obs) -> bool:
    return obs.similarity >= settings.attendance_ai_match_threshold and obs.margin >= settings.attendance_ai_strict_margin


def is_weak(obs: Obs) -> bool:
    return (
        obs.similarity >= settings.attendance_ai_relaxed_threshold
        and obs.margin >= settings.attendance_ai_relaxed_margin
    )


def _independent(a: Obs, b: Obs) -> bool:
    if a.camera_id != b.camera_id:
        return True
    gap = abs((a.seen_at - b.seen_at).total_seconds())
    return gap >= settings.attendance_relaxed_same_camera_gap_seconds


def reliable(observations: list[Obs]) -> list[Obs]:
    """Bitta odamning ishonchli kuzatuvlari: qat'iy moslik, yoki yumshoq
    moslik + yaqin vaqtda (attendance_relaxed_confirm_window_seconds)
    mustaqil ikkinchi ko'rinish (boshqa kamera yoki >= 10 s keyin)."""
    window = settings.attendance_relaxed_confirm_window_seconds
    out: list[Obs] = []
    candidates = [obs for obs in observations if is_strong(obs) or is_weak(obs)]
    for obs in candidates:
        if is_strong(obs):
            out.append(obs)
            continue
        if any(
            other is not obs
            and _independent(obs, other)
            and abs((other.seen_at - obs.seen_at).total_seconds()) <= window
            for other in candidates
        ):
            out.append(obs)
    return sorted(out, key=lambda item: item.seen_at)


def group_by_person(observations: list[Obs]) -> dict[str, list[Obs]]:
    grouped: dict[str, list[Obs]] = defaultdict(list)
    for obs in observations:
        grouped[obs.person_id].append(obs)
    return {person: reliable(items) for person, items in grouped.items()}


# ─────────────────────────────────────────────── kunlik davomat (#6, #7, #9)


@dataclass
class DayAttendance:
    status: str  # keldi | kech_keldi
    check_in: time_type | None
    check_out: time_type | None
    arrived_at: datetime
    left_at: datetime
    last_seen: time_type
    late_minutes: int
    sightings: int
    cameras: int
    early_leave: str
    arrival_known: bool
    # Dalil klipi uchun: kelish va ketish ko'ringan kameralar.
    arrival_camera_id: str | None = None
    exit_camera_id: str | None = None


def day_attendance(
    observations: list[Obs],
    *,
    person_type: str | None,
    day: date_type,
    policy: Policy,
    door_cameras: set[str],
    now: datetime,
) -> DayAttendance | None:
    """`observations` — shu odamning ISHONCHLI kuzatuvlari (reliable())."""
    if not observations:
        return None
    first = min(observations, key=lambda obs: obs.seen_at)
    last = max(observations, key=lambda obs: obs.last_seen_at)
    arrival_local = to_local(first.seen_at).time().replace(microsecond=0)
    late_after = policy.late_after(person_type)
    # Kelish vaqti eshik kamerasida ko'rilgan bo'lsa ma'lum. Boshqa kamerada
    # birinchi marta kechikish chegarasidan KEYIN ko'rilgan odam boshqa
    # (kamerasiz) eshikdan vaqtida kirgan bo'lishi mumkin — kelish vaqti
    # noma'lum, kechikish yozilmaydi (attendance_ai.first_sighting_status).
    from app.timezone import business_seconds

    arrival_known = first.camera_id in door_cameras or business_seconds(arrival_local) <= business_seconds(late_after)
    if arrival_known:
        check_in: time_type | None = arrival_local
        status = policy.arrival_status(arrival_local, person_type, day)
        late = policy.late_minutes(arrival_local, person_type, day)
    else:
        check_in, status, late = None, "keldi", 0
    door_sightings = [obs for obs in observations if obs.camera_id in door_cameras]
    exit_obs = max(door_sightings, key=lambda obs: obs.last_seen_at) if door_sightings else last
    check_out = to_local(exit_obs.last_seen_at).time().replace(microsecond=0)
    last_seen = to_local(last.last_seen_at).time().replace(microsecond=0)
    verdict = early_leave_verdict(
        status=status,
        day=day,
        check_in=check_in,
        check_out=check_out,
        last_seen=last_seen,
        sightings=len(observations),
        policy=policy,
        now=now,
    )
    return DayAttendance(
        status=status,
        check_in=check_in,
        check_out=check_out,
        arrived_at=first.seen_at,
        left_at=exit_obs.last_seen_at,
        last_seen=last_seen,
        late_minutes=late,
        sightings=len(observations),
        cameras=len({obs.camera_id for obs in observations}),
        early_leave=verdict,
        arrival_known=arrival_known,
        arrival_camera_id=first.camera_id,
        exit_camera_id=exit_obs.camera_id,
    )


def arrival_coverage(jobs: list[JobInfo], until: datetime) -> float | None:
    """Kelish oynasi (kun boshidan `until` gacha) kliplarining qancha qismi
    haqiqatan o'qildi (0..1). Kirish/chiqish kameralari bo'lsa — faqat ular,
    bo'lmasa (kamera turlari belgilanmagan) — hamma vazifalar. None — oynada
    klip yo'q.

    "Kelmadi" shu qamrov yetarli bo'lgandagina yoziladi: muddat (08:00)
    yetmay ertalabki eshik videolari tahlil qilinmay qolsa, o'sha soatda
    kelganlar "kelmadi" bo'lib qolmasin."""
    door = [job for job in jobs if job.kind == KIND_ENTRANCE]
    total = covered = 0
    for job in door or jobs:
        for index, clip in enumerate(job.clips):
            if clip.start < until:
                total += 1
                covered += index in job.covered
    return covered / total if total else None


def presence_visits(observations: list[Obs], gap_minutes: int) -> list[dict]:
    """Kuzatuvlardan "tashriflar" (bir kamerada uzluksiz bo'lish) —
    PresenceVisit qatorlari uchun."""
    gap = timedelta(minutes=gap_minutes)
    visits: list[dict] = []
    by_camera: dict[str | None, list[Obs]] = defaultdict(list)
    for obs in observations:
        by_camera[obs.camera_id].append(obs)
    for camera_id, items in by_camera.items():
        if camera_id is None:
            continue
        current: dict | None = None
        for obs in sorted(items, key=lambda item: item.seen_at):
            if current is not None and obs.seen_at - current["last_seen_at"] <= gap:
                current["last_seen_at"] = max(current["last_seen_at"], obs.last_seen_at)
                current["sightings"] += 1
                current["best_similarity"] = max(current["best_similarity"], obs.similarity)
                continue
            current = {
                "camera_id": camera_id,
                "first_seen_at": obs.seen_at,
                "last_seen_at": obs.last_seen_at,
                "sightings": 1,
                "best_similarity": obs.similarity,
            }
            visits.append(current)
    return visits


# ─────────────────────────────────────────────── darslar (#7, #8, #9, #19, #21, #22)


@dataclass
class StudentLessonResult:
    status: str | None  # keldi | kech_keldi | kelmadi | None (o'lchanmadi)
    first_seen: datetime | None
    last_seen: datetime | None
    sightings: int
    left_early: bool | None
    attention: int | None
    attention_samples: int
    # Diqqat dalili uchun payt: eng chalg'igan ko'rinish (telefon, keyin qiya yuz).
    attention_at: datetime | None = None


@dataclass
class TeacherLessonResult:
    on_time: bool | None
    first_seen: datetime | None
    status: str  # vaqtida | kechikdi | kelmadi | aniqlanmadi
    presence_pct: int | None
    activity: int | None
    activity_samples: int
    others: list[str] = field(default_factory=list)
    # Faollik dalili uchun payt: eng kam harakatli ko'rinish.
    activity_at: datetime | None = None


@dataclass
class LessonResult:
    lesson_id: str
    measured: bool
    students: dict[str, StudentLessonResult]
    teacher: TeacherLessonResult | None
    attention: int | None
    attention_samples: int
    coverage: dict[str, float]
    # Xona haqiqatan ko'rilgan payt (darsga kelmaganlik dalili): birinchi
    # qoplangan o'rta klip, bo'lmasa boshlanish klipi.
    room_at: datetime | None = None


def phase_coverage(job: JobInfo) -> dict[str, float]:
    totals: dict[str, int] = defaultdict(int)
    covered: dict[str, int] = defaultdict(int)
    for index, clip in enumerate(job.clips):
        phase = clip.phase or PHASE_MID
        totals[phase] += 1
        if index in job.covered:
            covered[phase] += 1
    return {phase: (covered[phase] / totals[phase]) for phase in totals}


def _clip_phase(job: JobInfo, index: int) -> str | None:
    if 0 <= index < len(job.clips):
        return job.clips[index].phase
    return None


def attention_score(frames: int, frontal: int, phone: int) -> float | None:
    """Kadr bo'yicha: telefon — 20, kameraga qaragan — 100, boshqa — 40
    (settings.attention_score_*)."""
    if frames <= 0:
        return None
    phone = min(phone, frames)
    frontal = min(frontal, frames - phone)
    other = frames - phone - frontal
    total = (
        phone * settings.attention_score_phone_visible
        + frontal * settings.attention_score_frontal
        + other * settings.attention_score_not_frontal
    )
    return total / frames


def lesson_result(
    lesson: LessonInfo,
    job: JobInfo,
    observations: list[Obs],
    roster: list[str],
    staff_ids: set[str],
    *,
    window_end: datetime,
) -> LessonResult:
    """Bitta darsning hamma kriteriyalari.

    `observations` — shu vazifaning (dars xonasi) BARCHA kuzatuvlari.
    `roster` — guruh talabalari (biometrikasi tasdiqlangan, faol)."""
    coverage = phase_coverage(job)
    start_cov = coverage.get(PHASE_START, 0.0)
    mid_cov = coverage.get(PHASE_MID, 0.0)
    end_cov = coverage.get(PHASE_END, 0.0)
    body_cov = (
        (start_cov * sum(1 for c in job.clips if c.phase == PHASE_START) + mid_cov * sum(1 for c in job.clips if c.phase == PHASE_MID))
        / max(1, sum(1 for c in job.clips if c.phase in (PHASE_START, PHASE_MID)))
    )
    by_person: dict[str, list[Obs]] = defaultdict(list)
    for obs in observations:
        if is_strong(obs) or is_weak(obs):
            by_person[obs.person_id].append(obs)

    def present(items: list[Obs]) -> bool:
        clips = {obs.clip_index for obs in items}
        if len(clips) >= settings.video_lesson_min_sightings:
            return True
        return any(is_strong(obs) and obs.frames >= 2 for obs in items)

    confirmed_anyone = any(present(items) for items in by_person.values())
    measured = body_cov >= MIN_PHASE_COVERAGE and confirmed_anyone
    grace = timedelta(minutes=settings.attendance_late_to_lesson_grace_minutes)
    late_after = lesson.start + grace
    end_known = lesson.end <= window_end and end_cov >= MIN_PHASE_COVERAGE
    early_cut = lesson.end - timedelta(minutes=settings.video_lesson_early_leave_minutes)
    covered_start_times = sorted(
        job.clips[i].start for i in job.covered if 0 <= i < len(job.clips) and job.clips[i].phase == PHASE_START
    )

    students: dict[str, StudentLessonResult] = {}
    weighted_attention = 0.0
    attention_frames = 0
    for student_id in roster:
        items = by_person.get(student_id, [])
        if not items or not present(items):
            students[student_id] = StudentLessonResult(
                status="kelmadi" if measured else None,
                first_seen=min((o.seen_at for o in items), default=None),
                last_seen=max((o.last_seen_at for o in items), default=None),
                sightings=len(items),
                left_early=None,
                attention=None,
                attention_samples=0,
            )
            continue
        first_seen = min(obs.seen_at for obs in items)
        last_seen = max(obs.last_seen_at for obs in items)
        # Kechikdi — faqat kamera boshlanishdan keyin ham (talaba hali yo'q
        # paytda) ishlagani ko'rinsa: kechikish chegarasidan keyingi, talaba
        # ko'rinishidan oldingi kamida bitta qoplangan klip.
        late = first_seen > late_after and any(late_after <= moment < first_seen for moment in covered_start_times)
        left_early: bool | None = None
        if end_known:
            seen_at_end = any(_clip_phase(job, obs.clip_index) == PHASE_END for obs in items)
            left_early = (not seen_at_end) and last_seen < early_cut
        mid_items = [obs for obs in items if _clip_phase(job, obs.clip_index) == PHASE_MID]
        frames = sum(obs.frames for obs in mid_items)
        score = attention_score(
            frames, sum(obs.frontal_frames for obs in mid_items), sum(obs.phone_frames for obs in mid_items)
        )
        if score is not None:
            weighted_attention += score * frames
            attention_frames += frames
        worst = min(
            mid_items,
            key=lambda obs: (-obs.phone_frames, obs.frontal_frames / max(1, obs.frames), obs.seen_at),
            default=None,
        )
        students[student_id] = StudentLessonResult(
            status="kech_keldi" if late else "keldi",
            first_seen=first_seen,
            last_seen=last_seen,
            sightings=len({obs.clip_index for obs in items}),
            left_early=left_early,
            attention=round(score) if score is not None else None,
            attention_samples=frames,
            attention_at=worst.seen_at if worst is not None else None,
        )

    teacher = None
    if lesson.teacher_id:
        teacher = teacher_result(lesson, job, by_person.get(lesson.teacher_id, []), by_person, staff_ids, measured)
    covered_clips = [job.clips[i] for i in sorted(job.covered) if 0 <= i < len(job.clips)]
    room_clip = next((clip for clip in covered_clips if clip.phase == PHASE_MID), None) or next(iter(covered_clips), None)
    return LessonResult(
        lesson_id=lesson.id,
        measured=measured,
        students=students,
        teacher=teacher,
        attention=round(weighted_attention / attention_frames) if attention_frames else None,
        attention_samples=attention_frames,
        coverage=coverage,
        room_at=room_clip.start if room_clip is not None else None,
    )


def teacher_result(
    lesson: LessonInfo,
    job: JobInfo,
    items: list[Obs],
    by_person: dict[str, list[Obs]],
    staff_ids: set[str],
    measured: bool,
) -> TeacherLessonResult:
    grace = timedelta(minutes=settings.teacher_punctuality_grace_minutes)
    mid_indices = [i for i, clip in enumerate(job.clips) if clip.phase == PHASE_MID and i in job.covered]
    others = sorted(
        person
        for person, obs_list in by_person.items()
        if person != lesson.teacher_id and person in staff_ids and any(is_strong(o) for o in obs_list)
    )
    movements = [obs.movement for obs in items if obs.movement is not None]
    calmest = min((obs for obs in items if obs.movement is not None), key=lambda obs: obs.movement, default=None)
    presence_pct = None
    if mid_indices:
        seen_mid = {obs.clip_index for obs in items if obs.clip_index in mid_indices}
        presence_pct = round(100 * len(seen_mid) / len(mid_indices))
    activity = None
    if presence_pct is not None and movements:
        activity = round(0.4 * presence_pct + 0.6 * (sum(movements) / len(movements)))
    if items:
        first_seen = min(obs.seen_at for obs in items)
        on_time = first_seen <= lesson.start + grace
        return TeacherLessonResult(
            on_time=on_time,
            first_seen=first_seen,
            status="vaqtida" if on_time else "kechikdi",
            presence_pct=presence_pct,
            activity=activity,
            activity_samples=len(movements),
            others=others,
            activity_at=calmest.seen_at if calmest is not None else None,
        )
    # Ko'rinmadi: "kelmadi" faqat dars o'lchangan (kamera ishlagan va kimdir
    # tanilgan) bo'lsa — aks holda kamera o'qituvchini ko'ra olmagan bo'lishi mumkin.
    return TeacherLessonResult(
        on_time=False if measured else None,
        first_seen=None,
        status="kelmadi" if measured else "aniqlanmadi",
        presence_pct=presence_pct if measured else None,
        activity=None,
        activity_samples=0,
        others=others,
    )


# ─────────────────────────────────────────────── xalat (#10)


def coat_votes(observations: list[Obs]) -> list[bool]:
    votes: list[bool] = []
    for obs in observations:
        vote = coat_rules.observation_vote(obs.coat_white_frames, obs.coat_frames)
        if vote is not None:
            votes.append(vote)
    return votes


# ─────────────────────────────────────────────── chekish (#15)


@dataclass
class SmokingIncident:
    camera_id: str | None
    at: datetime
    person_id: str | None
    confidence: int
    episodes: int
    snapshot_key: str | None
    cigarette_seen: bool
    clips: int = 1


def smoking_incidents(jobs: list[JobInfo], merge_minutes: int = 10) -> list[SmokingIncident]:
    """Kliplar bo'yicha nomzodlarni hodisalarga birlashtiradi: bir kamerada
    bir odam (yoki noma'lum) 10 daqiqa ichida — bitta hodisa. Bir necha
    klipda takrorlangan nomzod ishonchliroq (+10 har qo'shimcha klip)."""
    raw: list[SmokingIncident] = []
    for job in jobs:
        for item in (job.result or {}).get("smoking", []) or []:
            try:
                at = datetime.fromisoformat(item["at"])
            except (KeyError, TypeError, ValueError):
                continue
            raw.append(
                SmokingIncident(
                    camera_id=job.camera_id,
                    at=at,
                    person_id=item.get("person_id"),
                    confidence=int(item.get("confidence") or 0),
                    episodes=int(item.get("episodes") or 0),
                    snapshot_key=item.get("snapshot_key"),
                    cigarette_seen=bool(item.get("cigarette_seen")),
                )
            )
    raw.sort(key=lambda item: (str(item.camera_id), item.at))
    merged: list[SmokingIncident] = []
    window = timedelta(minutes=merge_minutes)
    for item in raw:
        previous = next(
            (
                m
                for m in reversed(merged)
                if m.camera_id == item.camera_id
                and item.at - m.at <= window
                and (m.person_id == item.person_id or m.person_id is None or item.person_id is None)
            ),
            None,
        )
        if previous is None:
            merged.append(item)
            continue
        previous.clips += 1
        previous.episodes += item.episodes
        previous.person_id = previous.person_id or item.person_id
        previous.cigarette_seen = previous.cigarette_seen or item.cigarette_seen
        if item.confidence > previous.confidence:
            previous.confidence = item.confidence
            previous.snapshot_key = item.snapshot_key or previous.snapshot_key
        previous.at = max(previous.at, item.at)
    for item in merged:
        item.confidence = min(95, item.confidence + 10 * (item.clips - 1))
    # Kamera bo'yicha kunlik chegara — eng ishonchlilari qoladi.
    by_camera: dict[str | None, list[SmokingIncident]] = defaultdict(list)
    for item in merged:
        by_camera[item.camera_id].append(item)
    out: list[SmokingIncident] = []
    for items in by_camera.values():
        items.sort(key=lambda item: -item.confidence)
        out.extend(items[: settings.smoking_max_events_per_camera_day])
    return sorted(out, key=lambda item: item.at)


def new_uuid(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None
