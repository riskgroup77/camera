import uuid
from datetime import date as date_type

from sqlalchemy import Boolean, Date, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class LessonSession(Base):
    """Matches src/types/index.ts `LessonSession` — TT 3-E bo'lim (Ta'lim
    jarayoni sifati) monitoring natijasi. Scores here would come from AI
    modules 19-22 (talaba diqqati, uxlab qolish, o'qituvchi faolligi,
    o'qituvchining aniq kelishi) once those are wired to a real model —
    today this is a storage/reporting layer, populated manually or by
    whatever produces the scores."""

    __tablename__ = "lesson_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    group_name: Mapped[str] = mapped_column(String, nullable=False)
    faculty: Mapped[str] = mapped_column(String, nullable=False)
    teacher: Mapped[str] = mapped_column(String, nullable=False)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    attention_score: Mapped[int] = mapped_column(Integer, nullable=False)
    sleep_incidents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    teacher_activity_score: Mapped[int] = mapped_column(Integer, nullable=False)
    teacher_on_time: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
