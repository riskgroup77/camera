"""Kampus kesimi (bino -> qavat -> kamera) va miniatyura keshi.

Video Monitoring Markazi shu endpointlar ustiga quriladi: birinchi
yuklanishda faqat sanoqlar keladi, kameralar esa qavat tanlangandagina.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.models import Building, Camera, Event
from app.routers.public import reset_campus_cache_for_tests
from app.services import thumbnail_cache
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def fresh_campus_cache():
    """Kesim 15 soniya keshlanadi — testlar orasida u tozalanishi shart."""
    reset_campus_cache_for_tests()
    thumbnail_cache.reset_thumbnail_cache_for_tests()
    # Testlarda Redis ishlatilmaydi: kesh jarayon ichida qolsin, aks holda
    # bir test yozgan rasm keyingisiga o'tib ketardi.
    thumbnail_cache._redis = None
    thumbnail_cache._redis_tried = True
    yield
    reset_campus_cache_for_tests()
    thumbnail_cache.reset_thumbnail_cache_for_tests()


@pytest.fixture
def monitoring_open(monkeypatch):
    monkeypatch.setattr(settings, "public_monitoring_requires_auth", False)


async def _camera(db_session, building, name, *, floor, live=True, video=True):
    now = datetime.now(timezone.utc)
    camera = Camera(
        name=name,
        ip=f"10.9.0.{abs(hash(name)) % 240 + 1}",
        building_id=building.id if building else None,
        zone="Koridor",
        floor=floor,
        resolution="1080p",
        status="faol" if live else "nofaol",
        last_seen_at=now if live else None,
        last_frame_at=now if (live and video) else None,
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera)
    return camera


@pytest.fixture
async def campus(db_session, seeded):
    building = (await db_session.execute(select(Building).order_by(Building.name))).scalars().first()
    building.floors = 3
    await db_session.commit()
    cameras = {
        "first": await _camera(db_session, building, "1-qavat kirish", floor=1),
        "second": await _camera(db_session, building, "2-qavat koridor", floor=2, video=False),
        "offline": await _camera(db_session, building, "2-qavat auditoriya", floor=2, live=False),
        "unknown_floor": await _camera(db_session, building, "Qavatsiz kamera", floor=None),
        "no_building": await _camera(db_session, None, "Biriktirilmagan kamera", floor=None),
    }
    return building, cameras


@pytest.mark.usefixtures("monitoring_open")
class TestCampusOverview:
    async def test_floors_carry_camera_and_event_counts(self, client: AsyncClient, db_session, campus):
        building, cameras = campus
        db_session.add(
            Event(
                camera_id=cameras["second"].id,
                camera_name=cameras["second"].name,
                building=building.name,
                module_code=1,
                module_name="Begona shaxs",
                group="A",
                confidence=90,
                severity="yuqori",
                status="yangi",
            )
        )
        db_session.add(
            Event(
                camera_id=cameras["second"].id,
                camera_name=cameras["second"].name,
                building=building.name,
                module_code=23,
                module_name="Yong'in",
                group="F",
                confidence=50,
                severity="yuqori",
                status="yangi",
                is_trial=True,
            )
        )
        await db_session.commit()

        body = (await client.get("/api/public/campus")).json()
        target = next(b for b in body["buildings"] if b["id"] == str(building.id))

        assert target["cameras"] == 4 and target["live"] == 3 and target["offline"] == 1
        assert [floor["floor"] for floor in target["floors"]] == [1, 2, 3, None]

        second = next(floor for floor in target["floors"] if floor["floor"] == 2)
        assert second["cameras"] == 2 and second["live"] == 1 and second["offline"] == 1
        assert second["noVideo"] == 1
        # Sinov namunasi operator kesimida ko'rinmaydi.
        assert second["eventsToday"] == 1

        empty = next(floor for floor in target["floors"] if floor["floor"] == 3)
        assert empty["cameras"] == 0 and empty["label"] == "3-qavat"

        unassigned = next(floor for floor in target["floors"] if floor["floor"] is None)
        assert unassigned["label"] == "Qavat belgilanmagan" and unassigned["cameras"] == 1

    async def test_cameras_without_a_building_stay_visible(self, client: AsyncClient, campus):
        body = (await client.get("/api/public/campus")).json()
        orphans = next(b for b in body["buildings"] if b["id"] == "")
        assert orphans["name"] == "Bino biriktirilmagan" and orphans["cameras"] == 1
        assert body["cameras"] == 5

    async def test_campus_never_lists_cameras(self, client: AsyncClient, campus):
        """Yengil bo'lishi kesimning butun ma'nosi: ro'yxat qavat
        tanlangandan keyin alohida so'raladi."""
        body = (await client.get("/api/public/campus")).json()
        assert "cameras" in body and isinstance(body["cameras"], int)
        assert all("items" not in building for building in body["buildings"])


