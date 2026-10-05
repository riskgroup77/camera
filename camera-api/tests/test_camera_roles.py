"""Kamera roli (xona turi) bo'yicha AI modullarini yo'naltirish —
app/services/camera_roles.py va kamera rollari CSV'si."""

from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.jobs.module_status import camera_allows_module, camera_can_report_unauthorized
from app.models import Building, Camera
from app.services.camera_roles import (
    MODULE_ROOM_TYPES,
    effective_room_type,
    guess_room_from_name,
    normalize_room_code,
    role_allows,
)
from tests.conftest import auth_headers


def _cam(**fields):
    base = dict(room_type=None, is_entrance=False, is_exit=False, is_perimeter=False)
    base.update(fields)
    return SimpleNamespace(**base)


class TestRules:
    def test_effective_type_comes_from_flags_when_unset(self):
        assert effective_room_type(_cam(is_entrance=True)) == "kirish"
        assert effective_room_type(_cam(is_exit=True)) == "kirish"
        assert effective_room_type(_cam(is_perimeter=True)) == "tashqi"
        assert effective_room_type(_cam(is_entrance=True, is_perimeter=True)) == "kirish"
        assert effective_room_type(_cam()) is None
        # Admin belgilagani bayroqdan ustun.
        assert effective_room_type(_cam(room_type="koridor", is_entrance=True)) == "koridor"

    def test_sleep_runs_only_in_classrooms_and_attendance_only_at_doors(self):
        assert role_allows(_cam(room_type="auditoriya"), 20)
        assert not role_allows(_cam(is_entrance=True), 20)  # 2026-09-18: kirishda "uxlayapti" signallari
        assert not role_allows(_cam(), 20)
        assert role_allows(_cam(is_entrance=True), 6)
        assert not role_allows(_cam(room_type="auditoriya"), 6)

    def test_security_modules_run_everywhere(self):
        for code in (2,):
            assert code not in MODULE_ROOM_TYPES
            assert role_allows(_cam(), code)
            assert role_allows(_cam(room_type="ofis"), code)

    def test_unauthorized_only_where_people_enter(self):
        assert camera_can_report_unauthorized(_cam(is_entrance=True))
        assert camera_can_report_unauthorized(_cam(is_perimeter=True))
        assert camera_can_report_unauthorized(_cam(room_type="cheklangan"))
        assert not camera_can_report_unauthorized(_cam(room_type="auditoriya"))
        assert not camera_can_report_unauthorized(_cam())

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("211", "211"),
            ("211-xona", "211"),
            ("Aud. 211", "211"),
            ("211 xonasi", "211"),
            (" 27-XONA ", "27"),
            ("A-201", "a201"),
            ("Oshxona", "oshxona"),
            ("", None),
            (None, None),
        ],
    )
    def test_room_codes_compare_equal_however_written(self, raw, expected):
        assert normalize_room_code(raw) == expected

    def test_guess_from_name(self):
        assert guess_room_from_name("27-xona") == ("auditoriya", "27")
        assert guess_room_from_name("211") == ("auditoriya", "211")
        assert guess_room_from_name("IPC-T280HA-LUF/SL (192.168.0.53)") == (None, None)


@pytest.mark.usefixtures("seeded")
class TestSqlMatchesPython:
    async def test_sweep_filter_agrees_with_python_rule(self, db_session):
        """Sweeplar SQL filtrini, unified_face_sweep esa Python qoidasini
        ishlatadi — ikkalasi bir xil kameralarni tanlashi shart."""
        building = (await db_session.execute(select(Building))).scalars().first()
        variants = [
            dict(),
            dict(is_entrance=True),
            dict(is_exit=True),
            dict(is_perimeter=True),
            dict(is_entrance=True, is_perimeter=True),
            *[dict(room_type=room_type) for room_type in
              ("kirish", "auditoriya", "laboratoriya", "koridor", "ofis", "cheklangan", "tashqi")],
            dict(room_type="auditoriya", is_entrance=True),
        ]
        cameras = []
        for index, flags in enumerate(variants):
            camera = Camera(
                name=f"Kamera {index}", ip=f"10.5.0.{index}", building_id=building.id, zone="Z",
                resolution="1080p", status="faol", **flags,
            )
            db_session.add(camera)
            cameras.append(camera)
        await db_session.commit()

        for code in [*MODULE_ROOM_TYPES, 14]:
            chosen = set((await db_session.execute(select(Camera.id).where(camera_allows_module(code)))).scalars())
            expected = {camera.id for camera in cameras if role_allows(camera, code)}
            assert chosen == expected, code


