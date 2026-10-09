"""iMentor integratsiya API (app/routers/integration_v1.py).

Bazasiz: qidiruv va yuz funksiyalari soxtalashtiriladi — tekshirilayotgani
kalit, IP, rate limit, so'rov/javob shakli, xato kodlari va audit yozuvi."""

import base64
import types
import uuid

import numpy as np
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.database import get_db
from app.routers import integration_v1 as api
from app.services import integration_students as svc

pytestmark = pytest.mark.anyio

KEY = "test-integration-key-0123456789"
PINFL = "12345678901234"
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _person(**extra):
    faculty = types.SimpleNamespace(name="Davolash ishi fakulteti")
    base = dict(id=uuid.uuid4(), full_name="Aliyev Vali Karimovich", hemis_id="344261100001", pinfl=PINFL,
                group_or_position="6-kurs, DI-2021", faculty=faculty, active=True,
                hemis_photo_url="https://hemis.example/p.jpg")
    base.update(extra)
    return types.SimpleNamespace(**base)


@pytest.fixture
def audit(monkeypatch):
    lines: list[tuple[str, bool]] = []

    async def fake_audit(_request, action, ok):
        lines.append((action, ok))

    monkeypatch.setattr(api, "_audit", fake_audit)
    return lines


@pytest.fixture
async def client(monkeypatch, audit):
    monkeypatch.setattr(settings, "camfermi_integration_key", KEY)
    monkeypatch.setattr(settings, "integration_allowed_ips", "")
    monkeypatch.setattr(settings, "integration_rate_limit_per_minute", 60)
    monkeypatch.setattr(settings, "redis_url", "")
    api.reset_limiter_for_tests()
    app = FastAPI()
    app.include_router(api.router)
    app.add_exception_handler(api.IntegrationError, api.integration_error_handler)

    async def no_db():
        yield None

    app.dependency_overrides[get_db] = no_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    api.reset_limiter_for_tests()


H = {"X-API-Key": KEY}


# ── Kalit, IP, rate limit ───────────────────────────────────────────────────

async def test_health_ok(client):
    r = await client.get("/api/v1/integration/health", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "ok"


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}, {"X-API-Key": KEY + "x"}])
async def test_wrong_or_missing_key_is_401(client, audit, headers):
    for method, path in (("get", "/health"), ("post", "/students/lookup"), ("post", "/students/face-identify")):
        r = await getattr(client, method)(f"/api/v1/integration{path}", headers=headers)
        assert r.status_code == 401 and r.json()["code"] == "unauthorized"
    assert audit and all(not ok for _, ok in audit)


async def test_empty_server_key_disables_the_api(client, monkeypatch):
    monkeypatch.setattr(settings, "camfermi_integration_key", "")
    r = await client.get("/api/v1/integration/health", headers={"X-API-Key": ""})
    assert r.status_code == 401


async def test_ip_allowlist(client, monkeypatch):
    monkeypatch.setattr(settings, "integration_allowed_ips", "10.0.0.0/8, 192.168.1.5")
    r = await client.get("/api/v1/integration/health", headers=H)  # ASGI test client — 127.0.0.1
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    monkeypatch.setattr(settings, "integration_allowed_ips", "127.0.0.1")
    assert (await client.get("/api/v1/integration/health", headers=H)).status_code == 200


