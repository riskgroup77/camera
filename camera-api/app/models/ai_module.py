import uuid

from sqlalchemy import Boolean, CheckConstraint, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class AIModuleConfig(Base):
    """Matches src/types/index.ts `AIModule`. Tracks which of the TT
    hujjat's 25 criteria are configured/enabled and holds the knobs
    (threshold, sensitivity) an admin can tune; `active` is enforced by
    every app/jobs/*.py sweep loop via app/jobs/module_status.py. See
    `has_detector` for which rows actually have detection code behind
    them — see README note in this module's router for the full picture.
    """

    __tablename__ = "ai_modules"
    __table_args__ = (
        CheckConstraint("\"group\" IN ('A', 'B', 'C', 'D', 'E', 'F')", name="ck_ai_modules_group"),
        CheckConstraint("sensitivity IN ('past', 'o''rta', 'yuqori')", name="ck_ai_modules_sensitivity"),
        CheckConstraint("mode IN ('ishchi', 'sinov')", name="ck_ai_modules_mode"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    code: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    group: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    method: Mapped[str] = mapped_column(String, nullable=False)
    accuracy: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=75)
    sensitivity: Mapped[str] = mapped_column(String, nullable=False, default="o'rta")
    camera_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # True for every criterion that has a real app/jobs/*.py sweep behind
    # it (heuristic/unvalidated is fine — accuracy=0 just means nobody's
    # measured it against ground truth yet). False only for the handful
    # (PPE, smoking, general dress-code) that are pure registry
    # rows with no detector written at all — see app/seed.py.
    has_detector: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # ishchi — signallar operator navbatiga tushadi. sinov — kalibrlanmagan
    # detektor: signal yoziladi (events.is_trial), lekin navbat,
    # ogohlantirish va hisobotlarga chiqmaydi, faqat namuna sifatida
    # baholanadi (app/services/event_bus.py, app/routers/ai_modules.py).
    mode: Mapped[str] = mapped_column(String, nullable=False, default="ishchi", server_default="ishchi")
    # Operator ko'rsatmasi (SOP): har qatorda bitta qadam. NULL — kodda
    # yozilgan standart matn (app/services/sop.py) ishlatiladi, shuning
    # uchun standartni yaxshilash bazani qayta yozishni talab qilmaydi.
    sop: Mapped[str | None] = mapped_column(Text, nullable=True)
