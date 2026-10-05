import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import PasswordResetToken, User
from tests.conftest import login


@pytest.mark.usefixtures("seeded")
class TestPasswordReset:
    async def test_forgot_password_unknown_login_is_still_204(self, client: AsyncClient):
        """Must not leak whether an account exists."""
        resp = await client.post("/api/auth/forgot-password", json={"login": "nobody"})
        assert resp.status_code == 204

    async def test_forgot_password_creates_a_real_token(self, client: AsyncClient, db_session):
        resp = await client.post("/api/auth/forgot-password", json={"login": "admin"})
        assert resp.status_code == 204

        user = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
        tokens = (
            (await db_session.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)))
            .scalars()
            .all()
        )
        assert len(tokens) == 1
        assert tokens[0].used_at is None
        assert tokens[0].expires_at > datetime.now(timezone.utc)

    async def test_reset_password_with_valid_token_changes_password(self, client: AsyncClient, db_session):
        await client.post("/api/auth/forgot-password", json={"login": "admin"})
        user = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
        token_row = (
            await db_session.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
        ).scalar_one()

        # Test faqat hash'ni biladi — xom tokenni email/log orqali "olamiz"
        # deb faraz qilib, uni topish uchun hashni qayta hisoblab bo'lmaydi
        # (bu ataylab shunday — sha256 qaytarib bo'lmaydi). Shu sabab bu test
        # forgot-password javobidan xom tokenni to'g'ridan-to'g'ri ololmaydi;
        # shuning uchun token yaratishni qo'lda, xom qiymatini bilgan holda,
        # takrorlaymiz.
        raw_token = "test-raw-token-value"
        token_row.token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        await db_session.commit()

        resp = await client.post(
            "/api/auth/reset-password", json={"token": raw_token, "newPassword": "yangi-parol-123"}
        )
        assert resp.status_code == 204

        # Eski parol endi ishlamaydi, yangisi ishlaydi.
        assert (await client.post("/api/auth/login", json={"login": "admin", "password": "admin123"})).status_code == 401
        ok = await client.post("/api/auth/login", json={"login": "admin", "password": "yangi-parol-123"})
        assert ok.status_code == 200

    async def test_reset_password_invalidates_existing_sessions(self, client: AsyncClient, db_session):
        old_token = await login(client, "admin", "admin123")
        assert (await client.get("/api/users", headers={"Authorization": f"Bearer {old_token}"})).status_code == 200

        await client.post("/api/auth/forgot-password", json={"login": "admin"})
        user = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
        token_row = (
            await db_session.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
        ).scalar_one()
        raw_token = "another-raw-token"
        token_row.token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        await db_session.commit()

        await client.post("/api/auth/reset-password", json={"token": raw_token, "newPassword": "yangi-parol-456"})

        resp = await client.get("/api/users", headers={"Authorization": f"Bearer {old_token}"})
        assert resp.status_code == 401

    async def test_reset_password_token_is_single_use(self, client: AsyncClient, db_session):
        await client.post("/api/auth/forgot-password", json={"login": "admin"})
        user = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
        token_row = (
            await db_session.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
        ).scalar_one()
        raw_token = "single-use-token"
        token_row.token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        await db_session.commit()

        first = await client.post("/api/auth/reset-password", json={"token": raw_token, "newPassword": "birinchi-parol1"})
        assert first.status_code == 204

        second = await client.post("/api/auth/reset-password", json={"token": raw_token, "newPassword": "ikkinchi-parol2"})
        assert second.status_code == 400

    async def test_reset_password_expired_token_is_rejected(self, client: AsyncClient, db_session):
        user = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
        raw_token = "expired-token"
        db_session.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        )
        await db_session.commit()

        resp = await client.post("/api/auth/reset-password", json={"token": raw_token, "newPassword": "yangi-parol-789"})
        assert resp.status_code == 400

    async def test_reset_password_unknown_token_is_rejected(self, client: AsyncClient):
        resp = await client.post(
            "/api/auth/reset-password", json={"token": "does-not-exist", "newPassword": "yangi-parol-000"}
        )
        assert resp.status_code == 400

    async def test_sixth_rapid_reset_attempt_is_rate_limited(self, client: AsyncClient):
        for _ in range(5):
            await client.post(
                "/api/auth/reset-password", json={"token": "does-not-exist", "newPassword": "yangi-parol-000"}
            )
        resp = await client.post(
            "/api/auth/reset-password", json={"token": "does-not-exist", "newPassword": "yangi-parol-000"}
        )
        assert resp.status_code == 429
