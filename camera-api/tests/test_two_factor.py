"""Ikki bosqichli kirish (TOTP): yoqish, kirish, qayta ishlatish,
chegaralar, o'chirish va administrator tomonidan bekor qilish."""

import uuid
from datetime import timedelta

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app import security
from app.config import settings
from app.crypto import decrypt
from app.models import Permission, User
from app.services import totp
from tests.conftest import auth_headers, login

pytestmark = pytest.mark.anyio

# Qadam chegarasiga yaqin tushib, test tasodifan yiqilmasin — soat qo'lda.
T0 = 1_900_000_000.0


@pytest.fixture
def clock(monkeypatch):
    state = {"now": T0}
    monkeypatch.setattr(totp, "_clock", lambda: state["now"])

    def advance(seconds: float) -> None:
        state["now"] += seconds

    return advance


def _code(secret: str, offset_steps: int = 0) -> str:
    return totp.code_at(secret, totp.current_step() + offset_steps)


async def _enable(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post("/api/auth/2fa/boshlash", headers=headers)
    assert resp.status_code == 200, resp.text
    secret = resp.json()["secret"]
    resp = await client.post("/api/auth/2fa/tasdiqlash", json={"code": _code(secret)}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["enabled"] is True
    return secret


async def _challenge(client: AsyncClient, login_name: str = "admin", password: str = "admin123") -> str:
    resp = await client.post("/api/auth/login", json={"login": login_name, "password": password})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["twoFactorRequired"] is True
    # Parolning o'zi hech narsa bermaydi: na sessiya, na rol, na ism.
    assert body["token"] is None and body["role"] is None and body["userName"] is None
    return body["challenge"]


class TestTotpAlgorithm:
    def test_rfc6238_reference_vector(self):
        # RFC 6238 A-ilova: "12345678901234567890" sirining SHA1 qiymatlari (oxirgi 6 raqam).
        import base64

        secret = base64.b32encode(b"12345678901234567890").decode()
        assert totp.code_at(secret, 59 // 30) == "287082"
        assert totp.code_at(secret, 1111111109 // 30) == "081804"
        assert totp.code_at(secret, 2000000000 // 30) == "279037"

    def test_drift_window_and_replay(self):
        secret = totp.generate_secret()
        step = totp.current_step(T0)
        assert totp.verify(secret, totp.code_at(secret, step), now=T0) == step
        assert totp.verify(secret, totp.code_at(secret, step - 1), now=T0) == step - 1
        assert totp.verify(secret, totp.code_at(secret, step + 1), now=T0) == step + 1
        assert totp.verify(secret, totp.code_at(secret, step - 2), now=T0) is None
        assert totp.verify(secret, totp.code_at(secret, step), last_step=step, now=T0) is None
        assert totp.verify(secret, "12345", now=T0) is None
        assert totp.verify(secret, "abcdef", now=T0) is None
        code = totp.code_at(secret, step)
        assert totp.verify(secret, f"{code[:3]} {code[3:]}", now=T0) == step

    def test_provisioning_uri(self):
        uri = totp.provisioning_uri("ABC", "admin", "Farg'ona JSSTI")
        assert uri.startswith("otpauth://totp/Farg%27ona%20JSSTI%3Aadmin?")
        assert "secret=ABC" in uri and "digits=6" in uri and "period=30" in uri


class TestEnrollment:
    async def test_begin_stores_encrypted_secret_and_confirm_enables(
        self, client: AsyncClient, db_session, seeded, clock
    ):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post("/api/auth/2fa/boshlash", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["otpauthUri"].startswith("otpauth://totp/")
        assert f"secret={body['secret']}" in body["otpauthUri"]

        user = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
        await db_session.refresh(user)
        # Bazada ochiq holda emas.
        assert user.totp_secret != body["secret"]
        assert decrypt(user.totp_secret) == body["secret"]
        assert user.totp_enabled is False

        # Hali yoqilmagan: login odatdagidek token beradi.
        assert (await client.get("/api/auth/2fa", headers=headers)).json()["enabled"] is False

        bad = await client.post("/api/auth/2fa/tasdiqlash", json={"code": "000000"}, headers=headers)
        assert bad.status_code == 400
        ok = await client.post("/api/auth/2fa/tasdiqlash", json={"code": _code(body["secret"])}, headers=headers)
        assert ok.status_code == 200 and ok.json()["enabled"] is True
        assert (await client.get("/api/auth/2fa", headers=headers)).json()["enabled"] is True

        # Yoqilgan 2FA ustidan qayta boshlash — sirni jimgina almashtirish yo'q.
        again = await client.post("/api/auth/2fa/boshlash", headers=headers)
        assert again.status_code == 409

    async def test_confirm_without_begin_is_400(self, client: AsyncClient, seeded, clock):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post("/api/auth/2fa/tasdiqlash", json={"code": "123456"}, headers=headers)
        assert resp.status_code == 400

    async def test_endpoints_require_session(self, client: AsyncClient, seeded):
        assert (await client.post("/api/auth/2fa/boshlash")).status_code == 401
        assert (await client.post("/api/auth/2fa/tasdiqlash", json={"code": "123456"})).status_code == 401
        assert (await client.post("/api/auth/2fa/ochirish", json={"code": "123456"})).status_code == 401


class TestTwoFactorLogin:
    async def test_happy_path(self, client: AsyncClient, db_session, seeded, clock):
        headers = await auth_headers(client, "admin", "admin123")
        secret = await _enable(client, headers)

        challenge = await _challenge(client)
        clock(30)  # keyingi qadam — tasdiqlashdagi kod bilan to'qnashmasin
        resp = await client.post("/api/auth/2fa/kirish", json={"challenge": challenge, "code": _code(secret)})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["role"] == "super-admin" and body["token"]
        assert body["twoFactorRequired"] is False
        me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
        assert me.status_code == 200

    async def test_challenge_is_not_a_session(self, client: AsyncClient, seeded, clock):
        headers = await auth_headers(client, "admin", "admin123")
        await _enable(client, headers)
        challenge = await _challenge(client)
        resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {challenge}"})
        assert resp.status_code == 401
        resp = await client.get("/api/users", headers={"Authorization": f"Bearer {challenge}"})
        assert resp.status_code == 401

    async def test_purpose_token_signed_with_main_key_is_rejected(self, client: AsyncClient, db_session, seeded):
        user = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
        forged = jwt.encode(
            {"sub": str(user.id), "role": "super-admin", "purpose": "2fa-kirish", "jti": str(uuid.uuid4()), "exp": 9999999999},
            settings.jwt_secret,
            algorithm="HS256",
        )
        resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
        assert resp.status_code == 401

    async def test_access_token_is_not_a_challenge(self, client: AsyncClient, seeded, clock):
        headers = await auth_headers(client, "admin", "admin123")
        secret = await _enable(client, headers)
        access = headers["Authorization"].split()[1]
        clock(30)
        resp = await client.post("/api/auth/2fa/kirish", json={"challenge": access, "code": _code(secret)})
        assert resp.status_code == 401

    async def test_wrong_and_expired_codes(self, client: AsyncClient, seeded, clock):
        headers = await auth_headers(client, "admin", "admin123")
        secret = await _enable(client, headers)
        challenge = await _challenge(client)
        clock(300)

        wrong = await client.post("/api/auth/2fa/kirish", json={"challenge": challenge, "code": "000000"})
        assert wrong.status_code == 401
        # 2 qadam (60 s) oldingi kod — soat farqi oynasidan tashqarida.
        old = await client.post("/api/auth/2fa/kirish", json={"challenge": challenge, "code": _code(secret, -2)})
        assert old.status_code == 401
        # Noto'g'ri kod chaqiruvni kuydirmaydi — to'g'ri kod hali ham o'tadi.
        ok = await client.post("/api/auth/2fa/kirish", json={"challenge": challenge, "code": _code(secret)})
        assert ok.status_code == 200

    async def test_expired_challenge(self, client: AsyncClient, seeded, clock, monkeypatch):
        headers = await auth_headers(client, "admin", "admin123")
        secret = await _enable(client, headers)
        monkeypatch.setattr(security, "TWO_FACTOR_CHALLENGE_TTL", timedelta(seconds=-1))
        challenge = await _challenge(client)
        clock(30)
        resp = await client.post("/api/auth/2fa/kirish", json={"challenge": challenge, "code": _code(secret)})
        assert resp.status_code == 401

    async def test_replayed_challenge_and_replayed_code(self, client: AsyncClient, seeded, clock):
        headers = await auth_headers(client, "admin", "admin123")
        secret = await _enable(client, headers)
        challenge = await _challenge(client)
        clock(30)
        first = await client.post("/api/auth/2fa/kirish", json={"challenge": challenge, "code": _code(secret)})
        assert first.status_code == 200

        # Xuddi shu chaqiruv — keyingi (yangi) kod bilan ham — ikkinchi marta yaramaydi.
        clock(30)
        replay = await client.post("/api/auth/2fa/kirish", json={"challenge": challenge, "code": _code(secret)})
        assert replay.status_code == 401

        # Yangi chaqiruv, lekin allaqachon ishlatilgan kod — rad.
        fresh = await _challenge(client)
        used_code = _code(secret, -1)
        again = await client.post("/api/auth/2fa/kirish", json={"challenge": fresh, "code": used_code})
        assert again.status_code == 401

    async def test_password_change_burns_outstanding_challenge(self, client: AsyncClient, db_session, seeded, clock):
        headers = await auth_headers(client, "admin", "admin123")
        secret = await _enable(client, headers)
        challenge = await _challenge(client)
        user = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
        user.token_version += 1
        await db_session.commit()
        clock(30)
        resp = await client.post("/api/auth/2fa/kirish", json={"challenge": challenge, "code": _code(secret)})
        assert resp.status_code == 401

    async def test_code_attempts_are_rate_limited(self, client: AsyncClient, seeded, clock):
        headers = await auth_headers(client, "admin", "admin123")
        secret = await _enable(client, headers)
        challenge = await _challenge(client)
        statuses = [
            (await client.post("/api/auth/2fa/kirish", json={"challenge": challenge, "code": "000000"})).status_code
            for _ in range(5)
        ]
        assert statuses == [401] * 5
        clock(30)
        blocked = await client.post("/api/auth/2fa/kirish", json={"challenge": challenge, "code": _code(secret)})
        assert blocked.status_code == 429

    async def test_confirm_attempts_are_rate_limited(self, client: AsyncClient, seeded, clock):
        headers = await auth_headers(client, "admin", "admin123")
        await client.post("/api/auth/2fa/boshlash", headers=headers)
        statuses = [
            (await client.post("/api/auth/2fa/tasdiqlash", json={"code": "000000"}, headers=headers)).status_code
            for _ in range(6)
        ]
        assert statuses[:5] == [400] * 5 and statuses[5] == 429

    async def test_users_without_2fa_log_in_as_before(self, client: AsyncClient, seeded):
        resp = await client.post("/api/auth/login", json={"login": "operator", "password": "operator123"})
        body = resp.json()
        assert body["token"] and body["role"] == "admin" and body["twoFactorRequired"] is False
        assert body["challenge"] is None


class TestDisable:
    async def test_self_disable_needs_a_valid_code(self, client: AsyncClient, seeded, clock):
        headers = await auth_headers(client, "admin", "admin123")
        secret = await _enable(client, headers)
        clock(30)
        bad = await client.post("/api/auth/2fa/ochirish", json={"code": "000000"}, headers=headers)
        assert bad.status_code == 400
        ok = await client.post("/api/auth/2fa/ochirish", json={"code": _code(secret)}, headers=headers)
        assert ok.status_code == 200 and ok.json()["enabled"] is False
        # Endi parolning o'zi yetarli.
        assert await login(client, "admin", "admin123")

    async def test_disable_when_not_enabled_is_409(self, client: AsyncClient, seeded):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post("/api/auth/2fa/ochirish", json={"code": "123456"}, headers=headers)
        assert resp.status_code == 409


class TestAdminReset:
    async def test_super_admin_resets_a_users_2fa(self, client: AsyncClient, db_session, seeded, clock):
        op_headers = await auth_headers(client, "operator", "operator123")
        await _enable(client, op_headers)
        operator = (await db_session.execute(select(User).where(User.login == "operator"))).scalar_one()

        admin_headers = await auth_headers(client, "admin", "admin123")
        listed = (await client.get("/api/users", headers=admin_headers)).json()["items"]
        assert next(u for u in listed if u["login"] == "operator")["twoFactorEnabled"] is True

        resp = await client.post(f"/api/users/{operator.id}/2fa/bekor", headers=admin_headers)
        assert resp.status_code == 200 and resp.json()["twoFactorEnabled"] is False
        await db_session.refresh(operator)
        assert operator.totp_secret is None and operator.totp_enabled is False
        # Eski sessiyalar yopildi (telefon o'g'irlangan bo'lishi mumkin).
        assert (await client.get("/api/auth/me", headers=op_headers)).status_code == 401
        # Parol bilan odatdagidek kiradi.
        assert await login(client, "operator", "operator123")

    async def test_reset_requires_manage_roles(self, client: AsyncClient, db_session, seeded):
        admin = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
        op_headers = await auth_headers(client, "operator", "operator123")
        resp = await client.post(f"/api/users/{admin.id}/2fa/bekor", headers=op_headers)
        assert resp.status_code == 403

    async def test_admin_with_manage_roles_cannot_reset_super_admin(self, client: AsyncClient, db_session, seeded):
        perm = (await db_session.execute(select(Permission).where(Permission.key == "manageRoles"))).scalar_one()
        perm.admin = True
        await db_session.commit()
        admin = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
        op_headers = await auth_headers(client, "operator", "operator123")
        resp = await client.post(f"/api/users/{admin.id}/2fa/bekor", headers=op_headers)
        assert resp.status_code == 403

    async def test_unknown_user_is_404(self, client: AsyncClient, seeded):
        headers = await auth_headers(client, "admin", "admin123")
        assert (await client.post("/api/users/not-a-uuid/2fa/bekor", headers=headers)).status_code == 404
        assert (await client.post(f"/api/users/{uuid.uuid4()}/2fa/bekor", headers=headers)).status_code == 404
