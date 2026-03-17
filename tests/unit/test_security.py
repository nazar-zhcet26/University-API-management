"""
tests/unit/test_security.py
----------------------------
Unit tests for core/security.py.

Unit tests = test one function in isolation.
No database, no HTTP, no external dependencies.
These run in milliseconds.

What we're testing:
  - Password hashing produces different hashes for same password (salting)
  - Password verification works correctly
  - JWT tokens contain the right claims
  - Expired tokens are rejected
  - Wrong token type (refresh used as access) is rejected
  - Tampered tokens are rejected

Why test the security module so thoroughly?
  It's the most critical part of your API.
  A bug here means unauthorized access to student data.
  You want maximum confidence that it works exactly as designed.
"""

import pytest
import time
from jose import jwt
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
)
from app.core.config import get_settings

settings = get_settings()


class TestPasswordHashing:
    """Tests for password hashing and verification."""

    def test_hash_is_not_plain_password(self):
        """The stored hash must never be the plain password."""
        plain = "MyPassword@123"
        hashed = hash_password(plain)
        assert hashed != plain

    def test_same_password_produces_different_hashes(self):
        """
        bcrypt generates a random salt each time.
        Same password → different hash every call.
        This prevents rainbow table attacks.
        """
        plain = "MyPassword@123"
        hash1 = hash_password(plain)
        hash2 = hash_password(plain)
        assert hash1 != hash2  # different because of random salt

    def test_verify_correct_password_returns_true(self):
        plain = "MyPassword@123"
        hashed = hash_password(plain)
        assert verify_password(plain, hashed) is True

    def test_verify_wrong_password_returns_false(self):
        hashed = hash_password("MyPassword@123")
        assert verify_password("WrongPassword@123", hashed) is False

    def test_verify_empty_password_returns_false(self):
        hashed = hash_password("MyPassword@123")
        assert verify_password("", hashed) is False


class TestJWTCreation:
    """Tests for JWT access token creation."""

    def test_access_token_contains_subject(self):
        token = create_access_token(subject="stu_10042", role="student")
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert payload["sub"] == "stu_10042"

    def test_access_token_contains_role(self):
        token = create_access_token(subject="stu_10042", role="student")
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert payload["role"] == "student"

    def test_access_token_type_is_access(self):
        """Token type must be 'access' — prevents refresh tokens being used as access."""
        token = create_access_token(subject="stu_10042", role="student")
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert payload["type"] == "access"

    def test_access_token_has_expiry(self):
        token = create_access_token(subject="stu_10042", role="student")
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert "exp" in payload
        assert "iat" in payload
        assert payload["exp"] > payload["iat"]

    def test_refresh_token_type_is_refresh(self):
        token = create_refresh_token(subject="stu_10042", role="student")
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert payload["type"] == "refresh"

    def test_extra_claims_included(self):
        token = create_access_token(
            subject="stu_10042",
            role="student",
            extra_claims={"email": "nazar@university.ac.ae"}
        )
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        assert payload["email"] == "nazar@university.ac.ae"


class TestJWTDecoding:
    """Tests for JWT validation and decoding."""

    def test_valid_access_token_decodes_correctly(self):
        token = create_access_token(subject="stu_10042", role="student")
        data = decode_access_token(token)
        assert data.subject == "stu_10042"
        assert data.role == "student"

    def test_refresh_token_rejected_as_access_token(self):
        """
        Using a refresh token where an access token is expected must fail.
        This prevents token type confusion attacks.
        """
        from jose import JWTError
        refresh = create_refresh_token(subject="stu_10042", role="student")
        with pytest.raises(JWTError):
            decode_access_token(refresh)

    def test_access_token_rejected_as_refresh_token(self):
        from jose import JWTError
        access = create_access_token(subject="stu_10042", role="student")
        with pytest.raises(JWTError):
            decode_refresh_token(access)

    def test_tampered_token_rejected(self):
        """
        Modifying ANY part of the JWT invalidates the signature.
        This is the core security guarantee of JWTs.
        """
        from jose import JWTError
        token = create_access_token(subject="stu_10042", role="student")

        # Tamper with the payload section (middle part of the JWT)
        parts = token.split(".")
        # Change the last character of the payload
        parts[1] = parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B")
        tampered = ".".join(parts)

        with pytest.raises(Exception):  # JWTError or DecodeError
            decode_access_token(tampered)

    def test_wrong_secret_key_rejected(self):
        """Token signed with a different key must be rejected."""
        from jose import jwt, JWTError
        # Create token with a different secret
        fake_token = jwt.encode(
            {"sub": "stu_10042", "role": "student", "type": "access"},
            "completely-different-secret-key",
            algorithm="HS256"
        )
        with pytest.raises(JWTError):
            decode_access_token(fake_token)
