from typing import Literal

from app.schemas.base import CamelModel

LessonRelation = Literal["oz_darsi", "boshqa_dars", "darsi_boshqa_joyda", "darsdan_tashqari", "jadval_yoq"]


class LessonLinkOut(CamelModel):
    """Tashrif shu paytdagi darsga qanday bog'liq."""

    relation: LessonRelation
    label: str
    subject: str | None = None
    group_name: str | None = None
    teacher: str | None = None
    starts_at: str | None = None  # "09:00"
    ends_at: str | None = None


class VisitOut(CamelModel):
    camera: str
    building: str
    zone: str
    camera_role: str  # "Kirish/chiqish", "Kirish", "Chiqish", "Xona/koridor"
    first_seen: str  # "09:03:12", Toshkent vaqti
    last_seen: str
    duration_minutes: int
    sightings: int
    lesson: LessonLinkOut


class ScheduledLessonOut(CamelModel):
    subject: str
    group_name: str
    starts_at: str
    ends_at: str
    camera: str | None = None
    building: str | None = None
    attended: bool
    arrived_at: str | None = None
    late: bool = False


class PersonDayOut(CamelModel):
    id: str
    full_name: str
    type: Literal["talaba", "xodim"]
    faculty: str
    unit: str
    date: str
    attendance_status: str | None = None
    check_in: str | None = None
    check_out: str | None = None
    first_seen: str | None = None
    last_seen: str | None = None
    buildings: list[str]
    visits: list[VisitOut]
    lessons: list[ScheduledLessonOut]


class TeacherDaySummaryOut(CamelModel):
    id: str
    full_name: str
    faculty: str
    unit: str
    attendance_status: str | None = None
    first_seen: str | None = None
    last_seen: str | None = None
    visits: int
    buildings: list[str]
    lessons_scheduled: int
    lessons_attended: int


class AttendanceCameraOut(CamelModel):
    id: str
    name: str
    building: str
    zone: str
    role: str
    check_interval_seconds: int | None = None
    attendance_enabled: bool
    disabled_reason: str | None = None
    online: bool
    video: bool
    recognized_today: int
    last_recognition: str | None = None  # "14:32"
    # Xotiradagi tanish statistikasi (app/services/recognition_stats.py) —
    # "kamera ko'rmayaptimi yoki tanimayaptimi" degan savolga javob.
    frames_checked_today: int = 0
    faces_seen_today: int = 0
    face_px_median: int | None = None
    small_faces_today: int = 0
    best_similarity_today: float | None = None
    similarity_buckets: dict[str, int] = {}
    strict_matches_today: int = 0
    relaxed_confirmed_today: int = 0
    relaxed_pending_today: int = 0
    last_checked: str | None = None
    cycles_today: int = 0
    last_cycle_seconds: float | None = None
    last_grab_seconds: float | None = None
    # AI qaysi oqimni o'qiyapti: "asosiy", "substream", "substream (zaxira)".
    stream_in_use: str | None = None
    diagnosis: str | None = None


class AttendanceCamerasOut(CamelModel):
    staff_module_active: bool
    student_module_active: bool
    total: int
    attendance_enabled: int
    entrance: int
    exit: int
    online: int
    video: int
    recognizing_today: int
    people_recognized_today: int
    enrolled_faces: int = 0
    match_threshold: float = 0.55
    relaxed_threshold: float | None = None
    cameras: list[AttendanceCameraOut]
