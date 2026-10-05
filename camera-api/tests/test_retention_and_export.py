"""Eski tashriflar va notanish yuzlarni tozalash; shaxs ma'lumotlari eksporti huquqi."""

from datetime import datetime, timedelta, timezone

from httpx import AsyncClient

from app.jobs import cleanup
from app.models import Camera, PresenceVisit, StudentStaff, UnknownSighting
from tests.conftest import auth_headers


async def test_old_visits_and_unknown_faces_are_pruned(db_session, seeded, monkeypatch):
    deleted: list[str] = []

    async def fake_delete(keys):
        deleted.extend(keys)
        return len(keys)

    monkeypatch.setattr(cleanup, "delete_files_quietly", fake_delete)
    now = datetime.now(timezone.utc)
    person = StudentStaff(full_name="Eski Tashrif", type="xodim", group_or_position="X")
    camera = Camera(name="Tozalash", ip="10.9.9.9", zone="Z", resolution="1080p", status="faol")
    db_session.add_all([person, camera])
    await db_session.flush()
    db_session.add_all([
        PresenceVisit(student_staff_id=person.id, camera_id=camera.id, first_seen_at=now - timedelta(days=400),
                      last_seen_at=now - timedelta(days=400), sightings=1),
        PresenceVisit(student_staff_id=person.id, camera_id=camera.id, first_seen_at=now - timedelta(days=3),
                      last_seen_at=now - timedelta(days=3), sightings=1),
        UnknownSighting(day=(now - timedelta(days=120)).date(), camera_id=camera.id, first_seen_at=now - timedelta(days=120),
                        last_seen_at=now - timedelta(days=120), hits=1, embedding="[]", crop_key="unknown/old.jpg",
                        face_px=60, status="kutilmoqda"),
        UnknownSighting(day=now.date(), camera_id=camera.id, first_seen_at=now, last_seen_at=now, hits=1,
                        embedding="[]", crop_key="unknown/new.jpg", face_px=60, status="kutilmoqda"),
    ])
    await db_session.commit()

    counts = await cleanup.run_cleanup_once(db_session)
    assert counts["presence_visits"] == 1 and counts["unknown_sightings"] == 1
    assert deleted == ["unknown/old.jpg"]
    from sqlalchemy import func, select

    assert await db_session.scalar(select(func.count()).select_from(PresenceVisit)) == 1
    assert await db_session.scalar(select(func.count()).select_from(UnknownSighting)) == 1


async def test_personal_data_export_needs_its_own_permission(client: AsyncClient, seeded):
    # "operator" — Admin: reestrni ko'radi, lekin standart bo'yicha eksport huquqi yo'q.
    admin = await auth_headers(client, "operator", "operator123")
    assert (await client.get("/api/students-staff/export", headers=admin)).status_code == 403
    super_admin = await auth_headers(client, "admin", "admin123")
    assert (await client.get("/api/students-staff/export", headers=super_admin)).status_code == 200


async def test_post_export_and_events_pdf_need_export_permission(client: AsyncClient, seeded):
    """POST /export ham JSHSHIR'li o'sha faylni beradi — huquq GET bilan bir xil."""
    admin = await auth_headers(client, "operator", "operator123")
    res = await client.post("/api/students-staff/export", headers=admin, json={"kind": "people"})
    assert res.status_code == 403
    assert (await client.get("/api/events/export.pdf", headers=admin)).status_code == 403
    super_admin = await auth_headers(client, "admin", "admin123")
    res = await client.post("/api/students-staff/export", headers=super_admin, json={"kind": "people"})
    assert res.status_code == 200


async def test_only_author_or_super_admin_deletes_a_report(client: AsyncClient, db_session, seeded):
    from app.models import Report

    report = Report(period="Kunlik", period_label="Sinov", summary="", body="", created_by="Boshqa Muallif")
    db_session.add(report)
    await db_session.commit()
    admin = await auth_headers(client, "operator", "operator123")
    res = await client.delete(f"/api/reports/{report.id}", headers=admin)
    assert res.status_code == 403 and "muallif" in res.json()["detail"]
    super_admin = await auth_headers(client, "admin", "admin123")
    assert (await client.delete(f"/api/reports/{report.id}", headers=super_admin)).status_code == 204