@pytest.mark.usefixtures("monitoring_open")
class TestFloorCameraList:
    async def test_filters_by_building_and_floor(self, client: AsyncClient, campus):
        building, _cameras = campus
        resp = await client.get(
            "/api/public/cameras", params={"buildingId": str(building.id), "floor": "2"}
        )
        body = resp.json()
        assert resp.status_code == 200
        assert sorted(item["name"] for item in body["items"]) == ["2-qavat auditoriya", "2-qavat koridor"]
        assert all(item["floor"] == 2 for item in body["items"])

    async def test_unassigned_floor_group(self, client: AsyncClient, campus):
        building, _cameras = campus
        body = (
            await client.get(
                "/api/public/cameras", params={"buildingId": str(building.id), "floor": "none"}
            )
        ).json()
        assert [item["name"] for item in body["items"]] == ["Qavatsiz kamera"]

    async def test_unassigned_building_group(self, client: AsyncClient, campus):
        body = (await client.get("/api/public/cameras", params={"buildingId": "none"})).json()
        assert [item["name"] for item in body["items"]] == ["Biriktirilmagan kamera"]

    async def test_bad_filters_are_rejected(self, client: AsyncClient, campus):
        assert (await client.get("/api/public/cameras", params={"buildingId": "abc"})).status_code == 400
        assert (await client.get("/api/public/cameras", params={"floor": "yuqori"})).status_code == 400


@pytest.mark.usefixtures("monitoring_open")
class TestThumbnail:
    async def test_cached_frame_is_served_without_touching_the_camera(
        self, client: AsyncClient, campus, monkeypatch
    ):
        _building, cameras = campus
        camera = cameras["first"]

        async def fail_grab(*_args, **_kwargs):
            raise AssertionError("keshdagi rasm bor ekan, kameraga ulanmasligi kerak")

        monkeypatch.setattr(thumbnail_cache, "_shrink", lambda raw: raw)
        await thumbnail_cache._store(str(camera.id), b"jpeg-bytes")
        monkeypatch.setattr("app.services.frame_grabber.grab_frame_for_camera", fail_grab)

        resp = await client.get(f"/api/public/cameras/{camera.id}/thumbnail")
        assert resp.status_code == 200
        assert resp.content == b"jpeg-bytes"
        assert resp.headers["content-type"] == "image/jpeg"
        assert int(resp.headers["X-Thumbnail-Age"]) >= 0

    async def test_missing_frame_is_a_404_not_an_error(self, client: AsyncClient, campus, monkeypatch):
        _building, cameras = campus

        async def no_frame(*_args, **_kwargs):
            return None

        monkeypatch.setattr("app.services.frame_grabber.grab_frame_for_camera", no_frame)
        resp = await client.get(f"/api/public/cameras/{cameras['first'].id}/thumbnail")
        assert resp.status_code == 404

    async def test_unknown_camera_id_is_a_404(self, client: AsyncClient, campus):
        assert (await client.get("/api/public/cameras/not-a-uuid/thumbnail")).status_code == 404

    async def test_stale_frame_triggers_one_grab(self, client: AsyncClient, campus, monkeypatch):
        _building, cameras = campus
        camera = cameras["first"]
        grabs: list[str] = []

        async def one_frame(camera_arg, **_kwargs):
            grabs.append(str(camera_arg.id))
            return b"fresh"

        monkeypatch.setattr(thumbnail_cache, "_shrink", lambda raw: raw)
        monkeypatch.setattr("app.services.frame_grabber.grab_frame_for_camera", one_frame)
        # Eskirgan rasm: yoshi thumbnail_stale_seconds dan katta.
        stale_at = (datetime.now(timezone.utc) - timedelta(seconds=settings.thumbnail_stale_seconds + 60)).timestamp()
        thumbnail_cache._cache[str(camera.id)] = (stale_at, b"old")

        first = await client.get(f"/api/public/cameras/{camera.id}/thumbnail")
        assert first.status_code == 200 and first.content == b"fresh"
        # Ikkinchi so'rov yangi rasmni keshdan oladi — kamera qayta bezovta qilinmaydi.
        second = await client.get(f"/api/public/cameras/{camera.id}/thumbnail")
        assert second.status_code == 200 and second.content == b"fresh"
        assert grabs == [str(camera.id)]


