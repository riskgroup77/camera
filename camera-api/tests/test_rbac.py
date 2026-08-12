import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers


@pytest.mark.usefixtures("seeded")
class TestRBAC:
    async def test_admin_without_manage_roles_gets_403(self, client: AsyncClient):
        headers = await auth_headers(client, "operator", "operator123")
        resp = await client.get("/api/users", headers=headers)
        assert resp.status_code == 403

    async def test_super_admin_can_list_users(self, client: AsyncClient):
        headers = await auth_headers(client, "admin", "admin123")
        resp = await client.get("/api/users", headers=headers)
        assert resp.status_code == 200

    async def test_granting_permission_takes_effect_immediately(self, client: AsyncClient):
        super_headers = await auth_headers(client, "admin", "admin123")
        admin_headers = await auth_headers(client, "operator", "operator123")

        assert (await client.get("/api/users", headers=admin_headers)).status_code == 403

        toggle = await client.patch(
            "/api/permissions/manageRoles", headers=super_headers, json={"role": "admin"}
        )
        assert toggle.status_code == 200
        assert toggle.json()["admin"] is True

        assert (await client.get("/api/users", headers=admin_headers)).status_code == 200

    async def test_only_super_admin_may_toggle_permissions(self, client: AsyncClient):
        admin_headers = await auth_headers(client, "operator", "operator123")
        resp = await client.patch(
            "/api/permissions/manageCameras", headers=admin_headers, json={"role": "admin"}
        )
        assert resp.status_code == 403

    async def test_no_token_is_unauthorized(self, client: AsyncClient):
        resp = await client.get("/api/users")
        assert resp.status_code == 401

    async def test_garbage_token_is_unauthorized(self, client: AsyncClient):
        resp = await client.get("/api/users", headers={"Authorization": "Bearer not-a-real-token"})
        assert resp.status_code == 401

    async def test_org_structure_needs_no_specific_permission(self, client: AsyncClient):
        """Matches AdminLayout.tsx: org-structure nav has no `permission` key."""
        headers = await auth_headers(client, "operator", "operator123")
        resp = await client.get("/api/buildings", headers=headers)
        assert resp.status_code == 200

    async def test_any_authenticated_user_can_read_permission_matrix(self, client: AsyncClient):
        """GET /api/permissions must be readable by every logged-in user (not just
        manageRoles holders) — AdminLayout/RequirePermission need it to filter nav
        for roles that by definition lack manageRoles."""
        headers = await auth_headers(client, "operator", "operator123")
        resp = await client.get("/api/permissions", headers=headers)
        assert resp.status_code == 200
        assert "manageRoles" in resp.json()
