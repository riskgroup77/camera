import uuid
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RevokedToken(Base):
    """Logout blocklist — a JWT's own `jti` claim lands here until the token's
    natural expiry, at which point app.jobs.cleanup removes the row (it's
    already unusable via exp, so keeping it around forever is pointless)."""

    __tablename__ = "revoked_tokens"

    jti: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