class TestBulkLocation:
    async def test_floor_is_assigned_to_many_cameras_at_once(self, client: AsyncClient, campus):
        _building, cameras = campus
        headers = await auth_headers(client, "admin", "admin123")
        ids = [str(cameras["unknown_floor"].id), str(cameras["no_building"].id)]

        resp = await client.post(
            "/api/cameras/bulk-location",
            headers=headers,
            json={"cameraIds": ids + ["not-a-uuid"], "floor": 4, "zone": "Zina"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["updated"] == 2 and resp.json()["notFound"] == ["not-a-uuid"]

        listed = (await client.get("/api/cameras", headers=headers, params={"pageSize": 100})).json()
        updated = {item["name"]: item for item in listed["items"]}
        assert updated["Qavatsiz kamera"]["floor"] == 4
        assert updated["Qavatsiz kamera"]["zone"] == "Zina"

    async def test_clear_floor_flag_removes_the_floor(self, client: AsyncClient, campus):
        _building, cameras = campus
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.post(
            "/api/cameras/bulk-location",
            headers=headers,
            json={"cameraIds": [str(cameras["first"].id)], "clearFloor": True},
        )
        assert resp.status_code == 200 and resp.json()["updated"] == 1

        listed = (await client.get("/api/cameras", headers=headers, params={"pageSize": 100})).json()
        assert next(item for item in listed["items"] if item["name"] == "1-qavat kirish")["floor"] is None


class TestCameraSummaryAndFilters:
    async def test_summary_counts_come_from_one_request(self, client: AsyncClient, campus):
        _building, _cameras = campus
        headers = await auth_headers(client, "admin", "admin123")
        body = (await client.get("/api/cameras/summary", headers=headers)).json()
        assert body["total"] == 5
        assert body["faol"] == 4 and body["nofaol"] == 1
        assert body["reachable"] == 4
        # Ikkitasining qavati yo'q: "Qavatsiz kamera" va "Biriktirilmagan kamera".
        assert body["withoutFloor"] == 2

    async def test_admin_list_filters_by_floor_and_search(self, client: AsyncClient, campus):
        headers = await auth_headers(client, "admin", "admin123")
        by_floor = (
            await client.get("/api/cameras", headers=headers, params={"floor": "2", "pageSize": 50})
        ).json()
        assert sorted(item["name"] for item in by_floor["items"]) == [
            "2-qavat auditoriya",
            "2-qavat koridor",
        ]

        without_floor = (
            await client.get("/api/cameras", headers=headers, params={"floor": "none", "pageSize": 50})
        ).json()
        assert without_floor["total"] == 2

        found = (
            await client.get("/api/cameras", headers=headers, params={"search": "kirish", "pageSize": 50})
        ).json()
        assert [item["name"] for item in found["items"]] == ["1-qavat kirish"]


class TestCameraEditKeepsFloor:
    async def test_patch_without_floor_does_not_clear_it(self, client: AsyncClient, campus):
        """Qavat maydonini bilmaydigan eski forma kameraning qavatini
        o'chirib yubormasligi kerak."""
        _building, cameras = campus
        headers = await auth_headers(client, "admin", "admin123")
        camera = cameras["first"]
        body = {
            "name": camera.name,
            "ip": camera.ip,
            "port": camera.port,
            "building": _building.name,
            "zone": camera.zone,
            "resolution": camera.resolution,
            "status": camera.status,
        }

        resp = await client.patch(f"/api/cameras/{camera.id}", headers=headers, json=body)
        assert resp.status_code == 200, resp.text
        assert resp.json()["floor"] == 1

        cleared = await client.patch(
            f"/api/cameras/{camera.id}", headers=headers, json={**body, "floor": None}
        )
        assert cleared.json()["floor"] is None


class TestBuildingFloors:
    async def test_floors_survive_a_patch_that_omits_them(self, client: AsyncClient, campus):
        building, _cameras = campus
        headers = await auth_headers(client, "admin", "admin123")

        resp = await client.patch(
            f"/api/buildings/{building.id}",
            headers=headers,
            json={"name": building.name, "cameraCount": 4},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["floors"] == 3

        updated = await client.patch(
            f"/api/buildings/{building.id}",
            headers=headers,
            json={"name": building.name, "cameraCount": 4, "floors": 6, "sortOrder": 2},
        )
        assert updated.json()["floors"] == 6 and updated.json()["sortOrder"] == 2
