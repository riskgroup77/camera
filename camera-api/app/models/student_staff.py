import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.org import Faculty


class StudentStaff(Base):
    __tablename__ = "students_staff"
    __table_args__ = (
        CheckConstraint("type IN ('talaba', 'xodim')", name="ck_students_staff_type"),
        CheckConstraint(
            "biometrics_status IN ('tasdiqlangan', 'kutilmoqda', 'yoq')",
            name="ck_students_staff_biometrics_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    # Used only to self-identify for the public self-service face-enrollment
    # flow (app/routers/enrollment.py) — an admin-imported record has no
    # login/password, so passport series+number is the one piece of
    # information the person themselves can supply to prove "this row is
    # me". Uzbek passport format: 2-letter series (e.g. "AD") + 7-digit
    # number. Nullable — existing/bulk-imported rows won't have this until
    # the Excel import that populates it is run.
    passport_series: Mapped[str | None] = mapped_column(String(4), nullable=True)
    passport_number: Mapped[str | None] = mapped_column(String(10), nullable=True)
    faculty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("faculties.id", ondelete="SET NULL"), nullable=True, index=True
    )
    group_or_position: Mapped[str] = mapped_column(String, nullable=False)
    biometrics_status: Mapped[str] = mapped_column(String, nullable=False, default="yoq")
    # S3/MinIO object key (not a URL — presigned URLs expire, so the key is
    # the stable handle and app/routers/students_staff.py generates a fresh
    # presigned URL on every read). embedding is the raw 512-d ArcFace
    # vector from app/services/face_recognition.py, JSON-encoded — no
    # pgvector extension is set up, so this is stored for future use
    # (e.g. a real "search by face" feature) rather than queried today.
    biometric_photo_key: Mapped[str | None] = mapped_column(String, nullable=True)
    biometric_embedding: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    faculty: Mapped[Faculty | None] = relationship("Faculty", lazy="joined")
