import uuid

from sqlalchemy import ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Faculty(Base):
    __tablename__ = "faculties"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    course_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    student_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class StudentGroup(Base):
    __tablename__ = "student_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String, nullable=False)
    faculty_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("faculties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course: Mapped[int] = mapped_column(Integer, nullable=False)
    student_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    faculty: Mapped["Faculty"] = relationship("Faculty", lazy="joined")


class Department(Base):
    """Kafedra — bino ichidagi tashkiliy bo'linma.

    Kameralar bino bo'yicha guruhlangan edi, lekin bitta binoda o'nlab
    kafedra joylashgan va operator "Biofizika kafedrasi kameralari" ni
    ko'rmoqchi bo'lganda butun binoni varaqlashiga to'g'ri kelardi.

    Binoga bog'langan, chunki kafedra jismonan bitta binoda joylashadi;
    kamerada esa ikkisi ham alohida saqlanadi (Camera.building_id va
    Camera.department_id), shunda kafedrasi belgilanmagan kamera ham
    bino bo'yicha filtrlanaveradi."""

    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String, nullable=False)
    building_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("buildings.id", ondelete="SET NULL"), nullable=True, index=True
    )

    building: Mapped["Building | None"] = relationship("Building", lazy="joined")


class Building(Base):
    __tablename__ = "buildings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    camera_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
