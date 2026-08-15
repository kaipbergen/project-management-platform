"""Tests for the optional share-link feature: GET /projects/{id}/share, GET /join."""

import uuid

from httpx import AsyncClient


async def _second_user_headers(client: AsyncClient, login: str) -> dict:
    await client.post(
        "/api/v1/auth/register",
        json={"login": login, "password": "Password123!", "repeat_password": "Password123!"},
    )
    login_resp = await client.post(
        "/api/v1/auth/login", json={"login": login, "password": "Password123!"}
    )
    return {"Authorization": f"Bearer {login_resp.json()['access_token']}"}


class TestShareLink:
    async def test_owner_can_generate_share_link(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        create_resp = await client.post(
            "/api/v1/projects", json={"name": "Shared Project"}, headers=auth_headers
        )
        project_id = create_resp.json()["id"]

        resp = await client.get(
            f"/api/v1/projects/{project_id}/share",
            params={"with": "invitee@example.com"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "join_url" in data
        assert "token=" in data["join_url"]
        assert "expires_at" in data

    async def test_non_owner_cannot_generate_share_link(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        create_resp = await client.post(
            "/api/v1/projects", json={"name": "Owner Only Project"}, headers=auth_headers
        )
        project_id = create_resp.json()["id"]
        other_headers = await _second_user_headers(client, "share_non_owner")

        resp = await client.get(
            f"/api/v1/projects/{project_id}/share",
            params={"with": "invitee@example.com"},
            headers=other_headers,
        )
        assert resp.status_code == 403

    async def test_join_grants_participant_access(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        create_resp = await client.post(
            "/api/v1/projects", json={"name": "Joinable Project"}, headers=auth_headers
        )
        project_id = create_resp.json()["id"]

        share_resp = await client.get(
            f"/api/v1/projects/{project_id}/share",
            params={"with": "joiner@example.com"},
            headers=auth_headers,
        )
        token = share_resp.json()["join_url"].split("token=")[1]

        joiner_headers = await _second_user_headers(client, "share_joiner")
        join_resp = await client.get(
            "/api/v1/join", params={"token": token}, headers=joiner_headers
        )
        assert join_resp.status_code == 200
        data = join_resp.json()
        assert data["project_id"] == project_id
        assert data["role"] == "participant"

        # Joiner now has access to the project
        info_resp = await client.get(f"/api/v1/projects/{project_id}/info", headers=joiner_headers)
        assert info_resp.status_code == 200

    async def test_join_with_invalid_token_fails(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        resp = await client.get(
            "/api/v1/join", params={"token": "not-a-real-token-xyz"}, headers=auth_headers
        )
        assert resp.status_code == 404

    async def test_share_nonexistent_project(self, client: AsyncClient, auth_headers: dict) -> None:
        resp = await client.get(
            f"/api/v1/projects/{uuid.uuid4()}/share",
            params={"with": "invitee@example.com"},
            headers=auth_headers,
        )
        assert resp.status_code == 404
