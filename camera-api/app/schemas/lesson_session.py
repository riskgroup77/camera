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


class LessonSessionCreateIn(CamelModel):
    date: str
    group: str
    faculty: str
    teacher: str
    subject: str
    attention_score: int
    sleep_incidents: int = 0
    teacher_activity_score: int
    teacher_on_time: bool = True
