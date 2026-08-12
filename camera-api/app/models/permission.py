from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Permission(Base):
    __tablename__ = "permissions"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    super_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
