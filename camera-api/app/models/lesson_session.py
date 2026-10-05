import uuid
from datetime import date as date_type, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class LessonSession(Base):
    """Matches src/types/index.ts `LessonSession` — TT 3-E bo'lim (Ta'lim
    jarayoni sifati) monitoring natijasi. Scores here would come from AI
    modules 19-22 (talaba diqqati, uxlab qolish, o'qituvchi faolligi,
    o'qituvchining aniq kelishi) once those are wired to a real model —
    today this is a storage/reporting layer, populated manually or by
    whatever produces the scores.

    teacher_id/camera_id/scheduled_start_time (all nullable) are the
    minimum a row needs for app/jobs/teacher_punctuality_ai.py (TT
    kriteriya 22) to actually CHECK it against real camera data instead
    of just storing a manually-typed teacher_on_time flag — a row missing
    any of the three is invisible to that job and behaves exactly like
    before (a plain report record). `teacher` (free-text name) is kept
    for existing report-display code; teacher_id is the real link needed
    to match against attendance_ai's face-recognition records."""

    __tablename__ = "lesson_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    group_name: Mapped[str] = mapped_column(String, nullable=False)
    faculty: Mapped[str] = mapped_column(String, nullable=False)
    teacher: Mapped[str] = mapped_column(String, nullable=False)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    attention_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sleep_incidents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    teacher_activity_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Davomiy o'rtachaning namunalar soni (app/jobs/lesson_quality_ai.py).
    # 0 — hali o'lchanmagan: ball ko'rsatilmaydi ("—"), hisobotga kirmaydi.
    attention_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    activity_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # NULL — tekshirilmagan (kamera/kadr bo'lmagan yoki muddati o'tgan).
    teacher_on_time: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)

    teacher_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students_staff.id", ondelete="SET NULL"), nullable=True, index=True
    )
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scheduled_start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set by teacher_punctuality_ai.py once it has handled this row — also
    # when the check could not run (no frame) or its window had passed, in
    # which case teacher_on_time stays NULL. Keeps the job from retrying.
    punctuality_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # HEMIS dars jadvalidan (app/services/integrations/hemis_schedule.py).
    hemis_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True, index=True)
    auditorium: Mapped[str | None] = mapped_column(String, nullable=True)
    building: Mapped[str | None] = mapped_column(String, nullable=True)
    scheduled_end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Kunlik video tahlil: o'qituvchi xonada birinchi ko'ringan payt (#22)
    # va dars o'rtasidagi kliplarning qanchasida ko'ringani, % (#21).
    teacher_first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    teacher_presence_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)

    teacher_ref: Mapped["StudentStaff | None"] = relationship("StudentStaff", lazy="joined")
    camera: Mapped["Camera | None"] = relationship("Camera", lazy="joined")
