"""Videodevor ko'rinishlari serverda: ro'yxat (o'ziniki + umumiy), egalik
qoidasi, systemSettings admini, bir martalik import."""

import uuid

import pytest

from app.models import User
from app.security import hash_password
from app.services.security_checks import DEMO_PASSWORDS
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

URL = "/api/devor-korinishlar"
OTHER = ("operator_ikki", "operator-ikki-123")
STEWARD = ("steward_wall", "steward-wall-123")
PAYLOAD = {"layout": "2x2", "tiles": ["cam-1", None, None, None]}


@pytest.fixture
async def users(db_session, seeded):
    db_session.add_all(
        [
            User(login=OTHER[0], password_hash=hash_password(OTHER[1]), full_name="Ikkinchi Operator", role="admin"),
            User(login=STEWARD[0], password_hash=hash_password(STEWARD[1]), full_name="Kamera Mas'uli", role="kamera-masuli"),
        ]
    )
    await db_session.commit()


async def _headers(client, who: str) -> dict:
    if who == "admin":
        return await auth_headers(client, "admin", DEMO_PASSWORDS["admin"])
    if who == "operator":
        return await auth_headers(client, "operator", DEMO_PASSWORDS["operator"])
    if who == "other":
        return await auth_headers(client, *OTHER)
    return await auth_headers(client, *STEWARD)


async def test_create_list_shared_and_private(client, users):
    op = await _headers(client, "operator")
    other = await _headers(client, "other")

    client_id = str(uuid.uuid4())
    resp = await client.post(URL, json={"id": client_id, "name": " Kirishlar ", "payload": PAYLOAD}, headers=op)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"] == client_id  # brauzer id'si saqlanadi (?view= havolalari)
    assert body["name"] == "Kirishlar"
    assert body["shared"] is True and body["mine"] is True and body["canEdit"] is True
    assert body["ownerName"] == "Behzod Karimov"
    assert body["payload"] == PAYLOAD

    resp = await client.post(URL, json={"name": "Shaxsiy", "payload": PAYLOAD, "shared": False}, headers=op)
    assert resp.status_code == 201

    mine = (await client.get(URL, headers=op)).json()
    assert [v["name"] for v in mine] == ["Kirishlar", "Shaxsiy"]

    theirs = (await client.get(URL, headers=other)).json()
    assert [v["name"] for v in theirs] == ["Kirishlar"]
    assert theirs[0]["mine"] is False and theirs[0]["canEdit"] is False

    # Tur sozlamalari alohida ro'yxat.
    assert (await client.get(URL, params={"kind": "tour"}, headers=op)).json() == []


async def test_taken_or_invalid_client_id_gets_new_one(client, users):
    op = await _headers(client, "operator")
    first = (await client.post(URL, json={"name": "A", "payload": PAYLOAD}, headers=op)).json()
    again = await client.post(URL, json={"id": first["id"], "name": "B", "payload": PAYLOAD}, headers=op)
    assert again.status_code == 201 and again.json()["id"] != first["id"]
    legacy = await client.post(URL, json={"id": "v-abc123", "name": "C", "payload": PAYLOAD}, headers=op)
    assert legacy.status_code == 201
    uuid.UUID(legacy.json()["id"])


async def test_only_owner_or_system_admin_edits(client, users):
    op = await _headers(client, "operator")
    other = await _headers(client, "other")
    admin = await _headers(client, "admin")
    view = (await client.post(URL, json={"name": "Umumiy", "payload": PAYLOAD}, headers=op)).json()

    assert (await client.patch(f"{URL}/{view['id']}", json={"name": "X"}, headers=other)).status_code == 403
    assert (await client.delete(f"{URL}/{view['id']}", headers=other)).status_code == 403

    resp = await client.patch(
        f"{URL}/{view['id']}", json={"name": "Yangi", "payload": {"layout": "1x1", "tiles": ["cam-9"]}}, headers=op
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Yangi" and resp.json()["payload"]["layout"] == "1x1"

    # systemSettings egasi boshqaning ko'rinishini ham tuzatadi.
    admin_list = (await client.get(URL, headers=admin)).json()
    assert admin_list[0]["canEdit"] is True and admin_list[0]["mine"] is False
    assert (await client.patch(f"{URL}/{view['id']}", json={"shared": False}, headers=admin)).status_code == 200
    # Endi ulashilmagan — boshqa operator uni umuman ko'rmaydi.
    assert (await client.get(URL, headers=other)).json() == []
    assert (await client.delete(f"{URL}/{view['id']}", headers=other)).status_code == 404

    assert (await client.delete(f"{URL}/{view['id']}", headers=op)).status_code == 204
    assert (await client.get(URL, headers=op)).json() == []


async def test_requires_view_live(client, users):
    steward = await _headers(client, "steward")
    assert (await client.get(URL, headers=steward)).status_code == 403
    assert (await client.post(URL, json={"name": "A", "payload": PAYLOAD}, headers=steward)).status_code == 403
    assert (await client.get(URL)).status_code == 401


async def test_payload_limits(client, users):
    op = await _headers(client, "operator")
    big = {"layout": "5x5", "tiles": ["x" * 1000] * 20}
    assert (await client.post(URL, json={"name": "Katta", "payload": big}, headers=op)).status_code == 413
    assert (await client.post(URL, json={"name": "   ", "payload": PAYLOAD}, headers=op)).status_code == 422
    assert (await client.post(URL, json={"name": "A", "kind": "boshqa", "payload": PAYLOAD}, headers=op)).status_code == 422


async def test_import_is_idempotent_and_respects_ownership(client, users):
    op = await _headers(client, "operator")
    other = await _headers(client, "other")
    foreign = (await client.post(URL, json={"name": "Begona", "payload": PAYLOAD}, headers=other)).json()

    local_id = str(uuid.uuid4())
    items = [
        {"id": local_id, "name": "Mahalliy", "payload": PAYLOAD, "updatedAt": "2026-09-01T10:00:00Z"},
        {"id": "v-eski", "name": "Eski id", "payload": PAYLOAD},
        {"id": foreign["id"], "name": "Egallash", "payload": PAYLOAD},
        {"name": "  ", "payload": PAYLOAD},
    ]
    resp = await client.post(f"{URL}/import", json={"items": items}, headers=op)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["created"], body["updated"], body["skipped"]) == (2, 0, 2)
    names = sorted(v["name"] for v in body["items"])
    assert names == ["Begona", "Eski id", "Mahalliy"]

    # Qayta import: eski sana — hech narsa o'zgarmaydi; yangi sana — yangilanadi.
    again = (await client.post(f"{URL}/import", json={"items": items[:1]}, headers=op)).json()
    assert (again["created"], again["updated"]) == (0, 0)
    newer = {**items[0], "name": "Mahalliy 2", "updatedAt": "2099-01-01T00:00:00Z"}
    again = (await client.post(f"{URL}/import", json={"items": [newer]}, headers=op)).json()
    assert again["updated"] == 1
    assert "Mahalliy 2" in [v["name"] for v in again["items"]]

    # Begona ko'rinish o'zgarmagan.
    theirs = (await client.get(URL, headers=other)).json()
    assert [v["name"] for v in theirs if v["mine"]] == ["Begona"]
