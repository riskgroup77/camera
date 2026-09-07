import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


class LessonAttendance(Base):
    """DARS bo'yicha davomat — bitta (dars, talaba) juftligi uchun bitta qator.

    AttendanceRecord dan farqi tub: u kun bo'yicha bitta qator saqlaydi va
    "bugun binoda ko'rindimi" degan savolga javob beradi. Institut esa
    aslida boshqa narsani so'raydi: "bu talaba SHU DARSDA bo'ldimi".
    Kirish eshigidan o'tib, keyin darsga kirmagan odam kun bo'yicha
    "keldi", dars bo'yicha esa "kelmadi" — ikkalasi ham to'g'ri javob,
    lekin ular boshqa-boshqa savollarga.

    Ma'lumot dars jadvalidan (LessonSession) keladi va uni to'ldirish
    uchun BITTA HAM qo'shimcha kamera so'rovi qilinmaydi:
    app/jobs/lesson_quality_ai.py allaqachon har bir faol darsning
    kamerasidan kadr olib, undagi yuzlarni ro'yxatdagi odamlar bilan
    solishtiradi (#19 diqqat balli uchun). Shu solishtiruv natijasi
    endi ikkinchi marta ishlatiladi.

    `sightings` — talaba dars davomida necha marta ko'ringani. Bu shunchaki
    statistika emas: bitta tasodifiy moslik (yonidan o'tib ketgan odam,
    yoki yuz mosligining xatosi) bilan haqiqiy ishtirokni ajratish uchun
    kerak — settings.lesson_attendance_min_sightings dan kam ko'ringan
    talaba "keldi" deb hisoblanmaydi.

    `status` faqat dars TUGAGANDAN keyin yoziladi
    (app/jobs/lesson_attendance.py). Dars davom etayotganda hali
    ko'rinmagan talabani "kelmadi" deb belgilash yolg'on bo'lardi — u
    kechikayotgan bo'lishi mumkin. Shu sabab dars vaqtida bu jadvalda
    faqat KO'RINGAN talabalar qatori bo'ladi, `status` esa NULL.
    """

    __tablename__ = "lesson_attendance"
    __table_args__ = (
        CheckConstraint(
            "status IS NULL OR status IN ('keldi', 'kech_keldi', 'kelmadi')",
            name="ck_lesson_attendance_status",
        ),
        UniqueConstraint("lesson_session_id", "student_staff_id", name="uq_lesson_attendance_person"),
        # Bitta darsning butun ro'yxatini o'qish — eng tez-tez so'rov
        # (hisobot, dars kartochkasi, yakunlash ishi).
        Index("ix_lesson_attendance_session", "lesson_session_id"),
        # Bitta talabaning davomat tarixi — "kim qaysi darslarni qoldirdi".
        Index("ix_lesson_attendance_student", "student_staff_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    lesson_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lesson_sessions.id", ondelete="CASCADE"), nullable=False
    )
    student_staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students_staff.id", ondelete="CASCADE"), nullable=False
    )

    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sightings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str | None] = mapped_column(String, nullable=True)

    lesson: Mapped["LessonSession"] = relationship("LessonSession", lazy="selectin")
    student: Mapped["StudentStaff"] = relationship("StudentStaff", lazy="selectin")
