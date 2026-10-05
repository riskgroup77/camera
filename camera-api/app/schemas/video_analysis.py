from datetime import date as date_type

from pydantic import Field

from app.schemas.base import CamelModel


class NvrIn(CamelModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field("hikvision", pattern="^(hikvision|fayl)$")
    ip: str | None = Field(None, max_length=64)
    http_port: int = Field(80, ge=1, le=65535)
    rtsp_port: int = Field(554, ge=1, le=65535)
    username: str | None = Field(None, max_length=64)
    password: str | None = Field(None, max_length=128)
    stream: str = Field("main", pattern="^(main|sub)$")
    fetch_mode: str = Field("download", pattern="^(rtsp|download)$")
    max_streams: int = Field(8, ge=1, le=64)
    local_time: bool = True
    rtsp_path_template: str | None = Field(None, max_length=300)
    base_path: str | None = Field(None, max_length=500)
    enabled: bool = True


class NvrPatch(CamelModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    ip: str | None = Field(None, max_length=64)
    http_port: int | None = Field(None, ge=1, le=65535)
    rtsp_port: int | None = Field(None, ge=1, le=65535)
    username: str | None = Field(None, max_length=64)
    password: str | None = Field(None, max_length=128)
    stream: str | None = Field(None, pattern="^(main|sub)$")
    fetch_mode: str | None = Field(None, pattern="^(rtsp|download)$")
    max_streams: int | None = Field(None, ge=1, le=64)
    local_time: bool | None = None
    rtsp_path_template: str | None = Field(None, max_length=300)
    base_path: str | None = Field(None, max_length=500)
    enabled: bool | None = None


class NvrOut(CamelModel):
    id: str
    name: str
    kind: str
    ip: str | None
    http_port: int
    rtsp_port: int
    username: str | None
    has_password: bool
    stream: str
    fetch_mode: str
    max_streams: int
    local_time: bool
    rtsp_path_template: str
    base_path: str | None
    enabled: bool
    last_check_at: str | None
    last_error: str | None
    channel_count: int | None
    cameras: int


class NvrChannelOut(CamelModel):
    channel: int
    name: str
    ip: str | None
    online: bool | None
    camera_id: str | None
    camera_name: str | None


class NvrTestOut(CamelModel):
    ok: bool
    message: str
    model: str | None = None
    channels: int | None = None


class AutoMapOut(CamelModel):
    mapped: int
    unmatched_channels: list[int]
    unmapped_cameras: int


class CameraNvrIn(CamelModel):
    nvr_id: str | None
    channel: int | None = Field(None, ge=1, le=512)


class RunCreateIn(CamelModel):
    day: date_type


class RunOut(CamelModel):
    id: str
    day: str
    status: str
    window_start: str
    window_end: str
    created_at: str | None
    started_at: str | None
    finished_at: str | None
    jobs_total: int
    jobs_done: int
    jobs_failed: int
    jobs_no_video: int
    frames_planned: int
    frames_analyzed: int
    faces_detected: int
    observations: int
    progress: float
    stats: dict | None
    error: str | None
    triggered_by: str


class JobSummaryOut(CamelModel):
    kind: str
    status: str
    count: int
    frames: int


class JobErrorOut(CamelModel):
    camera_name: str | None
    kind: str
    status: str
    error: str | None
    start_at: str


class RunDetailOut(RunOut):
    jobs: list[JobSummaryOut]
    errors: list[JobErrorOut]


class AnalysisStatusOut(CamelModel):
    mode: str
    start_time: str
    day_start: str
    next_run_at: str | None
    nvr_count: int
    mapped_cameras: int
    active_cameras: int
    current: RunOut | None
    last: RunOut | None


class EvidenceOut(CamelModel):
    """Bitta aniqlangan holat va uning video dalili (2 daqiqalik klip)."""

    code: int
    reason: str
    at: str
    camera_name: str | None = None
    clip_url: str | None = None
    clip_error: str | None = None


class DailyCriteriaRowOut(CamelModel):
    person_id: str
    full_name: str
    type: str
    group_or_position: str
    day: str
    attendance_status: str | None
    arrived_at: str | None
    left_at: str | None
    late_minutes: int | None
    early_leave: str | None
    sightings: int
    cameras_seen: int
    lessons_total: int | None
    lessons_attended: int | None
    lessons_late: int | None
    lessons_left_early: int | None
    lessons_unmeasured: int | None
    attention_score: int | None
    coat_status: str | None
    coat_samples: int
    coat_white_samples: int
    smoking_events: int
    teacher_lessons: int | None
    teacher_on_time: int | None
    teacher_late: int | None
    teacher_absent: int | None
    teacher_activity: int | None
    # Aniqlangan holatlar soni (ro'yxatda) va o'zlari (odam tarixida — video havolasi bilan).
    evidence_count: int = 0
    evidence: list[EvidenceOut] = Field(default_factory=list)


class CriteriaSummaryOut(CamelModel):
    day: str
    people: int
    present: int
    late: int
    absent: int
    early_leave: int
    lessons_late: int
    lessons_left_early: int
    attention_avg: int | None
    coat_yes: int
    coat_no: int
    coat_unknown: int
    smoking: int
    teacher_on_time: int
    teacher_late: int
    teacher_absent: int
    teacher_activity_avg: int | None
    run: RunOut | None
