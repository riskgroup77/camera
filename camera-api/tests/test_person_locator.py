"""Shaxs qidirish: joylashuv faqat oxirgi kuzatuv sifatida qaytadi."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Building, Camera, PresenceVisit, StudentStaff
from app.timezone import local_now
from tests.conftest import auth_headers


@pytest.fixture
async def located_person(db_session, seeded):
    building = (await db_session.execute(select(Building))).scalars().first()
    assert building is not None
    person = StudentStaff(
        full_name="Qidirilov Sinov Talaba",
        type="talaba",
        group_or_position="2-kurs, QA-101",
        biometrics_status="tasdiqlangan",
    )
    camera = Camera(
        name="QA auditoriya kamerasi",
        ip="10.90.0.10",
        building_id=building.id,
        floor=2,
        zone="211-xona",
        resolution="1280x720",
        status="faol",
    )
    db_session.add_all([person, camera])
    await db_session.flush()
    now = local_now()
    db_session.add(PresenceVisit(
        student_staff_id=person.id,
        camera_id=camera.id,
        first_seen_at=now - timedelta(minutes=2),
        last_seen_at=now - timedelta(minutes=1),
    ))
    await db_session.commit()
    return person, camera


async def test_search_returns_last_camera_location(client, located_person):
    person, camera = located_person
    headers = await auth_headers(client, "admin", "admin123")
    response = await client.post("/api/person-locator/search", headers=headers, json={"query": "Qidirilov"})
    assert response.status_code == 200, response.text
    item = response.json()[0]
    assert item["id"] == str(person.id)
    assert item["cameraId"] == str(camera.id)
    assert item["cameraName"] == "QA auditoriya kamerasi"
    assert item["floor"] == 2
    assert item["zone"] == "211-xona"
    assert item["currentlyVisible"] is True


async def test_search_requires_live_view_permission(client, located_person):
    response = await client.post("/api/person-locator/search", json={"query": "Qidirilov"})
    assert response.status_code == 401
