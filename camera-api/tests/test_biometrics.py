from pathlib import Path

import insightface
import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers

# Bundled with the insightface package itself (used in its own examples) —
# a real photo with a detectable face, so this test exercises the actual
# ONNX detection+embedding pipeline instead of a synthetic image.
FACE_IMAGE_PATH = Path(insightface.__file__).parent / "data" / "images" / "t1.jpg"


@pytest.fixture
async def a_student(client: AsyncClient, seeded):
    headers = await auth_headers(client, "admin", "admin123")
    resp = await client.post(
        "/api/students-staff",
        headers=headers,
        json={"fullName": "Biometrika Talaba", "type": "talaba", "faculty": "Davolash ishi", "groupOrPosition": "1"},
    )
    return resp.json()


@pytest.mark.usefixtures("seeded")
class TestBiometricsEnrollment:
    async def test_enroll_persists_photo_and_marks_confirmed(self, client: AsyncClient, a_student):
        headers = await auth_headers(client, "admin", "admin123")
        assert a_student["biometricsStatus"] == "yoq"
        assert a_student["biometricPhotoUrl"] is None

        with open(FACE_IMAGE_PATH, "rb") as f:
            resp = await client.post(
                f"/api/students-staff/{a_student['id']}/biometrics",
                headers=headers,
                files={"photo": ("face.jpg", f, "image/jpeg")},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["biometricsStatus"] == "tasdiqlangan"
        assert body["biometricPhotoUrl"] is not None
        assert body["biometricPhotoUrl"].startswith("http")

    async def test_enroll_unknown_student_is_404(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        with open(FACE_IMAGE_PATH, "rb") as f:
            resp = await client.post(
                "/api/students-staff/00000000-0000-0000-0000-000000000000/biometrics",
                headers=headers,
                files={"photo": ("face.jpg", f, "image/jpeg")},
            )
        assert resp.status_code == 404

    async def test_enroll_with_no_face_is_422(self, client: AsyncClient, a_student):
        headers = await auth_headers(client, "admin", "admin123")
        blank = bytes([255] * 100 * 100 * 3)  # solid-color RGB block, no face
        import io

        from PIL import Image

        img = Image.frombytes("RGB", (100, 100), blank)
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        buf.seek(0)

        resp = await client.post(
            f"/api/students-staff/{a_student['id']}/biometrics",
            headers=headers,
            files={"photo": ("blank.jpg", buf, "image/jpeg")},
        )
        assert resp.status_code == 422
