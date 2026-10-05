"""Xavfsizlik auditi (2026-09-20) topgan kamchiliklar uchun testlar.

Har bir test aynan bitta teshikni qaytadan ochilib ketishidan saqlaydi —
tavsif esa teshik nimada edi, shuni aytadi.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Permission, User
from app.rtsp import redact_credentials
from app.security import create_access_token
from tests.conftest import ENROLL_CODE, auth_headers, login


# ---------------------------------------------------------------------------
# 1. Rol tokendan emas, bazadan o'qiladi
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_role_change_takes_effect_on_existing_token(
    client: AsyncClient, db_session: AsyncSession, seeded: None
) -> None:
    """Rol pasaytirilganda ESKI token ham darhol kuchini yo'qotadi.

    Ilgari CurrentUser.role JWT ichidagi nusxadan olinardi: lavozimidan
    olingan admin tokeni muddati tugaguncha (12 soat) admin huquqlari
    bilan ishlashda davom etardi."""
    admin = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
    token = create_access_token(str(admin.id), "super-admin", admin.token_version)
    headers = {"Authorization": f"Bearer {token}"}

    assert (await client.get("/api/users", headers=headers)).status_code == 200

    admin.role = "kamera-masuli"
    await db_session.commit()

    # Aynan o'sha token — endi manageRoles huquqi yo'q.
    assert (await client.get("/api/users", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_forged_role_claim_in_token_is_ignored(
    client: AsyncClient, db_session: AsyncSession, seeded: None
) -> None:
    """Tokendagi "role" da'vosi hech narsani hal qilmaydi."""
    operator = (await db_session.execute(select(User).where(User.login == "operator"))).scalar_one()
    operator.role = "kamera-masuli"
    await db_session.commit()

    token = create_access_token(str(operator.id), "super-admin", operator.token_version)
    resp = await client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 2. Rolni ko'tarish (privilege escalation)
# ---------------------------------------------------------------------------


async def _grant_manage_roles_to_admin(db: AsyncSession) -> None:
    permission = (await db.execute(select(Permission).where(Permission.key == "manageRoles"))).scalar_one()
    permission.admin = True
    await db.commit()


