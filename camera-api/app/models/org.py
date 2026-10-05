import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, SmallInteger, String, func, true
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

    # Binodagi qavatlar soni. Kamerasi hali biriktirilmagan qavat ham
    # kampus kesimida ko'rinishi uchun kerak: aks holda 5 qavatli bino
    # 2 qavatli bo'lib ko'rinardi. NULL = noma'lum, u holda kesim faqat
    # kameralari bor qavatlarni chizadi.
    floors: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # Ro'yxat tartibi: nom bo'yicha saralash "10-bino"ni "2-bino"dan
    # oldin qo'yadi. Migratsiya nomdagi raqamdan to'ldiradi, admin
    # keyin qo'lda o'zgartirishi mumkin.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class OrgUnit(Base):
    """Institut tuzilmasi — HEMIS department-list dan (app/services/org_structure.py).

    Rektorat, fakultetlar (dekanat), kafedralar (fakultetga bo'ysunadi),
    bo'limlar, markazlar, boshqarma, talabalar turar joylari va boshqalar.
    Xodim StudentStaff.org_unit_id orqali bog'lanadi; HEMIS'da yo'q xodim
    bo'lim nomi bo'yicha (matn) bog'lanadi yoki bog'lanmay qoladi.

    kind: rektorat | fakultet | oquv (magistratura, ordinatura, malaka
    oshirish) | kafedra | boshqarma | bolim | markaz | turar_joy | boshqa."""

    __tablename__ = "org_units"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    hemis_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="boshqa")
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_units.id", ondelete="SET NULL"), nullable=True, index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