async def test_rate_limit_per_key(client, monkeypatch):
    monkeypatch.setattr(settings, "integration_rate_limit_per_minute", 2)
    codes = [(await client.get("/api/v1/integration/health", headers=H)).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    r = await client.get("/api/v1/integration/health", headers=H)
    assert r.json()["code"] == "rate_limited"


# ── Lookup ──────────────────────────────────────────────────────────────────

async def test_lookup_by_student_id_found(client, monkeypatch, audit):
    async def fake(_db, student_id):
        return _person() if student_id == "344261100001" else None

    monkeypatch.setattr(svc, "find_by_student_id", fake)
    r = await client.post("/api/v1/integration/students/lookup", headers=H, json={"student_id": "344261100001"})
    assert r.status_code == 200
    body = r.json()
    assert body["matched_by"] == "student_id" and "confidence" not in body
    assert body["first_name"] == "Vali" and body["last_name"] == "Aliyev" and body["middle_name"] == "Karimovich"
    assert body["group_name"] == "DI-2021" and body["course"] == 6 and body["status"] == "active"
    assert body["specialty"] is None and body["education_form"] is None
    assert audit[-1] == ("lookup student_id=344261100001: topildi", True)


async def test_lookup_by_pinfl_found_and_audit_masks_pinfl(client, monkeypatch, audit):
    async def fake(_db, pinfl):
        return _person(active=False) if pinfl == PINFL else None

    monkeypatch.setattr(svc, "find_by_pinfl", fake)
    r = await client.post("/api/v1/integration/students/lookup", headers=H, json={"pinfl": PINFL})
    assert r.status_code == 200 and r.json()["matched_by"] == "pinfl" and r.json()["status"] == "inactive"
    action = audit[-1][0]
    assert PINFL not in action and "1234********34" in action


async def test_lookup_not_found(client, monkeypatch):
    async def none(*_):
        return None

    monkeypatch.setattr(svc, "find_by_student_id", none)
    monkeypatch.setattr(svc, "find_by_pinfl", none)
    for body in ({"student_id": "999"}, {"pinfl": "99999999999999"}):
        r = await client.post("/api/v1/integration/students/lookup", headers=H, json=body)
        assert r.status_code == 404 and r.json()["code"] == "not_found"


@pytest.mark.parametrize("pinfl", ["123", "1234567890123a", "123456789012345", " "])
async def test_lookup_invalid_pinfl(client, pinfl):
    r = await client.post("/api/v1/integration/students/lookup", headers=H, json={"pinfl": pinfl})
    assert r.status_code == 400 and r.json()["code"] in ("invalid_pinfl", "invalid_request")


async def test_lookup_needs_exactly_one_identifier(client):
    for body in ({}, {"student_id": "1", "pinfl": PINFL}):
        r = await client.post("/api/v1/integration/students/lookup", headers=H, json=body)
        assert r.status_code == 400 and r.json()["code"] == "invalid_request"


# ── Face identify ───────────────────────────────────────────────────────────

def _face(height, emb=True):
    return types.SimpleNamespace(bbox=np.array([0, 0, height, height], dtype=np.float32),
                                 embedding=np.ones(512, dtype=np.float32) if emb else None)


class _Matrix:
    def __init__(self, match, person_type="talaba"):
        self.match, self.ptype = match, person_type

    def best_matches(self, _embeddings, _threshold, *, margin=0.0):
        return [self.match]

    def person_type(self, _pid):
        return self.ptype


@pytest.fixture
def faces(monkeypatch):
    state = {"faces": [_face(200)], "match": None, "ptype": "talaba", "person": _person()}

    async def fake_detect(_image, **_kw):
        return state["faces"]

    async def fake_matrix(_db):
        return _Matrix(state["match"], state["ptype"])

    async def fake_by_id(_db, _pid):
        return state["person"]

    monkeypatch.setattr(svc, "detect_faces", fake_detect)
    monkeypatch.setattr(svc, "load_candidate_matrix_cached", fake_matrix)
    monkeypatch.setattr(svc, "find_by_id", fake_by_id)
    return state


async def test_face_found_multipart(client, faces):
    faces["match"] = (str(uuid.uuid4()), 0.8123)
    r = await client.post("/api/v1/integration/students/face-identify", headers=H, files={"image": ("a.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 200
    assert r.json()["matched_by"] == "face" and r.json()["confidence"] == 0.812


async def test_face_found_base64_png(client, faces):
    faces["match"] = (str(uuid.uuid4()), 0.7)
    data_url = "data:image/png;base64," + base64.b64encode(PNG).decode()
    r = await client.post("/api/v1/integration/students/face-identify", headers=H, json={"image_base64": data_url})
    assert r.status_code == 200 and r.json()["confidence"] == 0.7


async def test_no_face(client, faces):
    faces["faces"] = []
    r = await client.post("/api/v1/integration/students/face-identify", headers=H, files={"image": ("a.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 422 and r.json()["code"] == "no_face"


async def test_two_faces(client, faces):
    faces["faces"] = [_face(200), _face(150)]
    r = await client.post("/api/v1/integration/students/face-identify", headers=H, files={"image": ("a.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 422 and r.json()["code"] == "multiple_faces"


async def test_tiny_background_face_is_not_a_second_face(client, faces):
    faces["faces"] = [_face(200), _face(40)]
    faces["match"] = (str(uuid.uuid4()), 0.9)
    r = await client.post("/api/v1/integration/students/face-identify", headers=H, files={"image": ("a.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 200


async def test_not_matched_below_threshold_or_staff(client, faces):
    r = await client.post("/api/v1/integration/students/face-identify", headers=H, files={"image": ("a.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 404 and r.json()["code"] == "not_matched"
    faces["match"], faces["ptype"] = (str(uuid.uuid4()), 0.9), "xodim"
    r = await client.post("/api/v1/integration/students/face-identify", headers=H, files={"image": ("a.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 404 and r.json()["code"] == "not_matched"


async def test_rejects_non_image_and_oversize(client, faces, monkeypatch):
    r = await client.post("/api/v1/integration/students/face-identify", headers=H, files={"image": ("a.gif", b"GIF89a" + b"0" * 10, "image/gif")})
    assert r.status_code == 415 and r.json()["code"] == "invalid_image"
    monkeypatch.setattr(settings, "integration_max_image_bytes", 50)
    r = await client.post("/api/v1/integration/students/face-identify", headers=H, files={"image": ("a.jpg", JPEG + b"0" * 100, "image/jpeg")})
    assert r.status_code == 413 and r.json()["code"] == "image_too_large"


# ── Sof funksiyalar ─────────────────────────────────────────────────────────

def test_name_and_group_split():
    assert svc.split_name("Xxx Imran Ahmad Xxx") == ("Imran", "Ahmad", None)
    assert svc.split_name("Kenjayeva Dilbarxon Olimjon qizi") == ("Kenjayeva", "Dilbarxon", "Olimjon qizi")
    assert svc.split_group("3-kurs, TPI-423") == ("TPI-423", 3)
    assert svc.split_group("HEMIS'da topilmadi") == (None, None)
    assert svc.mask_pinfl(PINFL) == "1234********34"
