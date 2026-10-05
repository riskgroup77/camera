"""Odamni ro'yxatdan o'chirish — DELETE /api/students-staff/{id}.

O'chirish qaytarib bo'lmaydigan amal va u odamning davomat tarixini ham
olib ketadi, shuning uchun bu yerda tekshiriladigan narsalar: to'g'ri
qatorgina o'chishi, bog'liq yozuvlar ham ketishi, yuz vektori keshdan
chiqarilishi (aks holda o'chirilgan odam kameralarda tanilaverardi) va
amalning audit jurnaliga tushishi.
"""

from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.models import AttendanceRecord, AuditLog, Camera, PresenceVisit, StudentStaff
from tests.conftest import auth_headers


async def _person(client: AsyncClient, headers, name: str, person_type: str = "talaba") -> str:
    resp = await client.post(
        "/api/students-staff",
        headers=headers,
        json={
            "fullName": name,
            "type": person_type,
            "faculty": "Davolash ishi",
            "groupOrPosition": "302-guruh" if person_type == "talaba" else "Laborant",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.usefixtures("seeded")
class TestDeletePerson:
    async def test_deletes_only_the_chosen_person(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        doomed = await _person(client, headers, "O'chiriladigan Talaba")
        kept = await _person(client, headers, "Qoladigan Talaba")

        resp = await client.delete(f"/api/students-staff/{doomed}", headers=headers)
        assert resp.status_code == 204

        listed = (await client.get("/api/students-staff", headers=headers, params={"pageSize": 100})).json()
        names = [item["fullName"] for item in listed["items"]]
        assert "O'chiriladigan Talaba" not in names
        assert "Qoladigan Talaba" in names
        assert kept  # qolgan yozuv tegilmagan

    async def test_attendance_and_visits_go_with_the_person(self, client: AsyncClient, db_session):
        headers = await auth_headers(client, "admin", "admin123")
        person_id = await _person(client, headers, "Tarixi Bor Xodim", person_type="xodim")
        person = await db_session.get(StudentStaff, person_id)
        camera = (await db_session.execute(select(Camera))).scalars().first()
        if camera is None:
            camera = Camera(name="Kirish-D", ip="10.9.9.9", zone="Kirish", resolution="1080p", status="faol")
            db_session.add(camera)
            await db_session.commit()
        db_session.add_all(
            [
                AttendanceRecord(student_staff_id=person.id, date=date(2026, 9, 14), status="keldi"),
                PresenceVisit(
                    student_staff_id=person.id,
                    camera_id=camera.id,
                    first_seen_at=datetime.now(timezone.utc),
                    last_seen_at=datetime.now(timezone.utc),
                    sightings=1,
                ),
            ]
        )
        await db_session.commit()

        assert (await client.delete(f"/api/students-staff/{person_id}", headers=headers)).status_code == 204

        attendance = await db_session.scalar(
            select(func.count()).select_from(AttendanceRecord).where(AttendanceRecord.student_staff_id == person_id)
        )
        visits = await db_session.scalar(
            select(func.count()).select_from(PresenceVisit).where(PresenceVisit.student_staff_id == person_id)
        )
        assert attendance == 0 and visits == 0

    async def test_face_cache_is_invalidated(self, client: AsyncClient, monkeypatch):
        """Kesh bekor qilinmasa, o'chirilgan odam sweep keshi yangilanguncha
        (bir necha daqiqa) kameralarda tanilishda davom etardi."""
        from app.routers import students_staff

        calls: list[int] = []
        async def record_change():
            calls.append(1)

        monkeypatch.setattr(students_staff, "announce_roster_change", record_change)
        headers = await auth_headers(client, "admin", "admin123")
        person_id = await _person(client, headers, "Keshdagi Talaba")

        assert (await client.delete(f"/api/students-staff/{person_id}", headers=headers)).status_code == 204
        assert calls == [1]

    async def test_deletion_is_written_to_the_audit_log(self, client: AsyncClient, db_session):
        headers = await auth_headers(client, "admin", "admin123")
        person_id = await _person(client, headers, "Audit Uchun Xodim", person_type="xodim")

        assert (await client.delete(f"/api/students-staff/{person_id}", headers=headers)).status_code == 204

        entries = (
            await db_session.execute(select(AuditLog.action).order_by(AuditLog.occurred_at.desc()).limit(5))
        ).scalars().all()
        assert any("Ro'yxatdan o'chirdi" in entry and "Audit Uchun Xodim" in entry for entry in entries)

    async def test_unknown_id_is_404(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        missing = await client.delete(
            "/api/students-staff/00000000-0000-0000-0000-000000000000", headers=headers
        )
        assert missing.status_code == 404
        assert (await client.delete("/api/students-staff/not-a-uuid", headers=headers)).status_code == 404

    async def test_requires_the_register_people_permission(self, client: AsyncClient):
        super_headers = await auth_headers(client, "admin", "admin123")
        person_id = await _person(client, super_headers, "Himoyalangan Talaba")
        await client.patch("/api/permissions/registerPeople", headers=super_headers, json={"role": "admin"})

        operator_headers = await auth_headers(client, "operator", "operator123")
        assert (await client.delete(f"/api/students-staff/{person_id}", headers=operator_headers)).status_code == 403
