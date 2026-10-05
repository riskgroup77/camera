from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class AttendancePolicy(Base):
    """Kelib-ketish qoidalari — bitta qator (id=1), admin UI'dan o'zgartiradi.

    Kech qolish: kunning birinchi ko'rinishi (istalgan kamera yoki turniket)
    ish boshlanishi + grace_minutes dan keyin bo'lsa — "kech_keldi"."""

    __tablename__ = "attendance_policy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    staff_start: Mapped[time] = mapped_column(Time, nullable=False)
    student_start: Mapped[time] = mapped_column(Time, nullable=False)
    grace_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    work_end: Mapped[time] = mapped_column(Time, nullable=False)
    # ISO hafta kunlari, vergul bilan: "1,2,3,4,5,6" (Du..Sha).
    work_days: Mapped[str] = mapped_column(String, nullable=False)
    # Kunning oxirgi ko'rinishi (istalgan kamera) check_out ga yoziladimi.
    track_last_seen: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Holiday(Base):
    """Ish kuni bo'lmagan sana (bayram, qo'shimcha dam olish) — Sozlamalar →
    Ish vaqti. Bu kunda hech kim "kelmadi" yoki "kech keldi" deb yozilmaydi."""

    __tablename__ = "holidays"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
