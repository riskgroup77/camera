import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.jobs import cleanup
from app.jobs.cleanup import run_cleanup_once
from app.models import AuditLog, Camera, Event, PasswordResetToken, RevokedToken, User


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
        assert counts == {
            "revoked_tokens": 0,
            "password_reset_tokens": 0,
            "audit_logs": 0,
            "events": 0,
            "event_snapshots": 0,
        }

    async def test_purged_events_take_their_snapshots_with_them(
        self, db_session: AsyncSession, monkeypatch
    ):
        """The retention purge used to delete Event rows and leave their
        MinIO objects behind forever — app/storage.py's delete_file() had
        no caller anywhere in the codebase, so every expired event leaked
        its JPEG. Storage is the one thing here with no natural bound, so
        this is the test that keeps that path wired."""
        deleted_keys: list[str] = []

        async def fake_delete(keys):
            collected = [k for k in keys if k]
            deleted_keys.extend(collected)
            return len(collected)

        monkeypatch.setattr(cleanup, "delete_files_quietly", fake_delete)

        camera = (await db_session.execute(select(Camera))).scalars().first()
        old = datetime.now(timezone.utc) - timedelta(days=settings.event_retention_days + 1)
        expired_with_snapshot = Event(
            camera_id=camera.id if camera else None, camera_name="Kamera", building="Bino",
            module_code=1, module_name="Test", group="A", confidence=70, severity="yuqori",
            status="yangi", occurred_at=old, snapshot_key="events/expired-one.jpg",
        )
        expired_without_snapshot = Event(
            camera_id=camera.id if camera else None, camera_name="Kamera", building="Bino",
            module_code=1, module_name="Test", group="A", confidence=70, severity="yuqori",
            status="yangi", occurred_at=old, snapshot_key=None,
        )
        recent = Event(
            camera_id=camera.id if camera else None, camera_name="Kamera", building="Bino",
            module_code=1, module_name="Test", group="A", confidence=70, severity="yuqori",
            status="yangi", snapshot_key="events/still-referenced.jpg",
        )
        db_session.add_all([expired_with_snapshot, expired_without_snapshot, recent])
        await db_session.commit()

        counts = await run_cleanup_once(db_session)

        assert counts["events"] == 2
        assert counts["event_snapshots"] == 1
        # Only the expired event's object is removed — the live event's
        # snapshot is still referenced by a row and must survive.
        assert deleted_keys == ["events/expired-one.jpg"]
        surviving = (await db_session.execute(select(Event))).scalars().all()
        assert [e.snapshot_key for e in surviving] == ["events/still-referenced.jpg"]
