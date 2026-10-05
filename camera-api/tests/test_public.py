from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.models import Building, Camera
from tests.conftest import auth_headers


@pytest.fixture
async def a_camera(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    camera = Camera(
        name="Ommaviy test kamerasi",
        ip="10.0.0.9",
        building_id=building.id,
        zone="Z",
        resolution="1080p",
        status="faol",
        # Simulates app/jobs/camera_health.py having just swept this camera
        # successfully — public "live" status needs both status='faol' AND
        # a fresh last_seen_at, not status alone.
        last_seen_at=datetime.now(timezone.utc),
    )
    db_session.add(camera)
    await db_session.commit()
    await db_session.refresh(camera)
    return camera


@pytest.fixture
def monitoring_open(monkeypatch):
    """Turns the monitoring wall's auth gate off for the tests below.

    Those tests are about the endpoints' BEHAVIOUR (pagination, filters,
    live/offline logic), not about who may call them; the gate itself is
    covered separately in TestMonitoringAuthGate. Keeping them split
    means a change to the gate cannot quietly pass by breaking fifteen
    unrelated assertions."""
    monkeypatch.setattr(settings, "public_monitoring_requires_auth", False)


@pytest.mark.usefixtures("seeded")
class TestMonitoringAuthGate:
    """The wall used to be readable by anyone who could reach the site.
    Measured on production before this: no token in localStorage, and all
    107 live camera feeds rendered anyway."""

    async def test_cameras_require_auth_by_default(self, client: AsyncClient, a_camera):
        resp = await client.get("/api/public/cameras")
        assert resp.status_code == 401

    async def test_stats_require_auth_by_default(self, client: AsyncClient):
        assert (await client.get("/api/public/stats")).status_code == 401

    async def test_live_detection_requires_auth_by_default(self, client: AsyncClient, a_camera):
        resp = await client.get(f"/api/public/cameras/{a_camera.id}/live-detection")
        assert resp.status_code == 401

    async def test_a_logged_in_user_gets_through(self, client: AsyncClient, a_camera):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/public/cameras", headers=headers)
        assert resp.status_code == 200

    async def test_the_gate_can_be_reopened_by_configuration(
        self, client: AsyncClient, a_camera, monitoring_open
    ):
        """A situation-centre wall display may have no one to type a
        password into it. Closing the hole must not mean that screen
        cannot be brought back without a redeploy."""
        assert (await client.get("/api/public/cameras")).status_code == 200


@pytest.mark.usefixtures("seeded", "monitoring_open")
class TestPublicEndpoints:
    async def test_public_cameras_hides_credentials(self, client: AsyncClient, a_camera):
        resp = await client.get("/api/public/cameras")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        cam = body["items"][0]
        assert cam["name"] == "Ommaviy test kamerasi"
        assert cam["status"] == "live"
        assert "ip" not in cam
        assert "rtspPath" not in cam
        assert "rtspUsername" not in cam

    async def test_faol_camera_never_swept_shows_offline_not_live(self, client: AsyncClient, db_session):
        """The exact bug this feature fixes: before app/jobs/camera_health.py,
        status='faol' alone made a camera show as JONLI on the public page
        forever, even if it had never actually been reached (or its cable
        was unplugged) — status is admin intent, not an observation."""
        building = (await db_session.execute(select(Building))).scalars().first()
        camera = Camera(
            name="Hech qachon tekshirilmagan kamera",
            ip="192.0.2.88",
            building_id=building.id,
            zone="Z",
            resolution="1080p",
            status="faol",
            last_seen_at=None,
        )
        db_session.add(camera)
        await db_session.commit()

        resp = await client.get("/api/public/cameras")
        cam = next(c for c in resp.json()["items"] if c["name"] == "Hech qachon tekshirilmagan kamera")
        assert cam["status"] == "offline"

    async def test_public_stats_shape(self, client: AsyncClient):
        resp = await client.get("/api/public/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {
            "totalStudents", "present", "absent", "late", "sleepIncidents", "violations",
            "liveCameras", "offlineCameras", "buildings", "departments",
        }

    async def test_public_stats_reflects_real_attendance(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        student = (
            await client.post(
                "/api/students-staff",
                headers=headers,
                json={"fullName": "Ochiq Talaba", "type": "talaba", "faculty": "Davolash ishi", "groupOrPosition": "1"},
            )
        ).json()
        today = date.today().isoformat()
        await client.post(
            "/api/attendance",
            headers=headers,
            json={"studentStaffId": student["id"], "date": today, "status": "keldi"},
        )

        resp = await client.get("/api/public/stats")
        assert resp.json()["present"] == 1
        assert resp.json()["totalStudents"] >= 1

    async def test_top_students_ranks_by_real_attendance_rate(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        student = (
            await client.post(
                "/api/students-staff",
                headers=headers,
                json={"fullName": "Reyting Talaba", "type": "talaba", "faculty": "Davolash ishi", "groupOrPosition": "5-guruh"},
            )
        ).json()
        today = date.today().isoformat()
        await client.post(
            "/api/attendance",
            headers=headers,
            json={"studentStaffId": student["id"], "date": today, "status": "keldi"},
        )

        resp = await client.get("/api/public/top-students")
        assert resp.status_code == 200
        body = resp.json()
        assert any(s["id"] == student["id"] and s["attendanceRate"] == 100 for s in body)

    async def test_live_detection_unknown_camera_is_404(self, client: AsyncClient):
        resp = await client.get("/api/public/cameras/00000000-0000-0000-0000-000000000000/live-detection")
        assert resp.status_code == 404

    async def test_live_detection_camera_without_stream_returns_empty(self, client: AsyncClient, a_camera):
        # a_camera has no stream_url configured -- no ffmpeg/RTSP available
        # to actually grab a frame from in this test environment, so the
        # endpoint's early-return path is what's under test here.
        resp = await client.get(f"/api/public/cameras/{a_camera.id}/live-detection")
        assert resp.status_code == 200
        body = resp.json()
        assert body["faces"] == []
        assert body["frameWidth"] == 0
        assert body["frameHeight"] == 0

    async def test_public_cameras_pagination_bounds_page_size(self, client: AsyncClient, db_session):
        building = (await db_session.execute(select(Building))).scalars().first()
        for i in range(5):
            db_session.add(
                Camera(
                    name=f"Sahifa kamerasi {i}", ip=f"10.0.1.{i}", building_id=building.id, zone="Z",
                    resolution="1080p", status="faol",
                )
            )
        await db_session.commit()

        resp = await client.get("/api/public/cameras?pageSize=2&page=1")
        body = resp.json()
        assert body["total"] == 5
        assert body["totalPages"] == 3
        assert len(body["items"]) == 2

        resp2 = await client.get("/api/public/cameras?pageSize=2&page=3")
        assert len(resp2.json()["items"]) == 1  # last page has the 1 remaining camera

    async def test_public_cameras_search_filters_by_name_or_zone(self, client: AsyncClient, db_session):
        building = (await db_session.execute(select(Building))).scalars().first()
        db_session.add(
            Camera(
                name="Kirish nazorati", ip="10.0.2.1", building_id=building.id, zone="Bosh kirish",
                resolution="1080p", status="faol",
            )
        )
        db_session.add(
            Camera(
                name="Boshqa kamera", ip="10.0.2.2", building_id=building.id, zone="Ombor",
                resolution="1080p", status="faol",
            )
        )
        await db_session.commit()

        resp = await client.get("/api/public/cameras?search=kirish")
        names = [c["name"] for c in resp.json()["items"]]
        assert names == ["Kirish nazorati"]  # matches by name

        resp2 = await client.get("/api/public/cameras?search=Ombor")
        names2 = [c["name"] for c in resp2.json()["items"]]
        assert names2 == ["Boshqa kamera"]  # matches by zone

    async def test_public_cameras_status_filter(self, client: AsyncClient, a_camera, db_session):
        building = (await db_session.execute(select(Building))).scalars().first()
        db_session.add(
            Camera(
                name="Oflayn kamera", ip="10.0.3.1", building_id=building.id, zone="Z",
                resolution="1080p", status="faol", last_seen_at=None,
            )
        )
        await db_session.commit()

        live_resp = await client.get("/api/public/cameras?status=live")
        live_names = [c["name"] for c in live_resp.json()["items"]]
        assert live_names == [a_camera.name]

        offline_resp = await client.get("/api/public/cameras?status=offline")
        offline_names = [c["name"] for c in offline_resp.json()["items"]]
        assert offline_names == ["Oflayn kamera"]

    async def test_public_cameras_building_filter(self, client: AsyncClient, db_session):
        buildings = (await db_session.execute(select(Building))).scalars().all()
        assert len(buildings) >= 2
        db_session.add(
            Camera(
                name="Birinchi bino kamerasi", ip="10.0.4.1", building_id=buildings[0].id, zone="Z",
                resolution="1080p", status="faol",
            )
        )
        db_session.add(
            Camera(
                name="Ikkinchi bino kamerasi", ip="10.0.4.2", building_id=buildings[1].id, zone="Z",
                resolution="1080p", status="faol",
            )
        )
        await db_session.commit()

        resp = await client.get(f"/api/public/cameras?building={buildings[0].name}")
        names = [c["name"] for c in resp.json()["items"]]
        assert "Birinchi bino kamerasi" in names
        assert "Ikkinchi bino kamerasi" not in names

    async def test_public_stats_camera_counts_and_buildings(self, client: AsyncClient, a_camera, db_session):
        building = (await db_session.execute(select(Building))).scalars().first()
        db_session.add(
            Camera(
                name="Oflayn statistika kamerasi", ip="10.0.5.1", building_id=building.id, zone="Z",
                resolution="1080p", status="faol", last_seen_at=None,
            )
        )
        await db_session.commit()

        resp = await client.get("/api/public/stats")
        body = resp.json()
        assert body["liveCameras"] >= 1
        assert body["offlineCameras"] >= 1
        assert building.name in body["buildings"]

    async def test_top_students_excludes_students_with_no_attendance(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        await client.post(
            "/api/students-staff",
            headers=headers,
            json={"fullName": "Yozuvsiz Talaba", "type": "talaba", "faculty": "Davolash ishi", "groupOrPosition": "1"},
        )

        resp = await client.get("/api/public/top-students")
        names = [s["name"] for s in resp.json()]
        assert "Yozuvsiz Talaba" not in names


# ─────────────────────── Yuz belgilari: holat va 4K manba (2026-09-24)

@pytest.mark.usefixtures("seeded", "monitoring_open")
class TestLiveDetectionFaceStatus:
    """Operator kamerani kuzatganda har yuz aniq belgilanishi kerak:
    tanildi / notanish / kichik. Ilgari oxirgi ikkisi bir xil
    ("Noma'lum") edi — skaner tanimadimi yoki umuman ko'rmadimi, bilib
    bo'lmasdi."""

    async def _call(self, client, a_camera, monkeypatch, *, main_frame, faces, match_ids=()):
        import numpy as np
        from types import SimpleNamespace

        from app.routers import public as public_router

        async def fake_main(camera, *, wait_seconds):
            return main_frame

        async def fake_sub(camera, *, wait_seconds=None):
            return b"sub-frame"

        async def fake_detect(frame, priority=None):
            return faces

        class FakeCandidates:
            is_empty = False

            def best_match(self, embedding, threshold):
                return (match_ids[0], 0.7) if match_ids and float(embedding[0]) > 0.5 else None

            def top_two(self, embeddings):
                return None, np.array([0.71 if float(embeddings[0][0]) > 0.5 else 0.12]), np.array([0.0])

        async def fake_candidates(db):
            return FakeCandidates()

        monkeypatch.setattr(public_router, "grab_live_main_frame", fake_main)
        monkeypatch.setattr(public_router, "grab_frame_for_camera", fake_sub)
        monkeypatch.setattr(public_router, "detect_faces", fake_detect)
        monkeypatch.setattr(public_router, "load_candidate_matrix_cached", fake_candidates)
        monkeypatch.setattr(public_router, "jpeg_dimensions", lambda _b: (3840, 2160))
        resp = await client.get(f"/api/public/cameras/{a_camera.id}/live-detection")
        assert resp.status_code == 200, resp.text
        return resp.json()

    @staticmethod
    def _face(first: float | None):
        import numpy as np
        from types import SimpleNamespace

        emb = None if first is None else np.array([first] + [0.0] * 511)
        return SimpleNamespace(bbox=np.array([10.0, 10.0, 60.0, 70.0]), embedding=emb, landmarks_68=None)

    async def test_each_face_gets_its_own_status(self, client, a_camera, monkeypatch, db_session):
        from app.models import StudentStaff

        person = StudentStaff(full_name="Aliyev Anvar", type="talaba", group_or_position="DI-2301")
        db_session.add(person)
        await db_session.commit()

        body = await self._call(
            client, a_camera, monkeypatch,
            main_frame=b"main-frame",
            faces=[self._face(0.9), self._face(0.1), self._face(None)],
            match_ids=(person.id,),
        )
        statuses = [f["status"] for f in body["faces"]]
        assert statuses == ["tanildi", "notanish", "kichik"]
        assert body["faces"][0]["personName"] == "Aliyev Anvar"
        assert body["faces"][1]["similarity"] == 0.12
        # Kichik yuzga o'xshashlik o'ylab topilmaydi.
        assert body["faces"][2]["similarity"] is None

    async def test_main_stream_is_used_when_available(self, client, a_camera, monkeypatch):
        body = await self._call(client, a_camera, monkeypatch, main_frame=b"main-frame", faces=[])
        assert body["source"] == "asosiy"

    async def test_falls_back_to_substream(self, client, a_camera, monkeypatch):
        body = await self._call(client, a_camera, monkeypatch, main_frame=None, faces=[])
        assert body["source"] == "kichik"


# ─────────────────────── Real vaqtdagi skaner (2026-09-24)

@pytest.mark.usefixtures("seeded", "monitoring_open")
class TestLiveDetectionFromWatcher:
    """Skaner ai-worker kuzatuvchisining natijasini o'qiydi — API o'zi kadr
    olmaydi va tahlil qilmaydi (app/services/live_focus.py)."""

    async def test_watcher_result_is_served_without_inference(self, client, a_camera, monkeypatch):
        from app.routers import public as public_router
        from app.services import live_focus

        async def must_not_run(*_args, **_kwargs):
            raise AssertionError("API kadrni o'zi tahlil qilmasligi kerak")

        monkeypatch.setattr(public_router, "detect_faces", must_not_run)
        monkeypatch.setattr(public_router, "grab_live_main_frame", must_not_run)
        await live_focus.publish_result(
            str(a_camera.id),
            {
                "frame_width": 1280,
                "frame_height": 720,
                "source": "kichik",
                "faces": [{"bbox": [1, 2, 3, 4], "person_name": "Ali Valiyev", "asleep": False, "status": "tanildi", "similarity": 0.61}],
            },
        )
        resp = await client.get(f"/api/public/cameras/{a_camera.id}/live-detection")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["faces"][0]["personName"] == "Ali Valiyev"
        assert body["frameWidth"] == 1280
        # So'rov kamerani "kuzatilmoqda" deb belgiladi — kuzatuvchi uni tezlashtiradi.
        assert await live_focus.is_focused(str(a_camera.id))

    async def test_waits_briefly_for_the_watcher_then_falls_back(self, client, a_camera, monkeypatch):
        from app.routers import public as public_router

        monkeypatch.setattr(settings, "live_result_first_wait_seconds", 0.3)
        calls: list[int] = []

        async def fake_sub(camera, *, wait_seconds=None):
            calls.append(1)
            return None

        async def no_main(camera, *, wait_seconds):
            return None

        monkeypatch.setattr(public_router, "grab_live_main_frame", no_main)
        monkeypatch.setattr(public_router, "grab_frame_for_camera", fake_sub)
        resp = await client.get(f"/api/public/cameras/{a_camera.id}/live-detection")
        assert resp.status_code == 200 and calls == [1]
        # Kuzatuvchi javob bermagan kamera uchun keyingi so'rov kutmaydi.
        assert str(a_camera.id) in public_router._no_watcher_until


# ─────────────────────── WebRTC (WHEP) (2026-09-24)

@pytest.mark.usefixtures("seeded", "monitoring_open")
class TestWhepProxy:
    """Brauzer SDP taklifi API orqali MediaMTX'ga uzatiladi."""

    async def test_offer_is_forwarded_to_the_cameras_shard(self, client, a_camera, db_session, monkeypatch):
        import httpx as real_httpx

        from app.routers import public as public_router

        a_camera.stream_url = "/s1/cam-" + str(a_camera.id) + "/index.m3u8"
        db_session.add(a_camera)
        await db_session.commit()
        seen = {}

        def handler(request: real_httpx.Request) -> real_httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = request.content
            return real_httpx.Response(201, content=b"v=0\r\nanswer", headers={"Content-Type": "application/sdp"})

        transport = real_httpx.MockTransport(handler)
        original = real_httpx.AsyncClient
        monkeypatch.setattr(public_router.httpx, "AsyncClient", lambda **kw: original(transport=transport, **kw))
        monkeypatch.setattr(settings, "mediamtx_shard_hls_base_urls", "/s0,/s1")
        monkeypatch.setattr(settings, "mediamtx_shard_hls_internal_base_urls", "http://mediamtx-0:8888,http://mediamtx-1:8888")
        resp = await client.post(
            f"/api/public/cameras/{a_camera.id}/whep", content=b"v=0\r\noffer", headers={"Content-Type": "application/sdp"}
        )
        assert resp.status_code == 201, resp.text
        assert resp.content == b"v=0\r\nanswer"
        assert seen["url"] == f"http://mediamtx-1:8889/cam-{a_camera.id}/whep"
        assert seen["body"] == b"v=0\r\noffer"

    async def test_garbage_and_disabled_are_refused(self, client, a_camera, monkeypatch):
        bad = await client.post(f"/api/public/cameras/{a_camera.id}/whep", content=b"hello")
        assert bad.status_code in (400, 404)
        monkeypatch.setattr(settings, "webrtc_enabled", False)
        off = await client.post(f"/api/public/cameras/{a_camera.id}/whep", content=b"v=0\r\n")
        assert off.status_code == 404
