from app.schemas.base import CamelModel


class LessonSessionOut(CamelModel):
    """Matches src/types/index.ts `LessonSession` exactly."""

    id: str
    date: str
    group: str
    faculty: str
    teacher: str
    subject: str
    attention_score: int
    sleep_incidents: int
    teacher_activity_score: int
    teacher_on_time: bool
    # Set together (see app/routers/lesson_sessions.py's _resolve_teacher) —
    # once all three are present, app/jobs/teacher_punctuality_ai.py and
    # app/jobs/lesson_quality_ai.py pick this session up automatically.
    teacher_id: str | None = None
    camera_id: str | None = None
    scheduled_start_time: str | None = None  # ISO 8601, institute-local (see app/timezone.py)


class LessonSessionCreateIn(CamelModel):
    date: str
    group: str
    faculty: str
    subject: str
    # `teacher` (display name) is auto-filled server-side from teacher_id
    # when one is given — see _resolve_teacher — so it's optional here
    # even though LessonSessionOut always returns it.
    teacher: str | None = None
    # Scores default to a neutral 50 rather than being required — a
    # freshly SCHEDULED lesson hasn't happened yet, so there's no real
    # attention/activity data to report; these get overwritten by
    # app/jobs/lesson_quality_ai.py once the lesson is actually in
    # progress.
    attention_score: int = 50
    sleep_incidents: int = 0
    teacher_activity_score: int = 50
    teacher_on_time: bool = True
    teacher_id: str | None = None
    camera_id: str | None = None
    scheduled_start_time: str | None = None


class LessonSessionScheduleIn(CamelModel):
    """PATCH body for attaching/changing a schedule on an existing
    (already-created) LessonSession row — see
    PATCH /api/lesson-sessions/{id}/schedule."""

    teacher_id: str | None = None
    camera_id: str | None = None
    scheduled_start_time: str | None = None
