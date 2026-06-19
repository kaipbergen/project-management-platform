"""Integration tests for /api/v1/auth endpoints."""

import pytest
from httpx import AsyncClient


class TestRegister:
    async def test_register_success(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "login": "newuser",
                "password": "Password123!",
                "repeat_password": "Password123!",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["login"] == "newuser"
        assert "id" in data
        assert "hashed_password" not in data

    async def test_register_duplicate_login(self, client: AsyncClient) -> None:
        payload = {
            "login": "dupuser",
            "password": "Password123!",
            "repeat_password": "Password123!",
        }
        await client.post("/api/v1/auth/register", json=payload)
        resp = await client.post("/api/v1/auth/register", json=payload)
        assert resp.status_code == 409

    async def test_register_passwords_mismatch(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "login": "mismatch_user",
                "password": "Password123!",
                "repeat_password": "Different123!",
            },
        )
        assert resp.status_code == 422

    async def test_register_short_password(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/register",
            json={"login": "shortpass", "password": "abc", "repeat_password": "abc"},
        )
        assert resp.status_code == 422

    async def test_register_invalid_login_chars(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "login": "bad login!",
                "password": "Password123!",
                "repeat_password": "Password123!",
            },
        )
        assert resp.status_code == 422


class TestLogin:
    async def test_login_success(
        self, client: AsyncClient, registered_user: dict
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/login",
            json={
                "login": registered_user["login"],
                "password": registered_user["password"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["access_expires_in"] == 15 * 60
        assert "refresh_token" in data

    async def test_login_wrong_password(
        self, client: AsyncClient, registered_user: dict
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"login": registered_user["login"], "password": "wrongpass"},
        )
        assert resp.status_code == 401

    async def test_login_nonexistent_user(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"login": "ghost_user", "password": "Password123!"},
        )
        assert resp.status_code == 401
