import uuid
from datetime import date as date_type, time

from sqlalchemy import CheckConstraint, Date, ForeignKey, String, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class AttendanceRecord(Base):
    """Matches src/types/index.ts `AttendanceDay`, one row per
    (person, date). In a real deployment this table is populated by the
    face-recognition attendance AI modules (TT kriteriya 6/7) firing a
    check-in/check-out event — see app/routers/attendance.py for the
    honest note on how it's populated today (manually / by admin) vs. how
    it should be populated once that AI module is wired in."""

    __tablename__ = "attendance_records"
    __table_args__ = (
        CheckConstraint("status IN ('keldi', 'kelmadi', 'kech_keldi', 'dam_olish')", name="ck_attendance_status"),
        UniqueConstraint("student_staff_id", "date", name="uq_attendance_person_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    student_staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students_staff.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    check_in: Mapped[time | None] = mapped_column(Time, nullable=True)
    check_out: Mapped[time | None] = mapped_column(Time, nullable=True)
