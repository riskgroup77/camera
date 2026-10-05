import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Camera
from tests.conftest import auth_headers

_HEADER = "Device Type,Status,IPv4 Address,MAC Address,Device Serial Number"


def _csv(*rows: str) -> bytes:
    return "\n".join([_HEADER, *rows]).encode("utf-8")


@pytest.mark.usefixtures("seeded")
class TestCameraImport:
    async def test_imports_active_cameras(self, client: AsyncClient, db_session):
        headers = await auth_headers(client, "admin", "admin123")
        body = _csv(
            "IPC-T280HA-LUF/SL,Active,192.168.0.84,cc-13-f3-52-f2-c9,SERIAL1",
            "DS-2CD1047G3-LIU,Active,192.168.0.47,8c-22-d2-4f-4e-6d,SERIAL2",
        )
        resp = await client.post(
            "/api/cameras/import", headers=headers, files={"file": ("sadp.csv", body, "text/csv")}
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["imported"] == 2
        assert result["skipped"] == 0
        assert result["skippedRecorders"] == 0

        cameras = (await db_session.execute(select(Camera).where(Camera.mac_address.is_not(None)))).scalars().all()
        assert len(cameras) == 2
        imported = next(c for c in cameras if c.mac_address == "cc-13-f3-52-f2-c9")
        assert imported.ip == "192.168.0.84"
        assert imported.zone == "Tasniflanmagan"
        assert imported.status == "nofaol"
        assert imported.building_id is None

    async def test_skips_non_active_devices(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        body = _csv("IPC-T280HA-LUF/SL,Inactive,192.168.0.84,cc-13-f3-52-f2-c9,SERIAL1")
        resp = await client.post(
            "/api/cameras/import", headers=headers, files={"file": ("sadp.csv", body, "text/csv")}
        )
        result = resp.json()
        assert result["imported"] == 0
        assert result["skipped"] == 1

    async def test_skips_recorders_separately(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        body = _csv(
            "DS-96256NXI-S16,Active,192.168.0.94,04-ee-cd-2d-02-cb,SERIAL1",  # NVR, not a camera
            "IPC-T280HA-LUF/SL,Active,192.168.0.84,cc-13-f3-52-f2-c9,SERIAL2",
        )
        resp = await client.post(
            "/api/cameras/import", headers=headers, files={"file": ("sadp.csv", body, "text/csv")}
        )
        result = resp.json()
        assert result["imported"] == 1
        assert result["skippedRecorders"] == 1

    async def test_reimport_dedupes_by_mac_not_ip(self, client: AsyncClient):
        """The whole reason dedup keys on MAC: SADP re-scans can show the
        same physical camera under a different IP (DHCP renewal, or an
        admin reassigning it by hand) — a second import of that camera
        must not create a duplicate row."""
        headers = await auth_headers(client, "admin", "admin123")
        first = _csv("IPC-T280HA-LUF/SL,Active,192.168.0.84,cc-13-f3-52-f2-c9,SERIAL1")
        await client.post("/api/cameras/import", headers=headers, files={"file": ("sadp.csv", first, "text/csv")})

        second = _csv("IPC-T280HA-LUF/SL,Active,192.168.0.199,cc-13-f3-52-f2-c9,SERIAL1")  # same MAC, new IP
        resp = await client.post(
            "/api/cameras/import", headers=headers, files={"file": ("sadp.csv", second, "text/csv")}
        )
        result = resp.json()
        assert result["imported"] == 0
        assert result["skipped"] == 1

    async def test_missing_required_column_is_a_top_level_error(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        body = b"Device Type,Status\nIPC-T280HA-LUF/SL,Active"
        resp = await client.post(
            "/api/cameras/import", headers=headers, files={"file": ("sadp.csv", body, "text/csv")}
        )
        result = resp.json()
        assert result["imported"] == 0
        assert len(result["errors"]) == 1
        assert "ipv4_address" in result["errors"][0]["message"] or "mac_address" in result["errors"][0]["message"]
