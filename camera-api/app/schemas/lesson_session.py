from pydantic import Field

from app.schemas.base import CamelModel


class LessonSessionOut(CamelModel):
    """Matches src/types/index.ts `LessonSession` exactly."""

    id: str
    date: str
    group: str
    faculty: str
    teacher: str
    subject: str
    # None — hali o'lchanmagan/tekshirilmagan (0% yoki "kechikdi" emas).
    attention_score: int | None = None
    sleep_incidents: int
    teacher_activity_score: int | None = None
    teacher_on_time: bool | None = None
    # Set together (see app/routers/lesson_sessions.py's _resolve_teacher) —
    # once all three are present, app/jobs/teacher_punctuality_ai.py and
    # app/jobs/lesson_quality_ai.py pick this session up automatically.
    teacher_id: str | None = None
    camera_id: str | None = None
    scheduled_start_time: str | None = None  # ISO 8601, institute-local (see app/timezone.py)
    # HEMIS dars jadvalidan (app/services/integrations/hemis_schedule.py).
    scheduled_end_time: str | None = None
    auditorium: str | None = None
    building: str | None = None
    from_hemis: bool = False


class LessonSessionCreateIn(CamelModel):
    date: str
    group: str
    faculty: str
    subject: str
    # `teacher` (display name) is auto-filled server-side from teacher_id
    # when one is given — see _resolve_teacher — so it's optional here
    # even though LessonSessionOut always returns it.
    teacher: str | None = None
    # Rejalashtirilgan dars hali o'tmagan — o'lchov yo'q. Ilgari bu yerda
    # "neytral" 50 / 50 / vaqtida turardi va hisobotda haqiqiy o'lchovdek
    # ko'rinardi. Qiymat berilsa (qo'lda kiritilgan hisobot) — bitta
    # o'lchov sifatida saqlanadi.
    attention_score: int | None = Field(default=None, ge=0, le=100)
    sleep_incidents: int = 0
    teacher_activity_score: int | None = Field(default=None, ge=0, le=100)
    teacher_on_time: bool | None = None
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


class LessonSessionImportErrorOut(CamelModel):
    row: int
    message: str


class LessonImportPreviewRowOut(CamelModel):
    """Import qilinadigan (yoki qilingan) bitta dars — nima nimaga bog'langani."""

    row: int
    date: str
    start: str | None = None
    group: str
    subject: str
    teacher: str | None = None
    teacher_matched: bool = False
    room: str | None = None
    camera: str | None = None


class LessonSessionImportResultOut(CamelModel):
    imported: int
    skipped: int
    errors: list[LessonSessionImportErrorOut]
    # True — faqat oldindan ko'rish, hech narsa yozilmagan (`imported` —
    # qo'shiladigan darslar soni).
    preview: bool = False
    with_camera: int = 0
    with_teacher: int = 0
    rows: list[LessonImportPreviewRowOut] = []
    # Kameraga bog'lanmagan xona raqamlari va xodimga bog'lanmagan
    # o'qituvchi ismlari (eng ko'p uchraganidan) — kamera xona raqamini
    # yoki ism yozilishini to'g'rilash uchun.
    unmatched_rooms: list[str] = []
    unmatched_teachers: list[str] = []
    # Haftalik import: jadval necha haftaga yoyilgani (sanali importda 0).
    weeks: int = 0


class LessonAttendanceRowOut(CamelModel):
    """Bitta talabaning bitta darsdagi davomati."""

    student_id: str
    full_name: str
    # None = dars hali yakunlanmagan. "kelmadi" dan qat'iy farq qiladi:
    # birinchisi "hali bilmaymiz", ikkinchisi "bo'lmadi" degani.
    status: str | None = None
    first_seen_at: str | None = None
    sightings: int = 0


class LessonAttendanceOut(CamelModel):
    lesson_session_id: str
    group: str
    subject: str
    scheduled_start_time: str | None = None
    finalized: bool
    present: int
    late: int
    absent: int
    rows: list[LessonAttendanceRowOut]
