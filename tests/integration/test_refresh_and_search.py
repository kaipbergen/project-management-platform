"""Tests for refresh token rotation and project search."""

import pytest
from httpx import AsyncClient


# ── Refresh token flow ────────────────────────────────────────────────────────

class TestRefreshToken:
    async def test_login_returns_token_pair(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/auth/register",
            json={"login": "rt_user1", "password": "Password123!", "repeat_password": "Password123!"},
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"login": "rt_user1", "password": "Password123!"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["access_expires_in"] == 60 * 60
        assert data["refresh_expires_in"] == 7 * 86400

    async def test_refresh_returns_new_pair(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/auth/register",
            json={"login": "rt_user2", "password": "Password123!", "repeat_password": "Password123!"},
        )
        login = await client.post(
            "/api/v1/auth/login",
            json={"login": "rt_user2", "password": "Password123!"},
        )
        old_refresh = login.json()["refresh_token"]
        old_access = login.json()["access_token"]

        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        assert resp.status_code == 200
        new_data = resp.json()
        assert "access_token" in new_data
        assert "refresh_token" in new_data
        # New tokens must differ from old ones
        assert new_data["access_token"] != old_access
        assert new_data["refresh_token"] != old_refresh

    async def test_old_refresh_token_invalid_after_rotation(
        self, client: AsyncClient
    ) -> None:
        await client.post(
            "/api/v1/auth/register",
            json={"login": "rt_user3", "password": "Password123!", "repeat_password": "Password123!"},
        )
        login = await client.post(
            "/api/v1/auth/login",
            json={"login": "rt_user3", "password": "Password123!"},
        )
        old_refresh = login.json()["refresh_token"]

        # First rotation — valid
        await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})

        # Second use of old token — must fail (rotation revokes it)
        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        assert resp.status_code == 401

    async def test_reuse_detection_revokes_all_sessions(
        self, client: AsyncClient
    ) -> None:
        """Using a rotated token should revoke ALL sessions for security."""
        await client.post(
            "/api/v1/auth/register",
            json={"login": "rt_user4", "password": "Password123!", "repeat_password": "Password123!"},
        )
        login = await client.post(
            "/api/v1/auth/login",
            json={"login": "rt_user4", "password": "Password123!"},
        )
        token_a = login.json()["refresh_token"]

        # Rotate once — token_b is valid, token_a is revoked
        rotate1 = await client.post("/api/v1/auth/refresh", json={"refresh_token": token_a})
        token_b = rotate1.json()["refresh_token"]

        # Attacker replays token_a → triggers reuse detection → all sessions revoked
        reuse_resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": token_a})
        assert reuse_resp.status_code == 401

        # token_b should also be invalid now (all sessions revoked)
        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": token_b})
        assert resp.status_code == 401

    async def test_invalid_refresh_token_rejected(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "completely-fake-token"},
        )
        assert resp.status_code == 401

    async def test_logout_revokes_refresh_token(self, client: AsyncClient) -> None:
        await client.post(
            "/api/v1/auth/register",
            json={"login": "rt_logout", "password": "Password123!", "repeat_password": "Password123!"},
        )
        login = await client.post(
            "/api/v1/auth/login",
            json={"login": "rt_logout", "password": "Password123!"},
        )
        refresh = login.json()["refresh_token"]

        logout = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
        assert logout.status_code == 200

        # Token should now be invalid
        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        assert resp.status_code == 401

    async def test_new_access_token_authorizes_requests(
        self, client: AsyncClient
    ) -> None:
        await client.post(
            "/api/v1/auth/register",
            json={"login": "rt_auth_check", "password": "Password123!", "repeat_password": "Password123!"},
        )
        login = await client.post(
            "/api/v1/auth/login",
            json={"login": "rt_auth_check", "password": "Password123!"},
        )
        refresh = login.json()["refresh_token"]

        rotate = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        new_access = rotate.json()["access_token"]

        # New access token must work for protected endpoints
        resp = await client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {new_access}"},
        )
        assert resp.status_code == 200


# ── Search ────────────────────────────────────────────────────────────────────

class TestProjectSearch:
    async def test_search_by_name(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        await client.post(
            "/api/v1/projects",
            json={"name": "Alpha Analytics", "description": "data pipeline"},
            headers=auth_headers,
        )
        await client.post(
            "/api/v1/projects",
            json={"name": "Beta Backend", "description": "api service"},
            headers=auth_headers,
        )

        resp = await client.get(
            "/api/v1/projects?search=Alpha", headers=auth_headers
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all("Alpha" in p["name"] for p in items)

    async def test_search_by_description(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        await client.post(
            "/api/v1/projects",
            json={"name": "Gamma Project", "description": "machine learning pipeline"},
            headers=auth_headers,
        )

        resp = await client.get(
            "/api/v1/projects?search=machine+learning", headers=auth_headers
        )
        assert resp.status_code == 200
        names = [p["name"] for p in resp.json()["items"]]
        assert "Gamma Project" in names

    async def test_search_case_insensitive(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        await client.post(
            "/api/v1/projects",
            json={"name": "Delta Dashboard"},
            headers=auth_headers,
        )

        resp = await client.get(
            "/api/v1/projects?search=delta", headers=auth_headers
        )
        assert resp.status_code == 200
        names = [p["name"] for p in resp.json()["items"]]
        assert "Delta Dashboard" in names

    async def test_search_no_match_returns_empty(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        resp = await client.get(
            "/api/v1/projects?search=xyznonexistent999", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["meta"]["total"] == 0

    async def test_search_empty_string_returns_all(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        resp_all = await client.get("/api/v1/projects", headers=auth_headers)
        resp_empty = await client.get("/api/v1/projects?search=", headers=auth_headers)
        assert resp_all.json()["meta"]["total"] == resp_empty.json()["meta"]["total"]

    async def test_search_combined_with_pagination(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        for i in range(3):
            await client.post(
                "/api/v1/projects",
                json={"name": f"Epsilon Project {i}"},
                headers=auth_headers,
            )

        resp = await client.get(
            "/api/v1/projects?search=Epsilon&page=1&size=2",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) <= 2
        assert data["meta"]["total"] >= 3
