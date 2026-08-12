import uuid

from sqlalchemy import Boolean, CheckConstraint, Float, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class AIModuleConfig(Base):
    """Matches src/types/index.ts `AIModule`. This is a REGISTRY, not an
    inference engine — it tracks which of the TT hujjat's 25 criteria are
    configured and enabled, and holds the knobs (threshold, sensitivity)
    an admin can tune. Actually detecting things in video (the `method`
    column describes what model *would* run) is a separate, much larger
    ML engineering effort — see README note in this module's router.
    """

    __tablename__ = "ai_modules"
    __table_args__ = (
        CheckConstraint("\"group\" IN ('A', 'B', 'C', 'D', 'E', 'F')", name="ck_ai_modules_group"),
        CheckConstraint("sensitivity IN ('past', 'o''rta', 'yuqori')", name="ck_ai_modules_sensitivity"),
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
