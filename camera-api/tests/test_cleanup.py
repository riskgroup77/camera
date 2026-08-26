import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.cleanup import run_cleanup_once
from app.models import AuditLog, PasswordResetToken, RevokedToken, User


@pytest.mark.usefixtures("seeded")
class TestCleanup:
    async def test_removes_expired_revoked_token_keeps_active_one(self, db_session: AsyncSession):
        now = datetime.now(timezone.utc)
        expired = RevokedToken(jti=uuid.uuid4(), expires_at=now - timedelta(hours=1))
        active = RevokedToken(jti=uuid.uuid4(), expires_at=now + timedelta(hours=1))
        db_session.add_all([expired, active])
        await db_session.commit()

        counts = await run_cleanup_once(db_session)
        assert counts["revoked_tokens"] == 1

        remaining = (await db_session.execute(select(RevokedToken))).scalars().all()
        assert len(remaining) == 1
        assert remaining[0].jti == active.jti

    async def test_removes_expired_and_used_reset_tokens_keeps_valid_one(self, db_session: AsyncSession):
        admin = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
        now = datetime.now(timezone.utc)
        expired = PasswordResetToken(
            user_id=admin.id, token_hash="expired-hash", expires_at=now - timedelta(minutes=1)
        )
        used = PasswordResetToken(
            user_id=admin.id, token_hash="used-hash", expires_at=now + timedelta(minutes=30), used_at=now
        )
        valid = PasswordResetToken(
            user_id=admin.id, token_hash="valid-hash", expires_at=now + timedelta(minutes=30)
        )
        db_session.add_all([expired, used, valid])
        await db_session.commit()

        counts = await run_cleanup_once(db_session)
        assert counts["password_reset_tokens"] == 2

        remaining = (await db_session.execute(select(PasswordResetToken))).scalars().all()
        assert len(remaining) == 1
        assert remaining[0].token_hash == "valid-hash"

    async def test_removes_audit_logs_past_retention_keeps_recent_one(self, db_session: AsyncSession):
        now = datetime.now(timezone.utc)
        old = AuditLog(
            user_name="Eski", action="X", module="Test", status="muvaffaqiyatli", ip="1.1.1.1",
            occurred_at=now - timedelta(days=91),
        )
        recent = AuditLog(
            user_name="Yangi", action="Y", module="Test", status="muvaffaqiyatli", ip="1.1.1.1",
            occurred_at=now - timedelta(days=1),
        )
        db_session.add_all([old, recent])
        await db_session.commit()

        counts = await run_cleanup_once(db_session)
        assert counts["audit_logs"] == 1

        remaining = (await db_session.execute(select(AuditLog))).scalars().all()
        assert len(remaining) == 1
        assert remaining[0].user_name == "Yangi"

    async def test_no_op_when_nothing_expired(self, db_session: AsyncSession):
        counts = await run_cleanup_once(db_session)
        assert counts == {"revoked_tokens": 0, "password_reset_tokens": 0, "audit_logs": 0, "events": 0}
