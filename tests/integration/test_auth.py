"""
tests/integration/test_auth.py
--------------------------------
Integration tests for authentication endpoints.

Integration tests = real HTTP requests through the full FastAPI stack,
real database writes and reads, real JWT generation.

What makes these different from unit tests:
  We're testing the FULL flow — HTTP → middleware → router → DB → response.
  A bug in how the router builds the response, how middleware intercepts
  the request, or how the DB session is managed will be caught here.

Test naming convention:
  test_<endpoint>_<scenario>_<expected_outcome>
  e.g. test_login_valid_credentials_returns_tokens

This naming makes test failure messages immediately clear:
  FAILED tests/integration/test_auth.py::test_login_wrong_password_returns_401
  → You know exactly what broke without reading the test body.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestLogin:

    async def test_login_valid_credentials_returns_tokens(
        self, client: AsyncClient, test_admin_user
    ):
        """
        Happy path: valid credentials → both tokens returned.
        This is the most important auth test.
        """
        response = await client.post("/v1/auth/login", json={
            "email": "admin@test.ac.ae",
            "password": "Admin@1234",
        })

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0
        # Tokens should be non-empty strings
        assert len(data["access_token"]) > 20
        assert len(data["refresh_token"]) > 20

    async def test_login_wrong_password_returns_401(
        self, client: AsyncClient, test_admin_user
    ):
        response = await client.post("/v1/auth/login", json={
            "email": "admin@test.ac.ae",
            "password": "WrongPassword@123",
        })
        assert response.status_code == 401
        error = response.json()["error"]
        assert error["code"] == "INVALID_CREDENTIALS"

    async def test_login_nonexistent_email_returns_401(
        self, client: AsyncClient
    ):
        """
        Non-existent email should return same error as wrong password.
        Uniform error prevents email enumeration attacks.
        """
        response = await client.post("/v1/auth/login", json={
            "email": "nobody@university.ac.ae",
            "password": "SomePassword@123",
        })
        assert response.status_code == 401
        # Must return same error code as wrong password — no information leakage
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"

    async def test_login_inactive_user_returns_403(
        self, client: AsyncClient, db_session, test_admin_user
    ):
        """Suspended/inactive users cannot log in even with correct credentials."""
        # Suspend the user
        test_admin_user.is_active = False
        await db_session.flush()

        response = await client.post("/v1/auth/login", json={
            "email": "admin@test.ac.ae",
            "password": "Admin@1234",
        })
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "ACCOUNT_SUSPENDED"

    async def test_login_missing_email_returns_422(self, client: AsyncClient):
        """Pydantic validation catches missing required fields."""
        response = await client.post("/v1/auth/login", json={
            "password": "Admin@1234",
        })
        assert response.status_code == 422

    async def test_login_invalid_email_format_returns_422(self, client: AsyncClient):
        response = await client.post("/v1/auth/login", json={
            "email": "not-an-email",
            "password": "Admin@1234",
        })
        assert response.status_code == 422


@pytest.mark.asyncio
class TestTokenRefresh:

    async def test_refresh_valid_token_returns_new_tokens(
        self, client: AsyncClient, test_admin_user
    ):
        """Refresh flow: login → get refresh token → use it to get new access token."""
        # Step 1: Login
        login_response = await client.post("/v1/auth/login", json={
            "email": "admin@test.ac.ae",
            "password": "Admin@1234",
        })
        refresh_token = login_response.json()["refresh_token"]
        old_access_token = login_response.json()["access_token"]

        # Step 2: Refresh
        refresh_response = await client.post("/v1/auth/refresh", json={
            "refresh_token": refresh_token,
        })

        assert refresh_response.status_code == 200
        new_data = refresh_response.json()
        assert "access_token" in new_data
        # New access token should be different (different iat timestamp)
        assert new_data["access_token"] != old_access_token

    async def test_refresh_with_access_token_returns_401(
        self, client: AsyncClient, test_admin_user
    ):
        """
        Using an ACCESS token where a REFRESH token is expected must fail.
        Token type confusion is a real attack vector.
        """
        login_response = await client.post("/v1/auth/login", json={
            "email": "admin@test.ac.ae",
            "password": "Admin@1234",
        })
        access_token = login_response.json()["access_token"]

        # Try to use access token as refresh token
        response = await client.post("/v1/auth/refresh", json={
            "refresh_token": access_token,  # wrong token type
        })
        assert response.status_code == 401

    async def test_refresh_with_garbage_token_returns_401(self, client: AsyncClient):
        response = await client.post("/v1/auth/refresh", json={
            "refresh_token": "this.is.garbage",
        })
        assert response.status_code == 401


@pytest.mark.asyncio
class TestAuthMiddleware:

    async def test_protected_endpoint_without_token_returns_401(
        self, client: AsyncClient
    ):
        """Every protected endpoint must reject requests with no token."""
        response = await client.get("/v1/students")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "MISSING_TOKEN"

    async def test_protected_endpoint_with_invalid_token_returns_401(
        self, client: AsyncClient
    ):
        response = await client.get(
            "/v1/students",
            headers={"Authorization": "Bearer this.is.invalid"}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_TOKEN"

    async def test_protected_endpoint_with_valid_token_passes_auth(
        self, client: AsyncClient, admin_headers
    ):
        """Valid admin token should get past auth (may still get 404 etc but not 401/403)."""
        response = await client.get("/v1/students", headers=admin_headers)
        # Auth passed — we get a real response (200 with empty list)
        assert response.status_code != 401
        assert response.status_code != 403
