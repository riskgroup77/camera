from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Permission(Base):
    __tablename__ = "permissions"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    super_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # "Kamera mas'uli" roli (2026-09-16): kamera ma'lumotlarini —
    # binosi, qavati, zonasi, nomi — to'g'rilaydigan xodimlar. Ular
    # kamera qo'sha olmaydi, o'chira olmaydi va ulanish sozlamalariga
    # (IP, port, RTSP, login/parol) umuman tegmaydi.
    camera_steward: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
