"""Integration tests for /api/v1/projects endpoints."""

import uuid

import pytest
from httpx import AsyncClient


class TestCreateProject:
    async def test_create_project_success(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        resp = await client.post(
            "/api/v1/projects",
            json={"name": "My Project", "description": "Test desc"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My Project"
        assert data["description"] == "Test desc"
        assert "id" in data
        assert data["total_size_bytes"] == 0

    async def test_create_project_no_auth(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/projects", json={"name": "Unauth Project"}
        )
        assert resp.status_code == 401

    async def test_create_project_empty_name(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        resp = await client.post(
            "/api/v1/projects", json={"name": ""}, headers=auth_headers
        )
        assert resp.status_code == 422


class TestListProjects:
    async def test_list_projects_empty(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        resp = await client.get("/api/v1/projects", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "meta" in data

    async def test_list_projects_contains_created(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        await client.post(
            "/api/v1/projects",
            json={"name": "Listed Project"},
            headers=auth_headers,
        )
        resp = await client.get("/api/v1/projects", headers=auth_headers)
        assert resp.status_code == 200
        names = [p["name"] for p in resp.json()["items"]]
        assert "Listed Project" in names


class TestGetProjectInfo:
    async def test_get_project_info(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        create_resp = await client.post(
            "/api/v1/projects",
            json={"name": "Info Project"},
            headers=auth_headers,
        )
        project_id = create_resp.json()["id"]

        resp = await client.get(
            f"/api/v1/projects/{project_id}/info", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == project_id

    async def test_get_nonexistent_project(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        resp = await client.get(
            f"/api/v1/projects/{uuid.uuid4()}/info", headers=auth_headers
        )
        assert resp.status_code == 404

    async def test_no_access_to_others_project(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        # Create second user
        second = await client.post(
            "/api/v1/auth/register",
            json={
                "login": "second_user_info",
                "password": "Password123!",
                "repeat_password": "Password123!",
            },
        )
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"login": "second_user_info", "password": "Password123!"},
        )
        second_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        # First user creates project
        create_resp = await client.post(
            "/api/v1/projects",
            json={"name": "Private Project"},
            headers=auth_headers,
        )
        project_id = create_resp.json()["id"]

        # Second user tries to access it
        resp = await client.get(
            f"/api/v1/projects/{project_id}/info", headers=second_headers
        )
        assert resp.status_code == 403


class TestUpdateProject:
    async def test_update_project(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        create_resp = await client.post(
            "/api/v1/projects",
            json={"name": "Old Name"},
            headers=auth_headers,
        )
        project_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/v1/projects/{project_id}/info",
            json={"name": "New Name"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    async def test_update_requires_at_least_one_field(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        create_resp = await client.post(
            "/api/v1/projects", json={"name": "Update Fail"}, headers=auth_headers
        )
        project_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/v1/projects/{project_id}/info",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 422


class TestDeleteProject:
    async def test_delete_project_owner(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        create_resp = await client.post(
            "/api/v1/projects",
            json={"name": "To Delete"},
            headers=auth_headers,
        )
        project_id = create_resp.json()["id"]

        resp = await client.delete(
            f"/api/v1/projects/{project_id}", headers=auth_headers
        )
        assert resp.status_code == 204

        # Verify gone
        get_resp = await client.get(
            f"/api/v1/projects/{project_id}/info", headers=auth_headers
        )
        assert get_resp.status_code == 404

    async def test_participant_cannot_delete(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        # Owner creates project
        create_resp = await client.post(
            "/api/v1/projects", json={"name": "Owner's Project"}, headers=auth_headers
        )
        project_id = create_resp.json()["id"]

        # Register participant
        await client.post(
            "/api/v1/auth/register",
            json={
                "login": "participant_del",
                "password": "Password123!",
                "repeat_password": "Password123!",
            },
        )
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"login": "participant_del", "password": "Password123!"},
        )
        participant_headers = {
            "Authorization": f"Bearer {login_resp.json()['access_token']}"
        }

        # Owner invites participant
        await client.post(
            f"/api/v1/projects/{project_id}/invite",
            json={"user_login": "participant_del"},
            headers=auth_headers,
        )

        # Participant tries to delete
        resp = await client.delete(
            f"/api/v1/projects/{project_id}", headers=participant_headers
        )
        assert resp.status_code == 403


class TestInviteUser:
    async def test_invite_success(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        await client.post(
            "/api/v1/auth/register",
            json={
                "login": "invitee_user",
                "password": "Password123!",
                "repeat_password": "Password123!",
            },
        )
        create_resp = await client.post(
            "/api/v1/projects", json={"name": "Team Project"}, headers=auth_headers
        )
        project_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/projects/{project_id}/invite",
            json={"user_login": "invitee_user"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "successfully invited" in resp.json()["message"]

    async def test_invite_nonexistent_user(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        create_resp = await client.post(
            "/api/v1/projects", json={"name": "Ghost Invite"}, headers=auth_headers
        )
        project_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/projects/{project_id}/invite",
            json={"user_login": "ghost_user_xyz"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_double_invite_conflict(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        await client.post(
            "/api/v1/auth/register",
            json={
                "login": "double_invite",
                "password": "Password123!",
                "repeat_password": "Password123!",
            },
        )
        create_resp = await client.post(
            "/api/v1/projects", json={"name": "Conflict Project"}, headers=auth_headers
        )
        project_id = create_resp.json()["id"]

        await client.post(
            f"/api/v1/projects/{project_id}/invite",
            json={"user_login": "double_invite"},
            headers=auth_headers,
        )
        resp = await client.post(
            f"/api/v1/projects/{project_id}/invite",
            json={"user_login": "double_invite"},
            headers=auth_headers,
        )
        assert resp.status_code == 409