@pytest.mark.asyncio
async def test_admin_cannot_create_super_admin(
    client: AsyncClient, db_session: AsyncSession, seeded: None
) -> None:
    """manageRoles berilgan admin o'ziga Super Admin yarata olmaydi."""
    await _grant_manage_roles_to_admin(db_session)
    operator = (await db_session.execute(select(User).where(User.login == "operator"))).scalar_one()
    operator.role = "admin"
    await db_session.commit()

    headers = await auth_headers(client, "operator", "operator123")
    resp = await client.post(
        "/api/users",
        headers=headers,
        json={"login": "yangi", "password": "Parol12345", "name": "Yangi", "role": "Super Admin"},
    )
    assert resp.status_code == 403

    # Pastroq rol esa muammosiz.
    resp = await client.post(
        "/api/users",
        headers=headers,
        json={"login": "yangi", "password": "Parol12345", "name": "Yangi", "role": "Admin"},
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_admin_cannot_promote_self_to_super_admin(
    client: AsyncClient, db_session: AsyncSession, seeded: None
) -> None:
    await _grant_manage_roles_to_admin(db_session)
    operator = (await db_session.execute(select(User).where(User.login == "operator"))).scalar_one()
    operator.role = "admin"
    await db_session.commit()
    operator_id = str(operator.id)

    headers = await auth_headers(client, "operator", "operator123")
    resp = await client.patch(
        f"/api/users/{operator_id}",
        headers=headers,
        json={"login": "operator", "name": "Operator", "role": "Super Admin"},
    )
    assert resp.status_code == 403

    await db_session.refresh(operator)
    assert operator.role == "admin"


@pytest.mark.asyncio
async def test_admin_cannot_touch_super_admin_account(
    client: AsyncClient, db_session: AsyncSession, seeded: None
) -> None:
    """Super Admin hisobining parolini tiklash — hisobni egallash yo'li edi."""
    await _grant_manage_roles_to_admin(db_session)
    operator = (await db_session.execute(select(User).where(User.login == "operator"))).scalar_one()
    operator.role = "admin"
    admin = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
    admin.role = "super-admin"
    await db_session.commit()
    admin_id = str(admin.id)

    headers = await auth_headers(client, "operator", "operator123")
    assert (
        await client.post(
            f"/api/users/{admin_id}/reset-password", headers=headers, json={"newPassword": "Yangiparol1"}
        )
    ).status_code == 403
    assert (await client.delete(f"/api/users/{admin_id}", headers=headers)).status_code == 403
    assert (
        await client.patch(
            f"/api/users/{admin_id}", headers=headers, json={"login": "admin", "name": "Admin Adminov", "role": "Admin"}
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_last_super_admin_cannot_be_demoted(
    client: AsyncClient, db_session: AsyncSession, seeded: None
) -> None:
    """O'chirishda tekshiruv bor edi, tahrirlashda yo'q edi — bitta PATCH
    bilan tizimda huquqlar matritsasini o'zgartiradigan odam qolmasdi."""
    admin = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
    admin.role = "super-admin"
    await db_session.commit()
    admin_id = str(admin.id)

    headers = await auth_headers(client, "admin", "admin123")
    resp = await client.patch(
        f"/api/users/{admin_id}", headers=headers, json={"login": "admin", "name": "Admin", "role": "Admin"}
    )
    assert resp.status_code == 400

    await db_session.refresh(admin)
    assert admin.role == "super-admin"


# ---------------------------------------------------------------------------
# 3. Kamera parolining oqib ketishi
# ---------------------------------------------------------------------------


def test_redact_credentials_hides_camera_password() -> None:
    line = "rtsp://admin:Qwerty123!@10.10.5.7:554/Streaming/Channels/101: 401 Unauthorized"
    redacted = redact_credentials(line)
    assert "Qwerty123!" not in redacted
    assert "admin:" not in redacted
    assert "10.10.5.7:554" in redacted  # diagnostika uchun kerakli qism qoladi


def test_redact_credentials_covers_other_schemes() -> None:
    assert "parol" not in redact_credentials("rtsps://user:parol@host/x")
    assert "parol" not in redact_credentials("http://user:parol@host/x")
    # Kredensialsiz manzil o'zgarmaydi.
    assert redact_credentials("rtsp://10.0.0.1:554/a") == "rtsp://10.0.0.1:554/a"


@pytest.mark.asyncio
async def test_rtsp_probe_error_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    """ffprobe xato satri foydalanuvchiga ko'rsatiladi — parolsiz."""
    import app.services.connectivity as connectivity

    class _Proc:
        returncode = 1

        async def communicate(self):
            return b"", b"rtsp://admin:Maxfiy99@10.0.0.9:554/s1: 401 Unauthorized"

    async def _fake_exec(*_args, **_kwargs):
        return _Proc()

    monkeypatch.setattr(connectivity.asyncio, "create_subprocess_exec", _fake_exec)
    ok, info = await connectivity._rtsp_probe("rtsp://admin:Maxfiy99@10.0.0.9:554/s1")
    assert ok is False
    assert info is not None and "Maxfiy99" not in info


# ---------------------------------------------------------------------------
# 4. Parolni tiklash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_link_is_not_written_to_logs(
    client: AsyncClient, db_session: AsyncSession, seeded: None, caplog: pytest.LogCaptureFixture
) -> None:
    """Emaili yo'q foydalanuvchi uchun havola jurnalga tushmaydi — jurnalni
    o'qigan har kim hisobni egallab olardi."""
    admin = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
    admin.email = None
    await db_session.commit()

    with caplog.at_level("WARNING"):
        resp = await client.post("/api/auth/forgot-password", json={"login": "admin"})
    assert resp.status_code == 204
    text = caplog.text + "".join(str(getattr(r, "reset_link", "")) for r in caplog.records)
    assert "parolni-tiklash?token=" not in text
    assert "reset_link" not in text


@pytest.mark.asyncio
async def test_older_reset_tokens_die_with_the_used_one(
    client: AsyncClient, db_session: AsyncSession, seeded: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ikki marta "parolni unutdim" bosilgan bo'lsa, birinchi havola
    ikkinchisi ishlatilganidan keyin ham amal qilardi."""
    sent: list[str] = []
    import app.routers.auth as auth_router

    monkeypatch.setattr(
        auth_router, "send_password_reset_email", lambda _email, _name, link: sent.append(link)
    )
    admin = (await db_session.execute(select(User).where(User.login == "admin"))).scalar_one()
    admin.email = "admin@example.org"
    await db_session.commit()

    for _ in range(2):
        assert (await client.post("/api/auth/forgot-password", json={"login": "admin"})).status_code == 204
    assert len(sent) == 2
    first, second = (link.split("token=")[1] for link in sent)

    assert (
        await client.post("/api/auth/reset-password", json={"token": second, "newPassword": "Yangiparol1"})
    ).status_code == 204
    # Eski havola endi o'lik.
    resp = await client.post(
        "/api/auth/reset-password", json={"token": first, "newPassword": "Boshqaparol1"}
    )
    assert resp.status_code == 400

    await db_session.refresh(admin)
    token = await login(client, "admin", "Yangiparol1")
    assert token


# ---------------------------------------------------------------------------
# 5. Fail-open sozlamalar ishga tushishda aytiladi
# ---------------------------------------------------------------------------


def test_insecure_config_is_reported() -> None:
    from app.config import settings
    from app.services.security_checks import insecure_config_warnings

    original = (settings.stream_url_secret, settings.public_monitoring_requires_auth)
    try:
        settings.stream_url_secret = ""
        settings.public_monitoring_requires_auth = False
        warnings = insecure_config_warnings()
        assert any("STREAM_URL_SECRET" in w for w in warnings)
        assert any("PUBLIC_MONITORING_REQUIRES_AUTH" in w for w in warnings)

        settings.stream_url_secret = "sir"
        settings.public_monitoring_requires_auth = True
        warnings = insecure_config_warnings()
        assert not any("STREAM_URL_SECRET" in w for w in warnings)
        assert not any("PUBLIC_MONITORING_REQUIRES_AUTH" in w for w in warnings)
    finally:
        settings.stream_url_secret, settings.public_monitoring_requires_auth = original


# ---------------------------------------------------------------------------
# 6. Ochiq endpointlarda noto'g'ri identifikator — 404, 500 emas
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_endpoints_reject_malformed_ids_with_404(
    client: AsyncClient, db_session: AsyncSession, seeded: None
) -> None:
    """Xom satr UUID ustuniga solishtirilganda Postgres "invalid input
    syntax for type uuid" bilan yiqilardi: hisobsiz chaqiruvchi 500 olardi
    va so'rov sessiyasi buzilgan holda qolardi."""
    headers = await auth_headers(client, "admin", "admin123")

    for url in (
        "/api/public/cameras/not-a-uuid/live-detection",
        "/api/public/cameras/not-a-uuid/analysis-status",
        "/api/public/cameras/not-a-uuid/thumbnail",
    ):
        assert (await client.get(url, headers=headers)).status_code == 404, url

    resp = await client.post(
        "/api/public/enrollment/not-a-uuid/submit",
        data={"code": ENROLL_CODE, "pinfl": "12345678901234", "consent": "true"},
        files=[("photos", ("a.jpg", b"not-an-image", "image/jpeg"))],
    )
    # 500 emas. Endi 404 ham emas: yo'q yozuv va noto'g'ri kod AYNAN bir
    # xil javob beradi (403), aks holda identifikatorlarni birma-bir
    # sinab kim bor-yo'qligini aniqlash mumkin bo'lardi.
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_register_with_malformed_faculty_id_is_422_not_500(
    client: AsyncClient, db_session: AsyncSession, seeded: None
) -> None:
    resp = await client.post(
        "/api/public/enrollment/register",
        json={"code": ENROLL_CODE, 
            "fullName": "Test Testov",
            "type": "talaba",
            "groupOrPosition": "101-guruh",
            "facultyId": "not-a-uuid",
            "pinfl": "12345678901234",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_duplicate_passport_does_not_break_lookup(
    client: AsyncClient, db_session: AsyncSession, seeded: None
) -> None:
    """Pasport ustunlarida unikal indeks yo'q. Ilgari ikkita mos yozuv
    bo'lsa /lookup scalar_one_or_none() da yiqilardi — ya'ni o'sha odam
    ro'yxatdan o'ta olmasdi."""
    from datetime import datetime, timedelta, timezone

    from app.models import StudentStaff

    now = datetime.now(timezone.utc)
    for index, offset in enumerate((0, 60)):
        db_session.add(
            StudentStaff(
                full_name=f"Dubl {index}",
                type="talaba",
                group_or_position="101-guruh",
                passport_series="AD",
                passport_number="1234567",
                biometrics_status="yoq",
                created_at=now + timedelta(seconds=offset),
            )
        )
    await db_session.commit()

    resp = await client.post(
        "/api/public/enrollment/lookup",
        json={"code": ENROLL_CODE, "passportSeries": "AD", "passportNumber": "1234567"},
    )
    assert resp.status_code == 200
    # Eng eskisi — barqaror tanlov (har chaqiruvda bir xil yozuv).
    assert resp.json()["fullName"] == "D*** 0"  # ochiq sahifada ism niqoblanadi
