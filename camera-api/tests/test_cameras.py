import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Camera
from tests.conftest import auth_headers


@pytest.mark.usefixtures("seeded")
class TestCameras:
    async def test_create_and_list(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/cameras",
            headers=headers,
            json={
                "name": "Kirish kamerasi",
                "ip": "192.168.1.50",
                "building": "1-Bino (Asosiy korpus)",
                "zone": "A-Zona",
                "resolution": "1080p",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["building"] == "1-Bino (Asosiy korpus)"

        listed = await client.get("/api/cameras", headers=headers)
        assert listed.json()["total"] == 1

    async def test_unknown_building_is_404(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/cameras",
            headers=headers,
            json={"name": "Test kamera", "ip": "10.0.0.1", "building": "Yoq Bino", "zone": "Z", "resolution": "720p"},
        )
        assert resp.status_code == 404

    async def test_rtsp_credentials_are_encrypted_at_rest(self, client: AsyncClient, db_session):
        headers = await auth_headers(client, "admin", "admin123")
        await client.post(
            "/api/cameras",
            headers=headers,
            json={
                "name": "Login kamerasi",
                "ip": "192.168.1.60",
                "rtspUsername": "admin",
                "rtspPassword": "TopSecret",
                "building": "1-Bino (Asosiy korpus)",
                "zone": "A-Zona",
                "resolution": "1080p",
            },
        )
        row = (await db_session.execute(select(Camera).where(Camera.name == "Login kamerasi"))).scalar_one()
        assert row.rtsp_username != "admin"
        assert row.rtsp_password != "TopSecret"
        assert "TopSecret" not in (row.rtsp_password or "")

    async def test_stored_credentials_can_be_decrypted_for_retest(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = (
            await client.post(
                "/api/cameras",
                headers=headers,
                json={
                    "name": "Retest kamerasi",
                    "ip": "192.0.2.99",
                    "rtspUsername": "admin",
                    "rtspPassword": "TopSecret",
                    "building": "1-Bino (Asosiy korpus)",
                    "zone": "A-Zona",
                    "resolution": "1080p",
                },
            )
        ).json()

        resp = await client.post(f"/api/cameras/{created['id']}/test-connection", headers=headers)
        assert resp.status_code == 200
        # 192.0.2.0/24 is TEST-NET-1 (RFC 5737) — guaranteed unreachable,
        # so this only proves decrypt() didn't blow up, not that it connects.
        assert resp.json()["success"] is False

    async def test_connection_test_rejects_unreachable_host(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/cameras/test-connection", headers=headers, json={"ip": "192.0.2.123", "port": 554}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["method"] == "tcp-only"

    async def test_new_camera_defaults_to_not_an_entrance(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = (
            await client.post(
                "/api/cameras",
                headers=headers,
                json={
                    "name": "Oddiy kamera", "ip": "192.168.1.71",
                    "building": "1-Bino (Asosiy korpus)", "zone": "A-Zona", "resolution": "1080p",
                },
            )
        ).json()
        assert created["isEntrance"] is False

    async def test_is_entrance_round_trips_through_create_and_update(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = (
            await client.post(
                "/api/cameras",
                headers=headers,
                json={
                    "name": "Kirish kamerasi", "ip": "192.168.1.72",
                    "building": "1-Bino (Asosiy korpus)", "zone": "Kirish", "resolution": "1080p",
                    "isEntrance": True,
                },
            )
        ).json()
        assert created["isEntrance"] is True

        fetched = (await client.get("/api/cameras", headers=headers)).json()["items"]
        assert next(c for c in fetched if c["id"] == created["id"])["isEntrance"] is True

        updated = (
            await client.patch(
                f"/api/cameras/{created['id']}",
                headers=headers,
                json={
                    "name": "Kirish kamerasi", "ip": "192.168.1.72",
                    "building": "1-Bino (Asosiy korpus)", "zone": "Kirish", "resolution": "1080p",
                    "isEntrance": False,
                },
            )
        ).json()
        assert updated["isEntrance"] is False

    async def test_update_camera_status(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = (
            await client.post(
                "/api/cameras",
                headers=headers,
                json={
                    "name": "Holat kamerasi",
                    "ip": "192.168.1.70",
                    "building": "1-Bino (Asosiy korpus)",
                    "zone": "A-Zona",
                    "resolution": "1080p",
                    "status": "faol",
                },
            )
        ).json()

        resp = await client.patch(
            f"/api/cameras/{created['id']}",
            headers=headers,
            json={
                "name": "Holat kamerasi",
                "ip": "192.168.1.70",
                "building": "1-Bino (Asosiy korpus)",
                "zone": "A-Zona",
                "resolution": "1080p",
                "status": "tamirda",
            },
        )
        assert resp.json()["status"] == "tamirda"

    async def test_port_and_rtsp_path_round_trip_through_edit(self, client: AsyncClient):
        """Regression: CameraOut must echo back port/rtspPath so the edit
        form can pre-fill them accurately. Before this, editing any field
        (e.g. status) silently reset port to 554 and cleared rtspPath,
        because the frontend had no way to know the real saved values and
        CameraUpdateIn overwrites both unconditionally."""
        headers = await auth_headers(client, "admin", "admin123")
        created = (
            await client.post(
                "/api/cameras",
                headers=headers,
                json={
                    "name": "RTSP kamerasi",
                    "ip": "127.0.0.1",
                    "port": 8554,
                    "rtspPath": "/source-cam",
                    "building": "1-Bino (Asosiy korpus)",
                    "zone": "A-Zona",
                    "resolution": "1080p",
                },
            )
        ).json()
        assert created["port"] == 8554
        assert created["rtspPath"] == "/source-cam"

        fetched = (await client.get("/api/cameras", headers=headers)).json()["items"][0]
        assert fetched["port"] == 8554
        assert fetched["rtspPath"] == "/source-cam"

        # Simulate the edit form round-tripping the fetched values back, only
        # changing an unrelated field (zone).
        updated = (
            await client.patch(
                f"/api/cameras/{created['id']}",
                headers=headers,
                json={
                    "name": fetched["name"],
                    "ip": fetched["ip"],
                    "port": fetched["port"],
                    "rtspPath": fetched["rtspPath"],
                    "building": fetched["building"],
                    "zone": "B-Zona",
                    "resolution": fetched["resolution"],
                },
            )
        ).json()
        assert updated["port"] == 8554
        assert updated["rtspPath"] == "/source-cam"
        assert updated["zone"] == "B-Zona"

    async def test_filter_by_status(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        for name, status_ in [("Faol kamera", "faol"), ("Nofaol kamera", "nofaol")]:
            await client.post(
                "/api/cameras",
                headers=headers,
                json={
                    "name": name,
                    "ip": "192.168.1.80",
                    "building": "1-Bino (Asosiy korpus)",
                    "zone": "A-Zona",
                    "resolution": "1080p",
                    "status": status_,
                },
            )
        resp = await client.get("/api/cameras", headers=headers, params={"status": "faol"})
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "Faol kamera"

    async def test_multiple_cameras_can_share_one_room(self, client: AsyncClient):
        """A room routinely holds more than one camera (different angles) —
        nothing in the schema (no unique constraint on zone) or the API
        should prevent this."""
        headers = await auth_headers(client, "admin", "admin123")
        created_ids = []
        for i in range(3):
            resp = await client.post(
                "/api/cameras",
                headers=headers,
                json={
                    "name": f"101-xona kamera {i + 1}",
                    "ip": f"10.0.2.{i + 1}",
                    "building": "1-Bino (Asosiy korpus)",
                    "zone": "101-xona",
                    "resolution": "1080p",
                },
            )
            assert resp.status_code == 201
            created_ids.append(resp.json()["id"])

        assert len(set(created_ids)) == 3  # each got its own distinct id

        resp = await client.get("/api/cameras", headers=headers, params={"zone": "101-xona"})
        body = resp.json()
        assert body["total"] == 3
        assert {c["id"] for c in body["items"]} == set(created_ids)

    async def test_zones_endpoint_reports_camera_count_per_room(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        for i in range(2):
            await client.post(
                "/api/cameras",
                headers=headers,
                json={
                    "name": f"A-Zona kamera {i + 1}",
                    "ip": f"10.0.3.{i + 1}",
                    "building": "1-Bino (Asosiy korpus)",
                    "zone": "A-Zona",
                    "resolution": "1080p",
                },
            )
        await client.post(
            "/api/cameras",
            headers=headers,
            json={
                "name": "B-Zona kamera",
                "ip": "10.0.3.9",
                "building": "1-Bino (Asosiy korpus)",
                "zone": "B-Zona",
                "resolution": "1080p",
            },
        )

        resp = await client.get("/api/cameras/zones", headers=headers)
        assert resp.status_code == 200
        by_zone = {z["zone"]: z["cameraCount"] for z in resp.json()}
        assert by_zone["A-Zona"] == 2
        assert by_zone["B-Zona"] == 1

    async def test_zones_endpoint_filters_by_building(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        await client.post(
            "/api/cameras",
            headers=headers,
            json={
                "name": "Ikkinchi bino kamerasi",
                "ip": "10.0.4.1",
                "building": "2-Bino (Klinika va Laboratoriya)",
                "zone": "Boshqa-Zona",
                "resolution": "1080p",
            },
        )
        resp = await client.get(
            "/api/cameras/zones", headers=headers, params={"building": "1-Bino (Asosiy korpus)"}
        )
        zones = [z["zone"] for z in resp.json()]
        assert "Boshqa-Zona" not in zones

    async def test_newly_created_camera_is_not_reachable_until_health_swept(self, client: AsyncClient):
        """A camera's status='faol' (admin intent) is set immediately on
        create, but isReachable (observed) only becomes true once
        app/jobs/camera_health.py's sweep has actually reached it — the two
        are independent by design."""
        headers = await auth_headers(client, "admin", "admin123")
        created = (
            await client.post(
                "/api/cameras",
                headers=headers,
                json={
                    "name": "Yangi kamera",
                    "ip": "192.0.2.77",
                    "building": "1-Bino (Asosiy korpus)",
                    "zone": "A-Zona",
                    "resolution": "1080p",
                    "status": "faol",
                },
            )
        ).json()
        assert created["status"] == "faol"
        assert created["isReachable"] is False


@pytest.mark.usefixtures("seeded")
class TestCameraZonePolygon:
    async def _create_camera(self, client: AsyncClient, headers: dict[str, str]) -> dict:
        resp = await client.post(
            "/api/cameras",
            headers=headers,
            json={
                "name": "Zona kamerasi",
                "ip": "192.168.9.10",
                "building": "1-Bino (Asosiy korpus)",
                "zone": "Hovli",
                "resolution": "1080p",
            },
        )
        return resp.json()

    async def test_new_camera_has_no_zone_polygon(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = await self._create_camera(client, headers)
        assert created["restrictedZonePolygon"] is None

    async def test_setting_a_valid_polygon_round_trips(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = await self._create_camera(client, headers)
        polygon = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]

        resp = await client.patch(
            f"/api/cameras/{created['id']}/zone-polygon", headers=headers, json={"polygon": polygon}
        )
        assert resp.status_code == 200
        assert resp.json()["restrictedZonePolygon"] == polygon

        fetched = (await client.get("/api/cameras", headers=headers)).json()["items"][0]
        assert fetched["restrictedZonePolygon"] == polygon

    async def test_clearing_a_polygon_sets_it_back_to_none(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = await self._create_camera(client, headers)
        await client.patch(
            f"/api/cameras/{created['id']}/zone-polygon",
            headers=headers,
            json={"polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]},
        )

        resp = await client.patch(
            f"/api/cameras/{created['id']}/zone-polygon", headers=headers, json={"polygon": None}
        )
        assert resp.status_code == 200
        assert resp.json()["restrictedZonePolygon"] is None

    async def test_fewer_than_three_points_is_rejected(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = await self._create_camera(client, headers)
        resp = await client.patch(
            f"/api/cameras/{created['id']}/zone-polygon",
            headers=headers,
            json={"polygon": [[0.1, 0.1], [0.9, 0.9]]},
        )
        assert resp.status_code == 422

    async def test_unknown_camera_is_404(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.patch(
            "/api/cameras/00000000-0000-0000-0000-000000000000/zone-polygon",
            headers=headers,
            json={"polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]]},
        )
        assert resp.status_code == 404


@pytest.mark.usefixtures("seeded")
class TestCameraExcludedModules:
    async def _create_camera(self, client: AsyncClient, headers: dict[str, str]) -> dict:
        resp = await client.post(
            "/api/cameras",
            headers=headers,
            json={
                "name": "Modul kamerasi",
                "ip": "192.168.9.20",
                "building": "1-Bino (Asosiy korpus)",
                "zone": "Hovli",
                "resolution": "1080p",
            },
        )
        return resp.json()

    async def test_new_camera_has_no_excluded_modules(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = await self._create_camera(client, headers)
        assert created["excludedModuleCodes"] is None

    async def test_setting_excluded_modules_round_trips(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = await self._create_camera(client, headers)

        resp = await client.patch(
            f"/api/cameras/{created['id']}/modules", headers=headers, json={"excludedModuleCodes": [25, 16]}
        )
        assert resp.status_code == 200
        assert resp.json()["excludedModuleCodes"] == [25, 16]

        fetched = (await client.get("/api/cameras", headers=headers)).json()["items"][0]
        assert fetched["excludedModuleCodes"] == [25, 16]

    async def test_clearing_excluded_modules_sets_it_back_to_none(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = await self._create_camera(client, headers)
        await client.patch(
            f"/api/cameras/{created['id']}/modules", headers=headers, json={"excludedModuleCodes": [25]}
        )

        resp = await client.patch(
            f"/api/cameras/{created['id']}/modules", headers=headers, json={"excludedModuleCodes": None}
        )
        assert resp.status_code == 200
        assert resp.json()["excludedModuleCodes"] is None

    async def test_empty_list_also_clears_it(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = await self._create_camera(client, headers)
        await client.patch(
            f"/api/cameras/{created['id']}/modules", headers=headers, json={"excludedModuleCodes": [25]}
        )

        resp = await client.patch(
            f"/api/cameras/{created['id']}/modules", headers=headers, json={"excludedModuleCodes": []}
        )
        assert resp.status_code == 200
        assert resp.json()["excludedModuleCodes"] is None

    async def test_unknown_camera_is_404(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.patch(
            "/api/cameras/00000000-0000-0000-0000-000000000000/modules",
            headers=headers,
            json={"excludedModuleCodes": [25]},
        )
        assert resp.status_code == 404

    async def test_module_options_lists_all_criteria(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/cameras/module-options", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 25
        assert all("code" in row and "name" in row and "hasDetector" in row for row in body)

    async def test_module_camera_assignments_toggle(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        created = await self._create_camera(client, headers)
        await client.patch(
            f"/api/cameras/{created['id']}",
            headers=headers,
            json={
                **{
                    "name": created["name"],
                    "ip": created["ip"],
                    "port": created["port"],
                    "building": created["building"],
                    "zone": created["zone"],
                    "resolution": created["resolution"],
                },
                "status": "faol",
            },
        )

        listed = await client.get("/api/cameras/by-module/25/assignments", headers=headers)
        assert listed.status_code == 200
        body = listed.json()
        assert body["moduleCode"] == 25
        row = next(c for c in body["cameras"] if c["cameraId"] == created["id"])
        assert row["enabled"] is True

        patched = await client.patch(
            "/api/cameras/by-module/25/assignments",
            headers=headers,
            json={"assignments": [{"cameraId": created["id"], "enabled": False}]},
        )
        assert patched.status_code == 200
        row2 = next(c for c in patched.json()["cameras"] if c["cameraId"] == created["id"])
        assert row2["enabled"] is False

        fetched = (
            await client.get("/api/cameras", headers=headers, params={"zone": "Hovli"})
        ).json()["items"][0]
        assert 25 in fetched["excludedModuleCodes"]