@pytest.mark.usefixtures("seeded")
class TestRolesCsv:
    async def _camera(self, db_session, name: str, ip: str, **fields) -> Camera:
        building = (await db_session.execute(select(Building))).scalars().first()
        camera = Camera(name=name, ip=ip, building_id=building.id, zone="Z", resolution="1080p", status="faol", **fields)
        db_session.add(camera)
        await db_session.commit()
        return camera

    async def test_export_preview_then_apply(self, client: AsyncClient, db_session):
        room = await self._camera(db_session, "IPC (192.168.0.53)", "192.168.0.53")
        lab = await self._camera(db_session, "Lab kamera", "192.168.0.54", room_type="koridor")
        headers = await auth_headers(client, "admin", "admin123")

        exported = await client.get("/api/cameras/roles.csv", headers=headers)
        assert exported.status_code == 200
        assert exported.content.startswith("﻿".encode())
        assert "xona_turi" in exported.text

        csv_text = (
            "id;nomi;xona_turi;xona_raqami\n"
            f"{room.id};x;Auditoriya (dars xonasi);211-xona\n"
            f"{lab.id};x;laboratoriya;\n"
            "no-such-id;x;auditoriya;1\n"
            f"{room.id};x;auditoriya;2\n"
        )
        files = {"file": ("rollar.csv", csv_text.encode("utf-8"), "text/csv")}

        preview = (await client.post("/api/cameras/roles/import", headers=headers, files=files)).json()
        assert preview["applied"] is False
        assert {(c["cameraName"], c["field"], c["new"]) for c in preview["changes"]} == {
            ("IPC (192.168.0.53)", "room_type", "auditoriya"),
            ("IPC (192.168.0.53)", "room_code", "211"),
            ("Lab kamera", "room_type", "laboratoriya"),
        }
        assert [e["row"] for e in preview["errors"]] == [4, 5]  # topilmadi, takror
        await db_session.refresh(room)
        assert room.room_type is None  # oldindan ko'rish hech narsa yozmaydi

        applied = (await client.post("/api/cameras/roles/import?apply=true", headers=headers, files=files)).json()
        assert applied["applied"] is True
        await db_session.refresh(room)
        await db_session.refresh(lab)
        assert (room.room_type, room.room_code) == ("auditoriya", "211")
        assert lab.room_type == "laboratoriya"

    async def test_a_bad_room_type_skips_the_whole_row(self, client: AsyncClient, db_session):
        camera = await self._camera(db_session, "Kamera", "192.168.0.60")
        headers = await auth_headers(client, "admin", "admin123")
        files = {"file": ("r.csv", f"id,xona_turi,xona_raqami\n{camera.id},oshxona,5\n".encode(), "text/csv")}
        result = (await client.post("/api/cameras/roles/import?apply=true", headers=headers, files=files)).json()
        assert result["changes"] == [] and len(result["errors"]) == 1
        await db_session.refresh(camera)
        assert camera.room_code is None

    async def test_location_patch_sets_and_clears_the_role(self, client: AsyncClient, db_session):
        camera = await self._camera(db_session, "Kamera", "192.168.0.61", is_entrance=True)
        headers = await auth_headers(client, "admin", "admin123")
        out = (
            await client.patch(
                f"/api/cameras/{camera.id}/location", headers=headers, json={"roomType": "koridor", "roomCode": "Aud. 12"}
            )
        ).json()
        assert (out["roomType"], out["effectiveRoomType"], out["roomCode"]) == ("koridor", "koridor", "12")
        out = (
            await client.patch(f"/api/cameras/{camera.id}/location", headers=headers, json={"clearRoomType": True})
        ).json()
        assert (out["roomType"], out["effectiveRoomType"]) == (None, "kirish")


def test_entrance_is_recognised_by_name():
    from types import SimpleNamespace

    from app.services.camera_roles import is_door_camera

    def cam(name, room_type=None):
        return SimpleNamespace(name=name, room_type=room_type, is_entrance=False, is_exit=False)

    assert is_door_camera(cam("Asosiy kirish"))
    assert is_door_camera(cam("2-KIRISH"))
    assert not is_door_camera(cam("1-xona koridori"))
    assert not is_door_camera(cam("Kirish koridori"))  # yo'lak, eshik emas
    assert not is_door_camera(cam("Asosiy kirish", room_type="auditoriya"))  # tur aniq berilgan
    assert not is_door_camera(cam("IPC-T280HA-LUF/SL (192.168.0.12)"))
